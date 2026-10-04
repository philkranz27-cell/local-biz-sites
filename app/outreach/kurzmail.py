"""Die kurze Akquise-Mail und die eine Nachfass-Mail.

Warum neu (04.10.2026): 101 Mails, 4 Antworten (alle Absagen), und von 42 Betrieben seit
dem Besuchszaehler hat einer seine Demo-Seite geoeffnet. Die alte Mail sah nach Werbung
aus: Betreff "Unverbindliche Demo-Website fuer ...", ein langer Vorteile-Block, kein
Preis. Wer nicht weiss, was es kostet, klickt nicht.

Die neue Mail ist kurz, persoenlich, nennt einen Preis und kommt ohne Sprachmodell aus -
jede Mail sagt dasselbe, nur mit Namen, Ort und Link des Betriebs.

Der Preis steht in ANGEBOT_PREIS in der .env. Ohne ihn geht keine Mail raus: Eine Mail
ohne Preis ist genau die, die nicht funktioniert hat.
"""

from __future__ import annotations

import json

from app.config import settings
from app.outreach.mailer import OPT_OUT_NOTE
from app.outreach.vorteile import KATEGORIEN, _STANDARD

NACHFASS_NACH_TAGEN = 7


class PreisFehlt(RuntimeError):
    """ANGEBOT_PREIS ist leer - dann wird nichts verschickt."""


def _preis() -> str:
    preis = (settings.angebot_preis or "").strip()
    if not preis:
        raise PreisFehlt("ANGEBOT_PREIS ist in der .env nicht gesetzt")
    return preis


def _absender() -> str:
    return (settings.sender_impressum or "").split(",")[0].strip() or "Philipp Kranz"


def _anrede(lead) -> str:
    extras = json.loads(lead["osm_extras_json"]) if lead["osm_extras_json"] else {}
    inhaber = extras.get("inhaber")
    return f"Guten Tag {inhaber}," if inhaber else "Guten Tag,"


def demo_link(lead) -> str:
    return f"{settings.base_url}/sites/{lead['site_slug']}/?q=mail"


def betreff(lead) -> str:
    return f"Kurze Frage zu {lead['name']}"


def erstmail(lead) -> str:
    _, vorteil = KATEGORIEN.get(lead["category"] or "", _STANDARD)
    ort = f" in {lead['city']}" if lead["city"] else ""
    return (
        f"{_anrede(lead)}\n\n"
        f"ich bin {_absender()} und baue Websites für kleine Betriebe. Für {lead['name']}{ort} "
        f"habe ich keine eigene Website gefunden – deshalb habe ich einfach mal einen Entwurf "
        f"gemacht:\n\n"
        f"{demo_link(lead)}\n\n"
        f"Die Fotos sind Platzhalter, Ihre eigenen setze ich ein. {vorteil}\n\n"
        f"Wenn er Ihnen gefällt, übernehme ich ihn mit Ihren Fotos und Texten – {_preis()}. "
        f"Wenn nicht, ignorieren Sie die Mail einfach.\n\n"
        f"Viele Grüße\n{_absender()}"
        f"{OPT_OUT_NOTE}"
    )


def nachfass_betreff(lead) -> str:
    return f"Nochmal kurz zu {lead['name']}"


def nachfassmail(lead) -> str:
    return (
        f"{_anrede(lead)}\n\n"
        f"letzte Woche hatte ich Ihnen einen Website-Entwurf für {lead['name']} geschickt. "
        f"Falls die Mail untergegangen ist, hier noch einmal der Link:\n\n"
        f"{demo_link(lead)}\n\n"
        f"Mit Ihren eigenen Fotos und Texten: {_preis()}.\n\n"
        f"Wenn kein Interesse besteht, genügt eine kurze Antwort – dann melde ich mich nicht "
        f"mehr.\n\n"
        f"Viele Grüße\n{_absender()}"
        f"{OPT_OUT_NOTE}"
    )
