"""Oeffnungszeiten aus OpenStreetMap lesbar machen.

OSM speichert Zeiten in einer eigenen Syntax mit englischen Tageskuerzeln, z.B.
"Su-Th 17:00-23:30; Fr-Sa 17:00-03:00". Ungefiltert stand das auf 56 von 57
Demo-Seiten - auf einer Verkaufsseite fuer einen deutschen Betrieb wirkt das
schlampig und verraet sofort, dass die Daten maschinell uebernommen wurden.

Bewusst konservativ: Was nicht sicher erkannt wird, bleibt unveraendert stehen.
Lieber die Rohform als eine falsche Uhrzeit auf der Seite eines Kunden.
"""

from __future__ import annotations

import re

DAY_NAMES = {
    "mo": "Mo", "tu": "Di", "we": "Mi", "th": "Do",
    "fr": "Fr", "sa": "Sa", "su": "So", "ph": "Feiertage",
}

# "Mo-Fr", "We,Th", "Su", "PH" - eine Gruppe von Tagen vor den Uhrzeiten
_DAYS = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)"
_DAY_GROUP = rf"{_DAYS}(?:\s*-\s*{_DAYS})?(?:\s*,\s*{_DAYS}(?:\s*-\s*{_DAYS})?)*"
# "18:00+" heisst in OSM: ab 18:00, ohne festes Ende.
_TIME_RANGE = r"\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2}|\+)"
_TIME_GROUP = rf"{_TIME_RANGE}(?:\s*,\s*{_TIME_RANGE})*"
_TIMES = re.compile(rf"^(?:{_TIME_GROUP})$")

# Eine vollstaendige Regel: Tage gefolgt von Uhrzeiten (oder "off").
# Absichtlich als Suchmuster ueber den ganzen String statt als Trennung an ";" -
# OSM benutzt das Komma sowohl innerhalb einer Tagesliste ("We,Th 19:00-01:00") als
# auch zwischen zwei Regeln ("Mo-Sa 11:00-24:00, Su 11:00-23:00"). Ueber die Suche
# loest sich das von selbst auf, weil nach einem Trenn-Komma wieder ein Tag steht.
_RULE = re.compile(rf"({_DAY_GROUP})\s+({_TIME_GROUP}|off|closed)", re.I)


def _render_days(spec: str) -> str | None:
    """'Mo-Fr' -> 'Mo–Fr', 'We,Th' -> 'Mi, Do'. None, wenn etwas nicht passt."""
    parts = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            da, db = DAY_NAMES.get(a.strip().lower()), DAY_NAMES.get(b.strip().lower())
            if not da or not db:
                return None
            parts.append(f"{da}–{db}")
        else:
            day = DAY_NAMES.get(chunk.lower())
            if not day:
                return None
            parts.append(day)
    return ", ".join(parts) if parts else None


def _render_times(spec: str) -> str | None:
    spec = spec.strip()
    if spec.lower() in ("off", "closed"):
        return "geschlossen"
    if not _TIMES.match(spec):
        return None
    # Bindestrich zu Halbgeviertstrich, Aufzaehlung als "und" - so schreibt man
    # Oeffnungszeiten im Deutschen.
    ranges = []
    for part in spec.split(","):
        part = part.strip()
        if part.endswith("+"):
            ranges.append(f"ab {part[:-1].strip()}")
        else:
            ranges.append(re.sub(r"\s*-\s*", "–", part))
    return " und ".join(ranges) + " Uhr"


def format_opening_hours(values: list[str] | None) -> list[str] | None:
    """Gibt Zeilen wie 'Mo–Fr: 09:00–13:00 und 15:00–18:00 Uhr' zurueck."""
    if not values:
        return None

    lines: list[str] = []
    for value in values:
        raw = (value or "").strip().strip('"')
        if not raw:
            continue
        if raw == "24/7":
            lines.append("Täglich durchgehend geöffnet")
            continue
        if raw.lower() in ("off", "closed"):
            lines.append("Geschlossen")
            continue
        if _TIMES.match(raw):
            # Nur Uhrzeiten ohne Tagesangabe - in OSM heisst das: an allen Tagen.
            lines.append(f"Täglich: {_render_times(raw)}")
            continue

        matches = list(_RULE.finditer(raw))
        # Nur uebersetzen, wenn die Regeln den String vollstaendig abdecken. Bleibt
        # etwas anderes als Trennzeichen uebrig (z.B. "PH -1 day" oder "12:00-22:00+"),
        # ist die Angabe komplexer als das hier - dann lieber unveraendert stehen lassen
        # als eine falsche Uhrzeit auf die Seite eines Kunden zu schreiben.
        rest = _RULE.sub(" ", raw)
        if not matches or re.search(r"[^\s;,]", rest):
            lines.append(raw)
            continue

        for match in matches:
            days, times = _render_days(match.group(1)), _render_times(match.group(2))
            if days is None or times is None:
                lines.append(raw)
                break
            lines.append(f"{days}: {times}")

    return lines or None
