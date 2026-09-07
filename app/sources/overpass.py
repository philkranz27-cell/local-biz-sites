"""Lead-Quelle ueber OpenStreetMap statt Google Places: komplett kostenlos, kein
Account, kein API-Key, kein Billing-Risiko. Datenqualitaet ist dafuer inkonsistenter
(kein Rating, Oeffnungszeiten/Website seltener gepflegt) - fuer diesen Anwendungsfall
(Lead-Vorqualifizierung, keine harten Fakten) reicht das.
"""

import json
import logging
import time

import httpx

from app.models import Lead

logger = logging.getLogger(__name__)

# Mehrere Server statt einem: overpass-api.de war ueber Stunden gar nicht erreichbar
# (ConnectTimeout) und die Pipeline lief dadurch komplett ins Leere - ohne dass es
# ausser im Log aufgefallen waere. Die Mirrors sind vollwertige Planet-Kopien, nur
# langsamer und wechselhaft ausgelastet, deshalb reihum probieren.
# Achtung: overpass.osm.ch NICHT aufnehmen - das ist ein reiner Schweiz-Auszug und
# liefert fuer deutsche Staedte stillschweigend 0 Treffer.
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
# Kurzer Verbindungsaufbau (ein toter Server soll nicht 40s kosten), aber grosszuegiges
# Lesefenster - es muss ueber dem Zeitbudget liegen, das die Abfrage dem Server einraeumt
# ([out:json][timeout:90]), sonst brechen wir ab waehrend der Server noch rechnet.
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
HEADERS = {"User-Agent": "local-biz-sites/1.0 (small side project, low volume)"}

# Merkt sich den zuletzt erfolgreichen Server, damit nicht jede Abfrage erneut in den
# Timeout des ausgefallenen Servers laeuft.
_preferred_endpoint = 0

# Zustand der Datenquelle, damit ein Totalausfall im Dashboard sichtbar wird statt nur
# im Log zu stehen - genau das ist einmal stundenlang unbemerkt geblieben.
_last_success_ts: float | None = None
_consecutive_failures = 0


def source_health() -> dict:
    """Fuer die Anzeige im Dashboard: laeuft die Lead-Suche gerade oder nicht?"""
    if _last_success_ts is None and _consecutive_failures == 0:
        return {"state": "unknown", "text": "Noch keine Abfrage seit dem Start"}

    minutes_ago = int((time.time() - _last_success_ts) / 60) if _last_success_ts else None
    if _consecutive_failures == 0:
        return {"state": "ok", "text": "Lead-Suche läuft"}
    if _consecutive_failures < 5:
        wort = "Abfrage" if _consecutive_failures == 1 else "Abfragen"
        return {"state": "warn", "text": f"{_consecutive_failures} {wort} in Folge fehlgeschlagen"}

    since = f"seit {minutes_ago} Min. keine Treffer" if minutes_ago is not None else "noch nie erfolgreich"
    return {
        "state": "down",
        "text": f"OpenStreetMap nicht erreichbar – {since} ({_consecutive_failures} Fehlversuche)",
    }

# Kategorie -> OSM-Tag (key, value). Weitere Kategorien: https://wiki.openstreetmap.org/wiki/Map_features
CATEGORY_OSM_TAGS = {
    "restaurant": ("amenity", "restaurant"),
    "hair_salon": ("shop", "hairdresser"),
    "bakery": ("shop", "bakery"),
    "cafe": ("amenity", "cafe"),
    "bar": ("amenity", "bar"),
    "gym": ("leisure", "fitness_centre"),
    "florist": ("shop", "florist"),
}


def _build_query(tag_key: str, tag_value: str, city: str, max_results: int) -> str:
    return f"""
    [out:json][timeout:90];
    area["name"="{city}"]["boundary"="administrative"]->.searchArea;
    (
      node["{tag_key}"="{tag_value}"](area.searchArea);
      way["{tag_key}"="{tag_value}"](area.searchArea);
    );
    out center tags {max_results};
    """


