"""Websuche nach der Website eines Betriebs - fuer die Faelle, die man nicht erraten kann.

Die Namenssuche in app/website_suche.py findet nur Domains, die aus dem Namen folgen. Viele
tun das nicht: "Die Eule" in Essen steht unter hotelfabritz.de. Eine Suchmaschine findet so
etwas, wenn man "Die Eule Essen" sucht.

Benutzt die Brave Search API: 5 Dollar pro 1.000 Suchen, dafuer 5 Dollar Gratis-
Guthaben jeden Monat - also 1.000 Suchen umsonst (Stand September 2026). Ohne
BRAVE_API_KEY in der .env ist sie aus - dann bleibt es bei OSM, Mail-Domain und Namenssuche.
Weil das Kontingent knapp ist, wird nur gesucht, wenn ein Betrieb gleich angeschrieben
werden soll, und nie mehr als WEBSUCHE_PRO_MONAT Mal (Standard 950 - bleibt unter dem
Gratis-Guthaben, kostet also nichts).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_ZAEHLER = Path(settings.db_path).parent / "websuche_zaehler.json"

# Treffer auf diesen Seiten sind Eintraege UEBER den Betrieb, nicht seine Website.
VERZEICHNISSE = {
    "facebook.com", "instagram.com", "tiktok.com", "youtube.com", "twitter.com", "x.com",
    "linkedin.com", "pinterest.com", "tripadvisor.de", "tripadvisor.com", "yelp.de", "yelp.com",
    "google.com", "google.de", "goo.gl", "gelbeseiten.de", "dasoertliche.de", "dastelefonbuch.de",
    "11880.com", "meinestadt.de", "golocal.de", "cylex.de", "branchenbuch.de", "stadtbranchenbuch.com",
    "speisekarte.de", "speisekarte.menu", "lieferando.de", "wolt.com", "ubereats.com",
    "opentable.de", "opentable.com", "quandoo.de", "thefork.de", "treatwell.de", "planity.com",
    "wikipedia.org", "wikidata.org", "openstreetmap.org", "kennstdueinen.de", "werkenntdenbesten.de",
    "restaurantguru.com", "restaurant-guru.de", "foursquare.com", "hotfrog.de", "firmenwissen.de",
    "northdata.de", "northdata.com", "unternehmensregister.de", "bundesanzeiger.de", "yably.de",
    "marcopolo.de", "prinz.de", "qype.com", "linktr.ee", "apple.com", "bing.com", "wlw.de",
    "stadtplan.net", "stadtbekannt.de", "tagesspiegel.de", "falstaff.com", "falstaff.de",
    "mapquest.com", "waz.de", "ruhrnachrichten.de", "rp-online.de", "ksta.de", "express.de",
    "sueddeutsche.de", "abendzeitung-muenchen.de", "tz.de", "merkur.de", "bild.de", "t-online.de",
    "welt.de", "spiegel.de", "zeit.de", "faz.net", "stern.de", "mopo.de", "ndr.de", "wdr.de",
    "br.de", "swr.de", "mdr.de", "hr.de", "rbb24.de", "lvz.de", "sz-online.de", "saechsische.de",
    "haz.de", "neue-westfaelische.de", "wn.de", "noz.de", "weser-kurier.de", "stuttgarter-zeitung.de",
    "stuttgarter-nachrichten.de", "augsburger-allgemeine.de", "nordbayern.de", "mainpost.de",
    "hna.de", "fr.de", "fnp.de", "badische-zeitung.de", "ka-news.de", "mannheimer-morgen.de",
    "ln-online.de", "kn-online.de", "ostsee-zeitung.de", "svz.de", "nnn.de", "volksstimme.de",
    "mz.de", "thueringer-allgemeine.de", "otz.de", "tlz.de", "freiepresse.de", "aachener-zeitung.de",
    "general-anzeiger-bonn.de", "wz.de", "derwesten.de", "lokalkompass.de", "nw.de",
    "creditreform.de", "handelsregister.de", "firmen.wko.at", "companyhouse.de", "online-handelsregister.de",
    "gastroguide.de", "gastronomie.de", "friseur.com", "salonkee.de", "shore.com", "booksy.com",
    "doctolib.de", "jameda.de", "urlaubsguru.de", "holidaycheck.de", "booking.com", "hrs.de",
    "trivago.de", "expedia.de", "airbnb.de", "ebay-kleinanzeigen.de", "kleinanzeigen.de", "indeed.com",
    "stepstone.de", "yellowmap.de", "stadtbranchenbuch.de", "branchen-info.net", "werliefertwas.de",
    "partyamt.de", "eventbrite.de", "eventim.de", "meetup.com", "rausgegangen.de", "prinz.de",
}


# Stadtportale und Gutscheinseiten fuehren jeden Laden der Stadt mit Anschrift auf -
# "Cupido coffee Oldenburg" landete so auf virtuelle-innenstadt-oldenburg.de.
_PORTAL_MUSTER = re.compile(
    r"innenstadt|stadtmarketing|citymarketing|stadtportal|stadtinfo|city-?guide|"
    r"gutschein|einkaufen-in|wirsind|lieblingsladen|standort-?verzeichnis",
    re.IGNORECASE,
)


def _registrierbar(host: str) -> str:
    teile = (host or "").lower().strip(".").split(".")
    return ".".join(teile[-2:]) if len(teile) >= 2 else (host or "").lower()


def _kontingent_frei() -> bool:
    monat = date.today().strftime("%Y-%m")
    try:
        daten = json.loads(_ZAEHLER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        daten = {}
    return daten.get(monat, 0) < settings.websuche_pro_monat


def _zaehlen() -> None:
    monat = date.today().strftime("%Y-%m")
    try:
        daten = json.loads(_ZAEHLER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        daten = {}
    daten[monat] = daten.get(monat, 0) + 1
    try:
        _ZAEHLER.write_text(json.dumps(daten), encoding="utf-8")
    except OSError:
        pass


def verfuegbar() -> bool:
    return bool(settings.brave_api_key) and _kontingent_frei()


def domains_aus_suche(name: str, stadt: str | None) -> list[str]:
    """Domains aus den ersten Suchtreffern, ohne Verzeichnisse und soziale Netze."""
    if not verfuegbar():
        return []
    _zaehlen()
    try:
        antwort = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": f"{name} {stadt or ''}".strip(), "country": "de", "search_lang": "de",
                    "count": 10},
            headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
            timeout=15,
        )
        if antwort.status_code == 429:
            time.sleep(1.5)   # kostenloser Zugang: eine Suche pro Sekunde
            return []
        antwort.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Websuche fehlgeschlagen fuer %s: %s", name, exc)
        return []
    domains: list[str] = []
    for treffer in antwort.json().get("web", {}).get("results", []):
        domain = _registrierbar(urlparse(treffer.get("url", "")).hostname or "")
        if (domain and domain not in VERZEICHNISSE and domain not in domains
                and not _PORTAL_MUSTER.search(domain)):
            domains.append(domain)
    return domains[:5]
