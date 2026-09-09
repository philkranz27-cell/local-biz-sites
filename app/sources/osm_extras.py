"""Waehlt aus den OSM-Tags die Angaben aus, die auf einer Betriebsseite etwas taugen.

Warum ueberhaupt: Ohne diese Angaben sieht die Demo-Seite jedes Betriebs gleich aus -
Stockfoto, KI-Text, Oeffnungszeiten. Mit ihnen steht dort, was diesen Betrieb ausmacht:
barrierefreier Zugang, Terrasse, griechische Kueche, vegetarisch. Erhebung ueber die
139 bereits erzeugten Seiten: 48 % barrierefrei, 28 % Aussenplaetze, 23 % Kueche,
17 % vegetarisch/vegan, 27 % mit Facebook-Auftritt.

Nur uebernehmen, was sich guten Gewissens veroeffentlichen laesst: Ein falsches
"barrierefrei" auf der Seite eines Betriebs waere schlimmer als gar keine Angabe.
Deshalb wird jeder Wert geprueft, statt Rohtext durchzureichen.
"""

from __future__ import annotations

import json
import re

# Kuechen-Tags sind englisch und teils mit ";" verkettet ("greek;mediterranean").
KUECHE = {
    "german": "deutsche Küche", "bavarian": "bayerische Küche", "italian": "italienische Küche",
    "greek": "griechische Küche", "turkish": "türkische Küche", "asian": "asiatische Küche",
    "chinese": "chinesische Küche", "japanese": "japanische Küche", "sushi": "Sushi",
    "indian": "indische Küche", "thai": "thailändische Küche", "vietnamese": "vietnamesische Küche",
    "mexican": "mexikanische Küche", "spanish": "spanische Küche", "french": "französische Küche",
    "american": "amerikanische Küche", "burger": "Burger", "pizza": "Pizza", "pasta": "Pasta",
    "steak_house": "Steakhaus", "seafood": "Fisch und Meeresfrüchte", "kebab": "Kebab",
    "regional": "regionale Küche", "international": "internationale Küche",
    "mediterranean": "mediterrane Küche", "arab": "arabische Küche", "lebanese": "libanesische Küche",
    "persian": "persische Küche", "korean": "koreanische Küche", "portuguese": "portugiesische Küche",
    "balkan": "Balkanküche", "croatian": "kroatische Küche", "russian": "russische Küche",
    "african": "afrikanische Küche", "ethiopian": "äthiopische Küche", "spanish_tapas": "Tapas",
    "coffee_shop": "Kaffeespezialitäten", "cake": "Kuchen und Torten", "ice_cream": "Eis",
    "bakery": "Backwaren", "sandwich": "Sandwiches", "breakfast": "Frühstück",
    "fish_and_chips": "Fish and Chips", "barbecue": "Grillgerichte", "vegan": "vegane Küche",
    "vegetarian": "vegetarische Küche",
}

# Nur diese Netzwerke - alles andere ist zu selten, um dafuer Logik zu pflegen.
SOZIALE_NETZE = {
    "contact:facebook": ("Facebook", "https://www.facebook.com/"),
    "contact:instagram": ("Instagram", "https://www.instagram.com/"),
}

# Ein Personenname als Betreiber ("Andreas Lippl"), keine Firma ("Muster GmbH") und
# keine Aufzaehlung mehrerer Personen - nur dann laesst sich damit jemand anschreiben.
_RECHTSFORM = re.compile(r"\b(GmbH|UG|AG|KG|OHG|e\.?K\.?|e\.?V\.?|mbH|Co\.|GbR|Stiftung)\b", re.I)
_PERSONENNAME = re.compile(r"^[A-ZÄÖÜ][\wäöüß.\-]+( [A-ZÄÖÜ][\wäöüß.\-]+){1,2}$")

_URL_ERLAUBT = re.compile(r"^https://[A-Za-z0-9._~:/?#@!$&'()*+,;=%\-]+$")


