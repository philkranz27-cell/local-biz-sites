"""Findet die Website eines Betriebs, auch wenn OpenStreetMap sie nicht kennt.

Warum: Das ganze Angebot ergibt nur Sinn fuer Betriebe OHNE Website. Am 18.09.2026 zeigte
eine Pruefung der Mail-Domains, dass rund die Haelfte der vermeintlich website-losen
Betriebe doch eine hat - OSM traegt sie einfach oft nicht ein.

Drei Quellen, in dieser Reihenfolge:
  1. OSM-Tags (website, contact:website, url, ...) - steht schon in der Datenbank
  2. Domain der Mailadresse (app/website_pruefung.py) - info@cinebar.de -> cinebar.de
  3. Domains, die aus Name und Stadt naheliegen: "Cafe Magnolie" in Braunschweig ->
     cafemagnolie.de, cafe-magnolie.de, magnolie-braunschweig.de, ...

Bei 3. ist die Gefahr, einen gleichnamigen Betrieb woanders zu treffen ("Baeckerei
Krause" gibt es hundertfach). Ein Treffer zaehlt deshalb nur, wenn auf der Seite (Start-
seite oder Impressum) auch Stadt, Postleitzahl oder Strasse des Betriebs steht.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.website_pruefung import bewerte_antwort, pruefe_maildomain

logger = logging.getLogger(__name__)

_KOPF = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PhilsWebsites-Pruefung"}

# Woerter, die im Namen stehen, aber selten allein in der Domain.
_FUELLWOERTER = {
    "der", "die", "das", "und", "am", "im", "an", "in", "zum", "zur", "zu", "bei", "von", "vom",
    "the", "and", "of", "gmbh", "ug", "kg", "ek", "inh", "inhaber",
}
# Branchenwoerter: Kommen sie weg, bleibt oft der eigentliche Name ("Cafe Magnolie" ->
# "magnolie"). Allein sind sie nie ein Domainkandidat.
_BRANCHE = {
    "cafe", "caffe", "kaffee", "kaffeebar", "coffee", "bar", "restaurant", "ristorante",
    "trattoria", "pizzeria", "osteria", "bistro", "imbiss", "grill", "kneipe", "gaststaette",
    "gasthaus", "gasthof", "wirtshaus", "friseur", "friseure", "friseursalon", "salon", "hair",
    "haar", "haarstudio", "coiffeur", "barbershop", "barber", "baeckerei", "backstube",
    "konditorei", "blumen", "blumenladen", "floristik", "florist", "blumenhaus", "studio",
    "fitness", "fitnessstudio", "gym", "yoga", "eiscafe", "eis", "cocktailbar", "lounge",
    "shop", "laden", "team",
}


@dataclass
class Befund:
    ergebnis: str        # "website", "tot", "keine" (keine = nichts gefunden)
    url: str | None      # wo die Website steht
    quelle: str          # "osm", "maildomain", "name"


def _ascii(text: str, umlaut_lang: bool) -> str:
    t = text.lower()
    if umlaut_lang:
        t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    t = t.replace("ß", "ss").replace("&", " und ").replace("+", " ")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    return t


def _woerter(text: str, umlaut_lang: bool) -> list[str]:
    t = _ascii(text, umlaut_lang)
    t = re.sub(r"['’`´]s\b", "s", t)          # "Diego's" -> "diegos"
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return [w for w in t.split() if w and w not in _FUELLWOERTER]


# Viele Betriebe stellen ihrer Domain die Branche voran: "Flower Power" in Wiesbaden
# steht unter blumen-flower-power.de. Aus dem Namen allein ist das nicht zu erraten.
_BRANCHENWORT = {
    "florist": ("blumen",), "bakery": ("baeckerei", "backerei"), "cafe": ("cafe",),
    "restaurant": ("restaurant",), "bar": ("bar",), "hair_salon": ("friseur", "salon"),
    "gym": ("fitness",), "yoga": ("yoga",),
}


def kandidaten(name: str, stadt: str | None, kategorie: str | None = None) -> list[str]:
    """Naheliegende Domains fuer einen Betrieb. Hoechstens ~16, meistgenutzte zuerst."""
    domains: list[str] = []

    def dazu(stamm: str, endungen=(".de", ".com")):
        stamm = stamm.strip("-")
        if len(stamm.replace("-", "")) < 4 or len(stamm) > 50:
            return
        for endung in endungen:
            d = stamm + endung
            if d not in domains:
                domains.append(d)

    for umlaut_lang in (True, False):
        woerter = _woerter(name, umlaut_lang)
        if not woerter:
            continue
        ort = "-".join(_woerter(stadt or "", umlaut_lang)[:2])
        eigen = [w for w in woerter if w not in _BRANCHE]
        dazu("".join(woerter))
        dazu("-".join(woerter))
        if eigen and eigen != woerter:
            dazu("".join(eigen), (".de",))
            dazu("-".join(eigen), (".de",))
        if ort and ort not in "".join(woerter):
            dazu("-".join(woerter) + "-" + ort, (".de",))
            dazu("".join(woerter) + "-" + ort, (".de",))
            if eigen:
                dazu("".join(eigen) + "-" + ort, (".de",))
        for vorne in _BRANCHENWORT.get(kategorie or "", ()):
            if vorne not in woerter:
                dazu(vorne + "-" + "-".join(woerter), (".de",))
                dazu(vorne + "".join(woerter), (".de",))
    return domains[:20]


def _abrufen(url: str, timeout: float) -> httpx.Response | None:
    try:
        return httpx.get(url, follow_redirects=True, timeout=timeout, headers=_KOPF)
    except (httpx.HTTPError, UnicodeError, ValueError):
        return None


def _klartext(html: str) -> str:
    t = re.sub(r"<(script|style)\b.*?</\1>", " ", html or "", flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return _ascii(re.sub(r"&[a-z#0-9]+;", " ", t), True)


def _starker_domaintreffer(domain: str, name: str, stadt: str | None) -> bool:
    """Leere Baukasten-Seite, aber die Domain nennt Betrieb UND Stadt
    (bloom-hamburg.de fuer "bloom" in Hamburg) - das reicht als Beweis.

    Ohne Stadt in der Domain nicht: flower-power.com, la-bodega.com und goldenerstern.com
    sehen genauso aus, gehoeren aber mit ziemlicher Sicherheit anderen Betrieben."""
    stamm = domain.rsplit(".", 1)[0].replace("-", "")
    for umlaut_lang in (True, False):
        ort = "".join(_woerter(stadt or "", umlaut_lang)[:2])
        eigen = "".join(w for w in _woerter(name, umlaut_lang) if w not in _BRANCHE)
        if ort and len(eigen) >= 4 and stamm.endswith(ort) and eigen in stamm:
            return True
    return False


def _ortsmerkmale(adresse: str | None, stadt: str | None) -> list[str]:
    """Was auf der Seite eines Betriebs in dieser Stadt stehen muss (eins davon reicht)."""
    merkmale = []
    if stadt:
        merkmale.append(_ascii(stadt, True))
    text = adresse or ""
    plz = re.search(r"(?<!\d)\d{5}(?!\d)", text)
    if plz:
        merkmale.append(plz.group(0))
    strasse = text.split(",")[0]
    strasse = re.sub(r"\s*\d+\s*[a-zA-Z]?\s*$", "", strasse).strip()
    if len(strasse) >= 6:
        s = _ascii(strasse, True)
        merkmale.append(s)
        merkmale.append(s.replace("strasse", "str"))
    return [m for m in merkmale if m]


def _passt(sichtbar: str, roh: str, name_woerter: list[str], ort: list[str]) -> bool:
    """Name UND Ort muessen vorkommen - sonst ist es womoeglich ein Namensvetter.

    Streng, weil ein falscher Treffer einen echten Kunden kostet: troy.de ist ein
    Inkassobuero, kein Friseur - "troy" stand drauf und "Muenchen" irgendwo im Quelltext.
    Deshalb: alle kennzeichnenden Namenswoerter; ist der Name kurz, zusaetzlich das
    Branchenwort ("salon"); der Ort im sichtbaren Text - im Quelltext zaehlt nur die
    genauere Strasse oder Postleitzahl."""
    kennzeichnend = [w for w in name_woerter if w not in _BRANCHE and len(w) >= 3] or name_woerter
    if not all(w in sichtbar or w in roh for w in kennzeichnend):
        return False
    if len("".join(kennzeichnend)) < 6:
        branche = [w for w in name_woerter if w in _BRANCHE]
        if branche and not any(w in sichtbar for w in branche):
            return False
    genauer = ort[1:]   # ort[0] ist die Stadt - im Quelltext zu unspezifisch
    return any(m in sichtbar for m in ort) or any(m in roh for m in genauer)


def pruefe_domain_fuer_betrieb(domain: str, name: str, adresse: str | None, stadt: str | None,
                              timeout: float = 5.0, streng: bool = False) -> tuple[str | None, bool]:
    """(URL, sicher). URL ist None, wenn unter `domain` nichts von diesem Betrieb steht.

    sicher=False heisst: Die Domain heisst wie der Betrieb, die Seite ist aber ein leeres
    Baukasten-Geruest, auf dem nichts zu pruefen ist. Das kann seine Seite sein oder die
    eines Namensvetters - angeschrieben wird er dann trotzdem nicht."""
    antwort = None
    # Manche kleinen Seiten laufen noch ohne Zertifikat - misch-misch.de und
    # cafe-lemberg.de antworteten nur ueber http.
    for url in (f"https://{domain}/", f"https://www.{domain}/", f"http://{domain}/"):
        antwort = _abrufen(url, timeout)
        if antwort is not None:
            break
    if antwort is None:
        return None, False
    if bewerte_antwort(domain, antwort.status_code, str(antwort.url), antwort.text) != "website":
        return None, False
    name_woerter = _woerter(name, True)
    ort = _ortsmerkmale(adresse, stadt)
    if streng and len(ort) > 1:
        # Treffer aus der Websuche: Auch ein Zeitungsartikel ueber den Betrieb nennt Name
        # und Stadt. Strasse oder Postleitzahl stehen aber fast nur auf seiner eigenen Seite.
        ort = ["ohne-stadt-zaehlt-nicht"] + ort[1:]
    if _passt(_klartext(antwort.text), _ascii(antwort.text, True), name_woerter, ort):
        return str(antwort.url), True
    # Die Anschrift steht bei deutschen Seiten spaetestens im Impressum.
    for pfad in ("impressum", "impressum/", "kontakt", "impressum.html"):
        unterseite = _abrufen(urljoin(str(antwort.url), pfad), timeout)
        if unterseite is not None and unterseite.status_code == 200                 and _passt(_klartext(unterseite.text), _ascii(unterseite.text, True),
                           name_woerter, ort):
            return str(antwort.url), True
    if len(_klartext(antwort.text).split()) < 30:
        # Baukasten-Seite (Wix, Jimdo, ...): Der Text kommt erst im Browser.
        if _starker_domaintreffer(domain, name, stadt):
            return str(antwort.url), True
        if _name_als_domain(domain, name):
            return str(antwort.url), False
    return None, False


def _name_als_domain(domain: str, name: str) -> bool:
    """Heisst die Domain genau wie der ganze Name (espressogarage.de)?"""
    stamm = domain.rsplit(".", 1)[0].replace("-", "")
    for umlaut_lang in (True, False):
        woerter = _woerter(name, umlaut_lang)
        if len(woerter) >= 2 and stamm == "".join(woerter):
            return True
    return False


def finde_website(name: str, stadt: str | None, adresse: str | None, email: str | None,
                  osm_website: str | None = None, websuche: bool = False,
                  kategorie: str | None = None) -> Befund:
    """Ergebnis "website" oder "vielleicht" heisst: nicht anschreiben."""
    if websuche:
        from app.websuche import verfuegbar
        websuche = verfuegbar()
    if osm_website:
        return Befund("website", osm_website, "osm")
    maildomain = pruefe_maildomain(email)
    if maildomain == "website":
        return Befund("website", "https://" + email.rsplit("@", 1)[1].lower() + "/", "maildomain")
    unsicher = None
    for domain in kandidaten(name, stadt, kategorie):
        url, sicher = pruefe_domain_fuer_betrieb(domain, name, adresse, stadt)
        if url and sicher:
            return Befund("website", url, "name")
        if url and not unsicher:
            unsicher = url
    if websuche:
        from app.websuche import domains_aus_suche
        for domain in domains_aus_suche(name, stadt):
            url, sicher = pruefe_domain_fuer_betrieb(domain, name, adresse, stadt, streng=True)
            if url and sicher:
                return Befund("website", url, "suche")
    if unsicher:
        return Befund("vielleicht", unsicher, "name")
    if maildomain == "tot":
        return Befund("tot", None, "maildomain")
    return Befund("keine", None, "suche" if websuche else "name")
