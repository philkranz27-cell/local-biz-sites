"""Erkennt, ob ein angeschriebener Betrieb geantwortet hat - und ob eine Mail gar nicht
ankam.

Antworten auf kontakt@philswebsites.de laufen ueber ImprovMX ins Gmail-Postfach. Von
dort holt dieser Job sie per IMAP. Bewusst eng: Gesucht wird nur nach Absendern, die wir
selbst angeschrieben haben (plus deren Firmendomain), und nach Unzustellbar-Meldungen.
Alles andere im Postfach wird weder abgerufen noch gespeichert.

Nur lesend: Abgerufen wird mit BODY.PEEK, das Postfach wird readonly geoeffnet - eine
Mail, die hier erkannt wird, bleibt in Gmail ungelesen.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timezone
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from app import db
from app.config import settings

logger = logging.getLogger(__name__)

AUSZUG_ZEICHEN = 1500

# Bei diesen Anbietern sagt die Domain nichts ueber den Betrieb - eine Mail von
# irgendwem@gmx.de ist nicht automatisch eine Antwort von Friseursalon Hammerschmidt.
FREEMAILER = {
    "gmx.de", "gmx.net", "web.de", "gmail.com", "googlemail.com", "t-online.de",
    "outlook.de", "outlook.com", "hotmail.com", "hotmail.de", "live.de", "yahoo.de",
    "yahoo.com", "arcor.de", "freenet.de", "icloud.com", "aol.com", "posteo.de", "mail.de",
}

# Wo der zitierte Verlauf beginnt - danach steht nur noch unsere eigene Mail.
_ZITAT_BEGINN = re.compile(
    r"^\s*(Am .{5,120}schrieb.*:|On .{5,120}wrote:|-{2,}\s*Original|Von:\s|From:\s|"
    r"_{5,}|Gesendet von meinem|Sent from my)",
    re.IGNORECASE | re.MULTILINE,
)


def _dekodiere(wert: str | None) -> str:
    if not wert:
        return ""
    teile = []
    for teil, kodierung in decode_header(wert):
        if isinstance(teil, bytes):
            try:
                teile.append(teil.decode(kodierung or "utf-8", errors="replace"))
            except LookupError:
                teile.append(teil.decode("utf-8", errors="replace"))
        else:
            teile.append(teil)
    return "".join(teile)


def _teiltext(teil: Message) -> str:
    inhalt = teil.get_payload(decode=True)
    if not inhalt:
        return ""
    try:
        return inhalt.decode(teil.get_content_charset() or "utf-8", errors="replace")
    except LookupError:
        return inhalt.decode("utf-8", errors="replace")


def textkoerper(nachricht: Message) -> str:
    """Lesbarer Text: text/plain bevorzugt, sonst HTML ohne Tags. Anhaenge nie."""
    klartext, html = "", ""
    for teil in nachricht.walk() if nachricht.is_multipart() else [nachricht]:
        if teil.get_content_maintype() == "multipart":
            continue
        if "attachment" in (teil.get("Content-Disposition") or "").lower():
            continue
        typ = teil.get_content_type()
        if typ == "text/plain" and not klartext:
            klartext = _teiltext(teil)
        elif typ in ("text/html", "message/delivery-status") and not html:
            html = _teiltext(teil)
    text = klartext
    if not text and html:
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;?", " ", text)
    return text


def auszug(text: str) -> str:
    """Nur das Neue: zitierter Verlauf und '>'-Zeilen raus, gekuerzt."""
    treffer = _ZITAT_BEGINN.search(text)
    if treffer:
        text = text[:treffer.start()]
    zeilen = [z for z in text.splitlines() if not z.lstrip().startswith(">")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(zeilen)).strip()
    if len(text) > AUSZUG_ZEICHEN:
        text = text[:AUSZUG_ZEICHEN].rstrip() + " […]"
    return text


def adresse_in_meldung(text: str, adressen: list[str]) -> str | None:
    """Welche unserer Adressen nennt eine Unzustellbar-Meldung? Der Vergleich ohne
    Gross-/Kleinschreibung, weil Mailserver die Adresse gern umschreiben."""
    klein = text.lower()
    for adresse in adressen:
        if adresse and adresse.lower() in klein:
            return adresse
    return None


# Postfaecher, deren oertlicher Teil nichts Eigenes ist - danach zu suchen wuerde jede
# beliebige Firmenmail treffen.
_ALLERWELTS_POSTFACH = {
    "info", "kontakt", "contact", "mail", "email", "office", "buero", "team", "service",
    "post", "hallo", "hello", "shop", "laden", "praxis", "salon", "restaurant", "cafe",
}
# gmail.com und googlemail.com sind dasselbe Konto. Nadja Dahlmann stand in OSM mit
# @googlemail.com und antwortete am 18.09.2026 von @gmail.com - die Antwort fiel durch.
_GLEICHE_ANBIETER = [{"gmail.com", "googlemail.com"}]


def _ortsteil(adresse: str) -> str:
    return adresse.rsplit("@", 1)[0].lower() if "@" in adresse else ""


def ist_derselbe_absender(unsere_adresse: str, from_header: str) -> bool:
    """Kommt die Mail von dem Betrieb, den wir angeschrieben haben?

    Gleiche Adresse, dieselbe Firmendomain - oder bei Freemailern derselbe Postfachname
    bei einem gleichwertigen Anbieter (gmail/googlemail)."""
    absender = parseaddr(from_header or "")[1].lower()
    unsere = (unsere_adresse or "").lower()
    if not absender or not unsere:
        return False
    if absender == unsere:
        return True
    d_absender, d_unser = _domain(absender), _domain(unsere)
    if d_unser and d_unser not in FREEMAILER and d_absender == d_unser:
        return True
    gleichwertig = d_absender == d_unser or any(
        {d_absender, d_unser} <= gruppe for gruppe in _GLEICHE_ANBIETER)
    return gleichwertig and _ortsteil(absender) == _ortsteil(unsere)


def _domain(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].lower() if "@" in adresse else ""


def _ordner_zum_durchsuchen(imap: imaplib.IMAP4_SSL) -> list[str]:
    """Welche Ordner durchsucht werden.

    Gmail hat einen Ordner mit dem IMAP-Merkmal "All", der alles enthaelt, auch Archiviertes -
    dann reicht der. Andere Anbieter haben keinen: Bei web.de landen Mails von fremden
    Absendern oft im Ordner "Unbekannt", verdaechtige im Spam. Eine Antwort von einem
    Betrieb, mit dem man noch nie geschrieben hat, ist genau so ein fremder Absender -
    deshalb werden dort INBOX, Unbekannt und Spam durchsucht."""
    _, zeilen = imap.list()
    alle, weitere = None, []
    for zeile in zeilen or []:
        text = zeile.decode("utf-8", errors="replace") if isinstance(zeile, bytes) else str(zeile)
        name = text.rsplit(' "/" ', 1)[-1].strip() if ' "/" ' in text else text.rsplit(" ", 1)[-1]
        name = name if name.startswith('"') else f'"{name}"'
        merkmale = text.split(")", 1)[0]
        if "\\All" in merkmale:
            alle = name
        elif "\\Junk" in merkmale or "unbekannt" in name.lower() or name.strip('"').lower() in ("spam", "junk"):
            weitere.append(name)
    if alle:
        return [alle]
    return ["INBOX"] + weitere


_MONATE_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _imap_datum(iso: str) -> str:
    """IMAP verlangt englische Monatskuerzel - strftime("%b") haengt von der Locale ab."""
    d = datetime.fromisoformat(iso)
    return f"{d.day:02d}-{_MONATE_IMAP[d.month - 1]}-{d.year}"


def _hole(imap: imaplib.IMAP4_SSL, nummer: bytes) -> Message | None:
    _, daten = imap.fetch(nummer, "(BODY.PEEK[])")
    for teil in daten or []:
        if isinstance(teil, tuple):
            return email.message_from_bytes(teil[1])
    return None


def _empfangen(nachricht: Message) -> str:
    """Immer in UTC - emailed_at steht in UTC in der Datenbank, und verglichen wird beides."""
    try:
        return parsedate_to_datetime(nachricht.get("Date")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def pruefe_antworten() -> int:
    """Ein Durchlauf. Gibt die Zahl neu erkannter Antworten und Ruecklaeufer zurueck."""
    if not settings.imap_configured:
        return 0
    leads = db.get_angeschriebene_leads()
    if not leads:
        return 0
    frueheste = min(l["emailed_at"] for l in leads)
    neu = 0

    with imaplib.IMAP4_SSL(settings.imap_host) as imap:
        imap.login(settings.imap_user, settings.imap_password)
        for ordner in _ordner_zum_durchsuchen(imap):
            if imap.select(ordner, readonly=True)[0] != "OK":
                continue

            for lead in leads:
                adresse = lead["contact_email"]
                kriterien = [adresse]
                domain = _domain(adresse)
                if domain and domain not in FREEMAILER:
                    kriterien.append("@" + domain)
                else:
                    # Freemailer: Der Betrieb antwortet oft von derselben Adresse bei einem
                    # Schwester-Anbieter (googlemail.com -> gmail.com). Deshalb nach dem
                    # Postfachnamen suchen - aber nur, wenn der eigen genug ist.
                    ortsteil = _ortsteil(adresse)
                    if len(ortsteil) >= 6 and ortsteil not in _ALLERWELTS_POSTFACH:
                        kriterien.append(ortsteil)
                gesehen: set[bytes] = set()
                for kriterium in kriterien:
                    _, daten = imap.search(None, "SINCE", _imap_datum(lead["emailed_at"]),
                                           "FROM", f'"{kriterium}"')
                    for nummer in (daten[0] or b"").split():
                        if nummer in gesehen:
                            continue
                        gesehen.add(nummer)
                        nachricht = _hole(imap, nummer)
                        if nachricht is None:
                            continue
                        if not ist_derselbe_absender(adresse, nachricht.get("From")):
                            continue
                        empfangen = _empfangen(nachricht)
                        if datetime.fromisoformat(empfangen) < datetime.fromisoformat(lead["emailed_at"]):
                            continue
                        if db.add_antwort(
                            lead_id=lead["id"],
                            nachricht_id=nachricht.get("Message-ID") or f"{adresse}:{empfangen}",
                            art="antwort",
                            absender=_dekodiere(nachricht.get("From")),
                            betreff=_dekodiere(nachricht.get("Subject")),
                            auszug=auszug(textkoerper(nachricht)),
                            empfangen_am=empfangen,
                        ):
                            neu += 1
                            logger.info("Antwort erkannt von Lead %s (%s)", lead["id"], adresse)

            # Rueckläufer: Die Meldung kommt vom Mailserver, nicht vom Betrieb - erkennbar
            # nur daran, dass unsere Empfaengeradresse im Text steht.
            adressen = [l["contact_email"] for l in leads]
            nach_adresse = {l["contact_email"].lower(): l for l in leads}
            for absender in ("mailer-daemon", "postmaster"):
                _, daten = imap.search(None, "SINCE", _imap_datum(frueheste), "FROM", absender)
                for nummer in (daten[0] or b"").split():
                    nachricht = _hole(imap, nummer)
                    if nachricht is None:
                        continue
                    volltext = "\n".join(_teiltext(t) for t in nachricht.walk()
                                         if t.get_content_maintype() != "multipart")
                    getroffen = adresse_in_meldung(volltext, adressen)
                    if not getroffen:
                        continue
                    lead = nach_adresse[getroffen.lower()]
                    if db.add_antwort(
                        lead_id=lead["id"],
                        nachricht_id=nachricht.get("Message-ID") or f"bounce:{getroffen}",
                        art="unzustellbar",
                        absender=_dekodiere(nachricht.get("From")),
                        betreff=_dekodiere(nachricht.get("Subject")),
                        auszug=auszug(textkoerper(nachricht)),
                        empfangen_am=_empfangen(nachricht),
                    ):
                        neu += 1
                        logger.info("Unzustellbar: Lead %s (%s)", lead["id"], getroffen)
    return neu