def _soziales_netz(wert: str, basis: str) -> str | None:
    """OSM speichert mal die volle Adresse, mal nur den Benutzernamen."""
    wert = wert.strip()
    if not wert:
        return None
    if wert.startswith("http://"):
        wert = "https://" + wert[7:]
    if not wert.startswith("https://"):
        wert = basis + wert.lstrip("@/")
    return wert if _URL_ERLAUBT.match(wert) else None


def _kuechen(wert: str) -> list[str]:
    gefunden = []
    for teil in wert.split(";"):
        lesbar = KUECHE.get(teil.strip().lower())
        if lesbar and lesbar not in gefunden:
            gefunden.append(lesbar)
    return gefunden[:2]


def extras_aus_tags(tags: dict) -> dict:
    """Gibt nur belegte Felder zurueck - fehlt eine Angabe, taucht sie gar nicht auf."""
    e: dict = {}

    if tags.get("wheelchair") == "yes":
        e["barrierefrei"] = "Barrierefreier Zugang"
    elif tags.get("wheelchair") == "limited":
        e["barrierefrei"] = "Teilweise barrierefrei"

    if tags.get("outdoor_seating") == "yes":
        e["aussenplaetze"] = "Plätze im Freien"
    if tags.get("takeaway") in ("yes", "only"):
        e["mitnehmen"] = "Zum Mitnehmen"
    if tags.get("delivery") == "yes":
        e["lieferung"] = "Lieferservice"
    if tags.get("internet_access") in ("wlan", "yes"):
        e["wlan"] = "WLAN für Gäste"
    if tags.get("air_conditioning") == "yes":
        e["klima"] = "Klimatisiert"

    if tags.get("diet:vegan") in ("yes", "only"):
        e["ernaehrung"] = "Vegane Gerichte"
    elif tags.get("diet:vegetarian") in ("yes", "only"):
        e["ernaehrung"] = "Vegetarische Gerichte"

    if tags.get("payment:credit_cards") == "yes" or tags.get("payment:debit_cards") == "yes":
        e["kartenzahlung"] = "Kartenzahlung möglich"

    kuechen = _kuechen(tags.get("cuisine", ""))
    if kuechen:
        e["kueche"] = kuechen

    netze = {}
    for tag, (titel, basis) in SOZIALE_NETZE.items():
        adresse = _soziales_netz(tags.get(tag, ""), basis)
        if adresse:
            netze[titel] = adresse
    if netze:
        e["soziale_netze"] = netze

    betreiber = (tags.get("operator") or "").strip()
    if betreiber and not _RECHTSFORM.search(betreiber) and _PERSONENNAME.match(betreiber):
        e["inhaber"] = betreiber

    # Filialbetrieb: kauft keine Website bei uns, die Entscheidung faellt in der Zentrale.
    if tags.get("brand") or tags.get("brand:wikidata"):
        e["kette"] = tags.get("brand") or "ja"

    return e


def extras_json(tags: dict) -> str | None:
    extras = extras_aus_tags(tags)
    return json.dumps(extras, ensure_ascii=False) if extras else None


# Reihenfolge der Anzeige: was einen Betrieb am ehesten von seinen Nachbarn
# unterscheidet, steht vorn. "Barrierefrei" ist zwar am haeufigsten belegt, sagt aber
# ueber den Betrieb selbst am wenigsten - deshalb nicht an erster Stelle.
_ANZEIGE = ("kueche", "ernaehrung", "aussenplaetze", "mitnehmen", "lieferung",
            "barrierefrei", "wlan", "kartenzahlung", "klima")


def fakten(extras: dict | None) -> list[str]:
    """Belegte Angaben in Anzeigereihenfolge, hoechstens sechs."""
    if not extras:
        return []
    liste: list[str] = []
    for schluessel in _ANZEIGE:
        wert = extras.get(schluessel)
        if isinstance(wert, list):
            liste.extend(wert)
        elif wert:
            liste.append(wert)
    return liste[:6]
