"""Echte Fotos eines Betriebs, sofern OpenStreetMap eines kennt.

Die Demo-Seiten arbeiten sonst mit Stockfotos - Stimmungsbildern, die zur Branche
passen, aber nicht den Betrieb zeigen. Ein echtes Foto ist offensichtlich besser.
Nur: In der Stichprobe hatte genau 1 von 60 Betrieben ein Foto in OSM hinterlegt.
Das hier hilft also einer kleinen Minderheit - aber es ist der einzige Weg zu einem
echten Bild, der uns rechtlich offensteht.

Ausdruecklich NICHT: Fotos von Google, Facebook oder Instagram uebernehmen. Die sind
urheberrechtlich geschuetzt, und ausgerechnet dem Betrieb sein eigenes Foto auf einer
fremden Seite zu praesentieren waere der schnellste Weg zu Aerger.

Die Bilder auf Wikimedia Commons stehen unter freien Lizenzen, die fast immer eine
Namensnennung verlangen - deshalb holt das Modul Urheber und Lizenz gleich mit.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote, unquote

import httpx

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/"
HEADERS = {"User-Agent": "local-biz-sites/1.0 (kontakt.philswebsites@gmail.com)"}
TIMEOUT = 20


def _dateiname(wert: str) -> str | None:
    """Aus einem OSM-image-Tag den Commons-Dateinamen ziehen.

    Ueblich sind "File:Foo.jpg", "commons.wikimedia.org/wiki/File:Foo.jpg" und
    Varianten mit Unterstrichen oder Prozentkodierung."""
    wert = (wert or "").strip()
    treffer = re.search(r'(?:File|Datei):([^/?#]+)$', wert)
    if treffer:
        return unquote(treffer.group(1)).replace("_", " ")
    return None


def _lizenz(datei: str) -> dict:
    """Urheber und Lizenz von Commons holen - die Lizenzen verlangen die Nennung."""
    try:
        antwort = httpx.get(
            COMMONS_API, headers=HEADERS, timeout=TIMEOUT,
            params={"action": "query", "titles": f"File:{datei}", "prop": "imageinfo",
                    "iiprop": "extmetadata", "format": "json"},
        ).json()
        seite = next(iter(antwort["query"]["pages"].values()))
        meta = seite["imageinfo"][0]["extmetadata"]
    except Exception:
        logger.warning("Lizenzangaben zu %s nicht abrufbar", datei)
        return {}

    def feld(name: str) -> str:
        wert = str(meta.get(name, {}).get("value", "")).strip()
        return re.sub(r"<[^>]+>", "", wert)  # Commons liefert teils HTML

    return {"autor": feld("Artist"), "lizenz": feld("LicenseShortName"),
            "lizenz_url": feld("LicenseUrl")}


def hole_foto(image_tag: str | None) -> dict | None:
    """Gibt ein Bild im selben Format wie die Pexels-Fotos zurueck, oder None.

    Bewusst streng: Nur Wikimedia Commons und direkte Bildadressen. Bei allem anderen
    ist die Lizenz unklar, und ein Bild mit unklarer Lizenz gehoert nicht auf eine
    Seite, die wir jemandem schicken."""
    if not image_tag:
        return None

    datei = _dateiname(image_tag)
    if datei:
        angaben = _lizenz(datei)
        return {
            "url": FILEPATH + quote(datei.replace(" ", "_")),
            "photographer": angaben.get("autor") or "unbekannt",
            "source_url": f"https://commons.wikimedia.org/wiki/File:{quote(datei.replace(' ', '_'))}",
            "lizenz": angaben.get("lizenz") or "",
            "lizenz_url": angaben.get("lizenz_url") or "",
            "echt": True,   # zeigt tatsaechlich diesen Betrieb
        }

    if re.match(r"^https?://\S+\.(?:jpe?g|png|webp)$", image_tag.strip(), re.I):
        # Direkt verlinktes Bild. Herkunft und Lizenz sind unbekannt, deshalb nur die
        # Adresse als Nachweis - und der Hinweis "echt" bleibt aus.
        return None

    return None
