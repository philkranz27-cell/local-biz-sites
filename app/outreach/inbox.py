"""Liest die letzten Mails aus dem Geschaefts-Postfach per IMAP, damit Antworten im
Dashboard sichtbar sind, ohne Gmail extra zu oeffnen. Bewusst IMAP + App-Passwort statt
Gmail-API/OAuth - kein Google-Cloud-Projekt noetig, nur ein App-Passwort auf dem Konto."""

import email
import imaplib
import logging
import re
from email.header import decode_header
from email.message import Message

from app.config import settings

logger = logging.getLogger(__name__)

# Lange Mails (Newsletter, Signaturen, zitierte Verlaeufe) wuerden das Dashboard
# aufblaehen. Fuer "hat jemand geantwortet und was steht drin" reicht das hier.
MAX_BODY_CHARS = 4000


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p for p, enc in parts)


def _part_text(part: Message) -> str:
    """Text einer einzelnen MIME-Teilnachricht, mit der im Header angegebenen Kodierung."""
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:  # unbekannte Kodierung im Header
        return payload.decode("utf-8", errors="replace")


def _body_text(msg: Message) -> str:
    """Lesbaren Text der Mail holen: bevorzugt text/plain, sonst HTML entschaerft.

    Anhaenge werden uebersprungen - im Dashboard soll der Text stehen, nicht der
    Inhalt einer angehaengten PDF."""
    plain, html_fallback = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and not plain:
            plain = _part_text(part)
        elif ctype == "text/html" and not html_fallback:
            html_fallback = _part_text(part)

    text = plain
    if not text and html_fallback:
        # Kein Rendering, nur lesbar machen: Skripte/Styles raus, Tags entfernen.
        text = re.sub(r"<(script|style)\b.*?</\1>", " ", html_fallback, flags=re.S | re.I)
        text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;?", " ", text)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_BODY_CHARS:
        text = text[:MAX_BODY_CHARS].rstrip() + "\n\n[…gekürzt]"
    return text


def fetch_recent_messages(limit: int = 15) -> list[dict]:
    if not settings.imap_configured:
        return []
    with imaplib.IMAP4_SSL(settings.imap_host) as imap:
        imap.login(settings.imap_user, settings.imap_password)
        imap.select("INBOX")
        _, data = imap.search(None, "ALL")
        ids = data[0].split()[-limit:]
        messages = []
        for msg_id in reversed(ids):
            _, msg_data = imap.fetch(msg_id, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            messages.append(
                {
                    "from": _decode(msg.get("From")),
                    "subject": _decode(msg.get("Subject")),
                    "date": msg.get("Date", ""),
                    "body": _body_text(msg),
                }
            )
        return messages
