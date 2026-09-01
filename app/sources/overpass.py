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

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "local-biz-sites/1.0 (small side project, low volume)"}

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
    [out:json][timeout:25];
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
    )


def find_leads(category: str, city: str, max_results: int) -> list[Lead]:
    tag = CATEGORY_OSM_TAGS.get(category)
    if tag is None:
        logger.warning("Unbekannte Kategorie fuer OSM-Suche: %s (siehe CATEGORY_OSM_TAGS)", category)
        return []
    tag_key, tag_value = tag

    cooldown = 3
    try:
        response = httpx.post(
            OVERPASS_URL,
            headers=HEADERS,
            data={"data": _build_query(tag_key, tag_value, city, max_results)},
            timeout=30,
        )
        if response.status_code == 429:
            # Der oeffentliche Server drosselt uns - laenger Pause machen statt sofort
            # wieder anzufragen, sonst verlaengert sich die Sperre nur.
            cooldown = 30
        response.raise_for_status()
        elements = response.json().get("elements", [])
    except httpx.HTTPError as exc:
        logger.error("Overpass-Anfrage fehlgeschlagen fuer %s/%s: %s", category, city, exc)
        return []
    finally:
        # Oeffentliche, kostenlose Infrastruktur - nicht ohne Pause hintereinander anfragen.
        time.sleep(cooldown)

    leads = [_lead_from_element(el, category, city) for el in elements]
    return [lead for lead in leads if lead is not None]
