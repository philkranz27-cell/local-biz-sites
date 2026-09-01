"""Stockfotos ueber die Pexels-API - kostenlos, kein Kreditkarte, sofortiger Key.
Wichtig: das sind generische Stimmungsbilder, keine echten Fotos des jeweiligen Betriebs -
deshalb steht auf jeder generierten Seite ein Bildnachweis samt Hinweis darauf.
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

# Fallback-Suchbegriff pro Kategorie, falls die KI keinen brauchbaren image_query liefert
# oder die Pexels-Suche dafuer nichts findet.
CATEGORY_IMAGE_FALLBACK = {
    "restaurant": "cozy restaurant interior",
    "hair_salon": "modern hair salon interior",
    "bakery": "artisan bakery bread",
    "cafe": "cozy coffee shop interior",
    "bar": "stylish bar interior",
    "gym": "modern gym interior",
    "florist": "flower shop bouquet",
}


def _search(query: str, count: int) -> list[dict]:
    response = httpx.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": settings.pexels_api_key},
        params={"query": query, "per_page": count, "orientation": "landscape"},
        timeout=15,
    )
    response.raise_for_status()
    photos = response.json().get("photos", [])
    return [
        {
            "url": p["src"]["large2x"],
            "photographer": p["photographer"],
            "source_url": p["url"],
        }
        for p in photos
    ]


def get_photos(image_query: str, category: str, count: int = 4) -> list[dict]:
    if not settings.pexels_configured:
        return []
    for query in (image_query, CATEGORY_IMAGE_FALLBACK.get(category, category)):
        if not query:
            continue
        try:
            photos = _search(query, count)
        except httpx.HTTPError as exc:
            logger.warning("Pexels-Suche fehlgeschlagen fuer %r: %s", query, exc)
            continue
        if photos:
            return photos
    return []