def _address_from_tags(tags: dict) -> str | None:
    parts = [
        " ".join(p for p in [tags.get("addr:street"), tags.get("addr:housenumber")] if p),
        " ".join(p for p in [tags.get("addr:postcode"), tags.get("addr:city")] if p),
    ]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _lead_from_element(element: dict, category: str, city: str) -> Lead | None:
    tags = element.get("tags", {})
    name = tags.get("name")
    if not name:
        return None
    return Lead(
        place_id=f"{element['type']}/{element['id']}",
        name=name,
        category=category,
        city=city,
        address=_address_from_tags(tags),
        phone=tags.get("contact:phone") or tags.get("phone"),
        existing_website=tags.get("website") or tags.get("contact:website"),
        opening_hours_json=json.dumps([tags["opening_hours"]], ensure_ascii=False) if tags.get("opening_hours") else None,
        osm_email=tags.get("contact:email") or tags.get("email"),
        osm_image=tags.get("image") or tags.get("wikimedia_commons"),
    )


def find_leads(category: str, city: str, max_results: int) -> list[Lead]:
    tag = CATEGORY_OSM_TAGS.get(category)
    if tag is None:
        logger.warning("Unbekannte Kategorie fuer OSM-Suche: %s (siehe CATEGORY_OSM_TAGS)", category)
        return []
    tag_key, tag_value = tag

    global _preferred_endpoint, _last_success_ts, _consecutive_failures

    query = _build_query(tag_key, tag_value, city, max_results)
    cooldown = 3
    elements = None
    failures: list[str] = []

    # Beim zuletzt erfolgreichen Server anfangen und bei Ausfall zum naechsten wechseln.
    for offset in range(len(OVERPASS_ENDPOINTS)):
        index = (_preferred_endpoint + offset) % len(OVERPASS_ENDPOINTS)
        endpoint = OVERPASS_ENDPOINTS[index]
        host = endpoint.split("//", 1)[-1].split("/", 1)[0]
        try:
            response = httpx.post(endpoint, headers=HEADERS, data={"data": query}, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                # Der Server drosselt uns - laenger pausieren statt sofort wieder
                # anzufragen, sonst verlaengert sich die Sperre nur.
                cooldown = 30
            response.raise_for_status()
            payload = response.json()
            remark = payload.get("remark")
            if remark:
                # Overpass meldet Abbrueche NICHT per Statuscode, sondern als "remark" in
                # einer 200er-Antwort mit unvollstaendigen Daten. Ohne diese Pruefung
                # haetten wir Teilergebnisse stillschweigend als vollstaendig verbucht.
                raise httpx.HTTPError(f"Overpass-Hinweis: {remark[:120]}")
            elements = payload.get("elements", [])
        except httpx.HTTPError as exc:
            failures.append(f"{host}: {type(exc).__name__}")
            continue

        if offset:
            logger.info("Overpass: auf %s ausgewichen (%s)", host, "; ".join(failures))
        _preferred_endpoint = index
        _last_success_ts = time.time()
        _consecutive_failures = 0
        break

    if elements is None:
        _consecutive_failures += 1
        # Alle Server ausgefallen - als Fehler melden, denn dann findet die Pipeline
        # nichts mehr und das darf nicht still passieren.
        logger.error(
            "Overpass-Anfrage fehlgeschlagen fuer %s/%s auf allen %d Servern: %s",
            category, city, len(OVERPASS_ENDPOINTS), "; ".join(failures),
        )
        time.sleep(cooldown)
        return []

    # Oeffentliche, kostenlose Infrastruktur - nicht ohne Pause hintereinander anfragen.
    time.sleep(cooldown)

    leads = [_lead_from_element(el, category, city) for el in elements]
    return [lead for lead in leads if lead is not None]
