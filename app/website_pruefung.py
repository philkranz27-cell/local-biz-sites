"""Hat der Betrieb schon eine Website - obwohl OpenStreetMap keine kennt?

Bis zum 18.09.2026 zaehlte nur das OSM-Tag "website". Das fehlt aber oft: Von den ersten
20 angeschriebenen Betrieben hatten mindestens sechs eine eigene Seite (CINE BAR,
Menehune Cocktailbar, Osteria al Vecchio Torchio, ...), und alle bekamen eine Mail, die
erklaert, warum sich eine eigene Website lohnt.

Der verlaesslichste Hinweis steckt in der Mailadresse: info@cinebar.de gehoert zu
cinebar.de, und dort steht die Seite. Bei Freemailern (gmx.de, gmail.com, ...) verraet die
Adresse nichts - dort bleibt es beim OSM-Tag.

Drei Ergebnisse:
  "website"  - unter der Domain antwortet eine echte Seite  -> nicht anschreiben
  "tot"      - Domain verkauft, abgelaufen oder auf eine fremde Seite umgeleitet. Eine
               Mail an diese Adresse kommt wahrscheinlich nicht an, und wenn doch, liest
               sie womoeglich jemand anderes                -> nicht per Mail anschreiben
  "keine"    - Domain antwortet nicht                      -> anschreiben
  None       - Freemailer, nichts zu pruefen
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from app.outreach.antworten import FREEMAILER

logger = logging.getLogger(__name__)

# Seiten, die zwar antworten, aber keine Website des Betriebs sind.
_GEPARKT = re.compile(
    r"steht zum verkauf|domain is for sale|domain ist zu verkaufen|this domain (is|may be) for sale|"
    r"website expired|domain expired|abgelaufen|parked|geparkt|sedo|dan\.com|"
    r"hier entsteht (eine|die) neue|under construction|coming soon|baustelle|"
    r"default web page|welcome to nginx|it works!|plesk|strato.*platzhalter|"
    r"diese domain wurde|domain registriert|webhosting",
    re.IGNORECASE,
)


SOZIALE_NETZE = {"instagram.com", "facebook.com", "fb.com", "linktr.ee", "tiktok.com"}


def _registrierbar(host: str) -> str:
    """www.cinebar.de -> cinebar.de. Grob, reicht aber fuer .de/.com/.net/.eu."""
    teile = host.lower().strip(".").split(".")
    return ".".join(teile[-2:]) if len(teile) >= 2 else host.lower()


def bewerte_antwort(domain: str, status: int, end_url: str, html: str) -> str:
    """Reine Auswertung, ohne Netz - damit sie testbar ist."""
    if status >= 400:
        return "keine" if status in (404, 410) and not _GEPARKT.search(html or "") else "tot"
    ziel = _registrierbar(urlparse(end_url).hostname or "")
    if ziel in SOZIALE_NETZE:
        # croenlein.com leitet auf Instagram um: Der Betrieb hat keine Website, nur ein
        # Profil - genau die Zielgruppe. Die Mail-Domain selbst ist in Ordnung.
        return "keine"
    stamm = _registrierbar(domain).split(".")[0].replace("-", "")
    if ziel != _registrierbar(domain) and len(stamm) >= 4 and stamm in ziel.replace("-", ""):
        # losteria.de -> losteria.net: dieselbe Firma unter einer anderen Endung.
        return "website"
    if ziel != _registrierbar(domain):
        # Umgeleitet auf eine fremde Domain: Domainhandel, Spam, Parkplatz. Eine eigene
        # Website, die auf eine andere eigene Domain zeigt, wird so auch als "tot"
        # gewertet - lieber eine Mail zu wenig als eine an einen Fremden.
        return "tot"
    titel = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    anfang = (titel.group(1) if titel else "") + " " + (html or "")[:4000]
    if _GEPARKT.search(anfang):
        return "tot"
    # Auch eine fast leere Seite zaehlt als Website: Baukaesten wie Wix oder Jimdo
    # liefern oft nur ein Geruest aus, das der Browser erst fuellt. Im Zweifel lieber
    # nicht anschreiben als jemandem mit Website eine Website anbieten.
    return "website"


def pruefe_maildomain(email: str | None, timeout: float = 12.0) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].lower().strip()
    if domain in FREEMAILER:
        return None
    for url in (f"https://{domain}/", f"https://www.{domain}/", f"http://{domain}/"):
        try:
            antwort = httpx.get(url, follow_redirects=True, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0 (PhilsWebsites Pruefung)"})
        except httpx.HTTPError:
            continue
        return bewerte_antwort(domain, antwort.status_code, str(antwort.url), antwort.text)
    return "keine"
