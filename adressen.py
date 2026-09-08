"""Ergaenzt unvollstaendige Postanschriften, damit mehr Briefe verschickt werden koennen.

OpenStreetMap liefert Adressen haeufig nur bruchstueckhaft: mal fehlt die Postleitzahl,
mal die Hausnummer, mal steht nur "50667" da. Fuer briefe.py sind solche Leads unbrauchbar -
ein Brief ohne vollstaendige Anschrift kommt nicht an und kostet trotzdem Porto.

Zwei Schritte, beide kostenlos und ohne Account:
1. Den OSM-Eintrag erneut abfragen. Oft sind die addr:*-Tags doch vorhanden, standen aber
   beim ersten Import nicht im abgefragten Umfang.
2. Bleibt etwas offen, ueber die Koordinaten bei Nominatim rueckwaerts suchen.

Nominatim erlaubt hoechstens eine Anfrage pro Sekunde und verlangt eine echte
Kontaktadresse im User-Agent - beides wird hier eingehalten. Ohne das wird gesperrt,
und zwar zu Recht: Der Dienst wird von Freiwilligen bezahlt.

Aufruf:  .venv/Scripts/python.exe adressen.py [--schreiben]
Ohne --schreiben nur anzeigen, was sich aendern wuerde.
"""

from __future__ import annotations

import re
import sys
import time

import httpx

from app import db
from app.config import settings
from app.sources.overpass import HEADERS, OVERPASS_ENDPOINTS, REQUEST_TIMEOUT

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
# Nominatim verlangt eine erreichbare Kontaktadresse. Die aus dem Impressum ist die
# ehrlichste Angabe - so kann der Betreiber sich melden, statt einfach zu sperren.
NOMINATIM_HEADERS = {
    "User-Agent": f"local-biz-sites/1.0 ({settings.from_email or 'kontakt'})"
}

PLZ = re.compile(r"(?<!\d)\d{5}(?!\d)")
HAUSNUMMER = re.compile(r"\d+\s*[a-zA-Z]?\s*,")


def vollstaendig(adresse: str | None) -> bool:
    a = (adresse or "").strip()
    return bool(PLZ.search(a)) and bool(HAUSNUMMER.search(a))


def _aus_tags(tags: dict) -> str | None:
    """Adresse aus den OSM-Tags zusammensetzen, so wie overpass.py es auch tut."""
    strasse = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
    ort = " ".join(x for x in (tags.get("addr:postcode"), tags.get("addr:city")) if x)
    teile = [t for t in (strasse, ort) if t]
    return ", ".join(teile) if teile else None


def _osm_abfragen(place_ids: list[str]) -> dict[str, dict]:
    """Tags und Koordinaten fuer die gegebenen OSM-Objekte holen."""
    nodes = [p.split("/")[1] for p in place_ids if p.startswith("node/")]
    ways = [p.split("/")[1] for p in place_ids if p.startswith("way/")]
    if not nodes and not ways:
        return {}

    abfrage = "[out:json][timeout:90];("
    if nodes:
        abfrage += f"node(id:{','.join(nodes)});"
    if ways:
        abfrage += f"way(id:{','.join(ways)});"
    abfrage += ");out center tags;"

    for endpunkt in OVERPASS_ENDPOINTS:
        try:
            antwort = httpx.post(endpunkt, headers=HEADERS, data={"data": abfrage},
                                 timeout=REQUEST_TIMEOUT)
            if antwort.status_code != 200:
                continue
            daten = antwort.json()
            if "remark" in daten:
                continue
            return {f"{e['type']}/{e['id']}": e for e in daten.get("elements", [])}
        except httpx.HTTPError:
            continue
    return {}


