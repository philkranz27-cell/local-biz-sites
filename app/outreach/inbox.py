"""Liest die letzten Mails aus dem Geschaefts-Postfach per IMAP, damit Antworten im
Dashboard sichtbar sind, ohne Gmail extra zu oeffnen. Bewusst IMAP + App-Passwort statt
Gmail-API/OAuth - kein Google-Cloud-Projekt noetig, nur ein App-Passwort auf dem Konto."""

import email
import imaplib
import logging
from email.header import decode_header

from app.config import settings

logger = logging.getLogger(__name__)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p for p, enc in parts)


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
                }
            )
        return messages
