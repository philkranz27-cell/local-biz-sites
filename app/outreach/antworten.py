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
from email.utils import parsedate_to_datetime

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


def _domain(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].lower() if "@" in adresse else ""


def _alle_nachrichten_ordner(imap: imaplib.IMAP4_SSL) -> str:
    """Gmail legt archivierte Mails nicht im INBOX ab. Der Ordner mit dem Merkmal \\All
    enthaelt alles - sein Name haengt aber von der Sprache ab ("Alle Nachrichten")."""
    _, zeilen = imap.list()
    for zeile in zeilen or []:
        text = zeile.decode("utf-8", errors="replace") if isinstance(zeile, bytes) else str(zeile)
        if "\\All" in text:
            name = text.rsplit(' "/" ', 1)[-1].strip()
            return name if name.startswith('"') else f'"{name}"'
    return "INBOX"


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
        imap.select(_alle_nachrichten_ordner(imap), readonly=True)

        for lead in leads:
            adresse = lead["contact_email"]
            kriterien = [adresse]
            domain = _domain(adresse)
            if domain and domain not in FREEMAILER:
                kriterien.append("@" + domain)
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