def _rueckwaerts(lat: float, lon: float) -> str | None:
    """Koordinaten -> Anschrift. Genau eine Anfrage, danach wartet der Aufrufer."""
    try:
        antwort = httpx.get(NOMINATIM, headers=NOMINATIM_HEADERS, timeout=30, params={
            "lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1, "zoom": 18,
        })
        adresse = antwort.json().get("address", {})
    except Exception:
        return None

    strassenname = adresse.get("road")
    hausnummer = adresse.get("house_number")

    # Haeufigster Fall: Strasse, PLZ und Ort sind da, nur die Hausnummer fehlt, weil der
    # Kartenpunkt an keinem adressierten Gebaeude haengt. Dann beim Nachbargebaeude
    # nachsehen - streng abgesichert, siehe _hausnummer_aus_nachbarschaft.
    if strassenname and not hausnummer:
        hausnummer = _hausnummer_aus_nachbarschaft(lat, lon, strassenname)

    strasse = " ".join(x for x in (strassenname, hausnummer) if x)
    ort = " ".join(x for x in (adresse.get("postcode"),
                               adresse.get("city") or adresse.get("town") or adresse.get("village")) if x)
    teile = [t for t in (strasse, ort) if t]
    return ", ".join(teile) if teile else None


def _hausnummer_aus_nachbarschaft(lat: float, lon: float, strasse: str) -> str | None:
    """Hausnummer vom naechstgelegenen Gebaeude uebernehmen - aber nur unter strengen
    Bedingungen.

    Warum so vorsichtig: Bei "Kieser Training" (Ritterstrasse, Dresden) lag das naechste
    adressierte Gebaeude 15 m entfernt an der *Metzer Strasse*. Blind uebernommen waere
    der Brief an eine falsche Anschrift gegangen. Deshalb muss der Strassenname
    uebereinstimmen und das Gebaeude hoechstens 12 m entfernt sein - dann steht der
    Kartenpunkt praktisch im Haus."""
    abfrage = (f'[out:json][timeout:40];('
               f'node(around:12,{lat},{lon})["addr:housenumber"];'
               f'way(around:12,{lat},{lon})["addr:housenumber"];);out center tags;')
    for endpunkt in OVERPASS_ENDPOINTS:
        try:
            antwort = httpx.post(endpunkt, headers=HEADERS, data={"data": abfrage},
                                 timeout=REQUEST_TIMEOUT)
            if antwort.status_code != 200 or "remark" in antwort.json():
                continue
            for element in antwort.json().get("elements", []):
                tags = element.get("tags", {})
                if tags.get("addr:street") == strasse and tags.get("addr:housenumber"):
                    return tags["addr:housenumber"]
            return None
        except httpx.HTTPError:
            continue
    return None


def main() -> int:
    schreiben = "--schreiben" in sys.argv

    offen = [l for l in db.get_all_leads(limit=1000)
             if l["site_slug"] and not vollstaendig(l["address"])]
    if not offen:
        print("Alle Anschriften sind vollstaendig.")
        return 0
    print(f"{len(offen)} Betriebe mit unvollstaendiger Anschrift\n")

    osm = _osm_abfragen([l["place_id"] for l in offen])
    if not osm:
        print("Overpass nicht erreichbar - spaeter erneut versuchen.")
        return 1

    repariert = ohne_erfolg = 0
    for lead in offen:
        element = osm.get(lead["place_id"])
        if not element:
            ohne_erfolg += 1
            continue

        neu = _aus_tags(element.get("tags", {}))

        if not vollstaendig(neu):
            mitte = element.get("center") or element
            lat, lon = mitte.get("lat"), mitte.get("lon")
            if lat and lon:
                gefunden = _rueckwaerts(lat, lon)
                # Nominatim: hoechstens eine Anfrage pro Sekunde.
                time.sleep(1.1)
                if vollstaendig(gefunden):
                    neu = gefunden

        if vollstaendig(neu):
            print(f"  OK  {lead['name'][:34]:36} {lead['address'] or '(leer)'}  ->  {neu}")
            if schreiben:
                with db.get_connection() as conn:
                    conn.execute("UPDATE leads SET address = ? WHERE id = ?", (neu, lead["id"]))
            repariert += 1
        else:
            print(f"  --  {lead['name'][:34]:36} bleibt unvollstaendig")
            ohne_erfolg += 1

    print(f"\nergaenzt: {repariert} | weiterhin offen: {ohne_erfolg}")
    if repariert and not schreiben:
        print("\nNichts gespeichert. Mit --schreiben uebernehmen:")
        print("  .venv/Scripts/python.exe adressen.py --schreiben")
    return 0


if __name__ == "__main__":
    sys.exit(main())
