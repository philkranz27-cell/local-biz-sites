"""Oeffnungszeiten aus OpenStreetMap lesbar machen.

OSM speichert Zeiten in einer eigenen Syntax mit englischen Tageskuerzeln, z.B.
"Su-Th 17:00-23:30; Fr-Sa 17:00-03:00". Ungefiltert stand das auf 56 von 57
Demo-Seiten - auf einer Verkaufsseite fuer einen deutschen Betrieb wirkt das
schlampig und verraet sofort, dass die Daten maschinell uebernommen wurden.

Die Syntax kann mehr als Tage und Uhrzeiten, und genau daran ist die erste Fassung
gescheitert (18 von 139 Seiten zeigten weiter Rohtext):

    Mo 13:00-16:00; PH closed || "Verkaufsautomaten sind auch ausserhalb erreichbar"
    Th-Su 18:00-23:00 "bei schoenem Wetter"
    Jun-Sep: Tu-Th 16:00-22:30; Oct-May: Tu-Th 17:00-22:00
    We,Th 19:00-01:00; PH -1 day 19:00-01:00
    Tu-Sa "nach Vereinbarung"

Deshalb hier: Kommentare in Anfuehrungszeichen werden als Hinweiszeile ausgegeben
statt den ganzen Eintrag unlesbar zu machen, "||" trennt die Regel von ihrer
Ausweichangabe, Monatsbereiche und "PH -1 day" werden uebersetzt.

Bewusst konservativ bleibt: Was nicht sicher erkannt wird, bleibt unveraendert stehen.
Lieber die Rohform als eine falsche Uhrzeit auf der Seite eines Kunden.
"""

from __future__ import annotations

import re

DAY_NAMES = {
    "mo": "Mo", "tu": "Di", "we": "Mi", "th": "Do",
    "fr": "Fr", "sa": "Sa", "su": "So", "ph": "Feiertage",
}

MONTH_NAMES = {
    "jan": "Januar", "feb": "Februar", "mar": "März", "apr": "April",
    "may": "Mai", "jun": "Juni", "jul": "Juli", "aug": "August",
    "sep": "September", "oct": "Oktober", "nov": "November", "dec": "Dezember",
}

# "Mo-Fr", "We,Th", "Su", "PH" - eine Gruppe von Tagen vor den Uhrzeiten
_DAYS = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH)"
_DAY_GROUP = rf"{_DAYS}(?:\s*-\s*{_DAYS})?(?:\s*,\s*{_DAYS}(?:\s*-\s*{_DAYS})?)*"
# "PH -1 day" ist der Tag vor einem Feiertag - kommt bei Bars und Kneipen vor.
_DAY_GROUP_FULL = rf"(?:PH\s*-1\s*day|{_DAY_GROUP})"
# "18:00+" heisst in OSM: ab 18:00, ohne festes Ende.
_TIME_RANGE = r"\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2}\+?|\+)"
_TIME_GROUP = rf"{_TIME_RANGE}(?:\s*,\s*{_TIME_RANGE})*"
_TIMES = re.compile(rf"^(?:{_TIME_GROUP})$")

# Eine vollstaendige Regel: Tage gefolgt von Uhrzeiten (oder "off"/"open").
# Absichtlich als Suchmuster ueber den ganzen String statt als Trennung an ";" -
# OSM benutzt das Komma sowohl innerhalb einer Tagesliste ("We,Th 19:00-01:00") als
# auch zwischen zwei Regeln ("Mo-Sa 11:00-24:00, Su 11:00-23:00"). Ueber die Suche
# loest sich das von selbst auf, weil nach einem Trenn-Komma wieder ein Tag steht.
_RULE = re.compile(rf"({_DAY_GROUP_FULL})\s+({_TIME_GROUP}|off|closed|open)", re.I)

# Monatsbereich als Vorsatz: "Jun-Sep: ..." oder "Oct-May: ..."
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
# Der Doppelpunkt hinter dem Monatsbereich ist in OSM ueblich, aber nicht Pflicht.
_SEASON = re.compile(rf"^({_MONTHS})\s*-\s*({_MONTHS})\s*:?\s+(.+)$", re.I)
# Kommt der Monatsvorsatz mehr als einmal vor, stehen mehrere Saisons im selben
# Eintrag ("Jun-Sep: ...; Oct-May: ..."). Die muessen einzeln uebersetzt werden.
_SEASON_ANY = re.compile(rf"{_MONTHS}\s*-\s*{_MONTHS}\s*:?\s+(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|\d)", re.I)
# Nur Tage, keine Uhrzeit - kommt zusammen mit einem Kommentar vor:
# 'Tu-Sa "nach Vereinbarung"'.
_ONLY_DAYS = re.compile(rf"^{_DAY_GROUP}$", re.I)

# Kommentar in Anfuehrungszeichen, irgendwo im String.
_COMMENT = re.compile(r'"([^"]*)"?')


def _render_days(spec: str) -> str | None:
    """'Mo-Fr' -> 'Mo–Fr', 'We,Th' -> 'Mi, Do'. None, wenn etwas nicht passt."""
    spec = spec.strip()
    if re.fullmatch(r"PH\s*-1\s*day", spec, re.I):
        return "Tag vor Feiertagen"
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
    if spec.lower() == "open":
        return "geöffnet"
    if not _TIMES.match(spec):
        return None
    # Bindestrich zu Halbgeviertstrich, Aufzaehlung als "und" - so schreibt man
    # Oeffnungszeiten im Deutschen.
    ranges = []
    offenes_ende = False
    for part in spec.split(","):
        part = part.strip()
        if part.endswith("+") and "-" in part:
            # "08:00-19:00+": bis 19:00 sicher, danach oft laenger.
            offenes_ende = True
            ranges.append(re.sub(r"\s*-\s*", "–", part[:-1].strip()))
        elif part.endswith("+"):
            ranges.append(f"ab {part[:-1].strip()}")
        else:
            ranges.append(re.sub(r"\s*-\s*", "–", part))
    return " und ".join(ranges) + " Uhr" + (" (oder später)" if offenes_ende else "")


def _split_comment(raw: str) -> tuple[str, str | None]:
    """Trennt einen Kommentar in Anfuehrungszeichen ab.

    OSM haengt Erlaeuterungen als "..." an die Regel ("bei schoenem Wetter",
    "nach Vereinbarung"). Frueher machte ein solcher Zusatz die ganze Angabe
    unuebersetzbar - dabei ist er fuer den Besucher die nuetzlichste Zeile.
    """
    treffer = _COMMENT.search(raw)
    if not treffer:
        return raw, None
    kommentar = treffer.group(1).strip()
    rest = (raw[: treffer.start()] + " " + raw[treffer.end():]).strip(" ;,")
    return rest, kommentar or None


def _regeln_uebersetzen(raw: str) -> list[str] | None:
    """Alle Regeln eines Ausdrucks, oder None wenn er nicht vollstaendig aufgeht."""
    if _TIMES.match(raw):
        # Nur Uhrzeiten ohne Tagesangabe - in OSM heisst das: an allen Tagen.
        zeiten = _render_times(raw)
        return [f"Täglich: {zeiten}"] if zeiten else None

    treffer = list(_RULE.finditer(raw))
    # Nur uebersetzen, wenn die Regeln den String vollstaendig abdecken. Bleibt etwas
    # anderes als Trennzeichen uebrig, ist die Angabe komplexer als das hier - dann
    # lieber unveraendert stehen lassen als eine falsche Uhrzeit auf eine Kundenseite
    # zu schreiben.
    rest = _RULE.sub(" ", raw)
    if not treffer or re.search(r"[^\s;,]", rest):
        return None

    zeilen = []
    for match in treffer:
        tage, zeiten = _render_days(match.group(1)), _render_times(match.group(2))
        if tage is None or zeiten is None:
            return None
        zeilen.append(f"{tage}: {zeiten}")
    return zeilen


def _eintrag_uebersetzen(raw: str, _abschnittsweise: bool = True) -> list[str]:
    """Eine komplette Angabe in lesbare Zeilen. Faellt auf die Rohform zurueck.

    `_abschnittsweise=False` schaltet die Aufteilung nach Jahreszeiten ab - sonst
    ruft sich ein Abschnitt ohne ";" endlos selbst auf.
    """
    if raw == "24/7":
        return ["Täglich durchgehend geöffnet"]
    if raw.lower() in ("off", "closed"):
        return ["Geschlossen"]

    # "||" trennt die Regel von einer Ausweichangabe. Die zweite Haelfte ist fast immer
    # ein Kommentar ("Verkaufsautomaten auch ausserhalb erreichbar") und selten ein
    # zweiter Zeitplan; in beiden Faellen zaehlt fuer die Seite die erste Haelfte.
    haupt, _, ausweich = raw.partition("||")
    haupt, kommentar = _split_comment(haupt.strip())
    if ausweich:
        _, zweiter_kommentar = _split_comment(ausweich.strip())
        kommentar = kommentar or zweiter_kommentar

    # Mehrere Saisons: jeden Abschnitt fuer sich uebersetzen, sonst scheitert der
    # ganze Eintrag an der zweiten Jahreszeit.
    if _abschnittsweise and len(_SEASON_ANY.findall(haupt)) > 1:
        zeilen: list[str] = []
        for abschnitt in haupt.split(";"):
            abschnitt = abschnitt.strip()
            if not abschnitt:
                continue
            teil = _eintrag_uebersetzen(abschnitt, _abschnittsweise=False)
            if teil == [abschnitt]:
                return [raw]  # ein Abschnitt geht nicht auf -> lieber alles roh
            zeilen.extend(teil)
        if kommentar:
            zeilen.append(f"Hinweis: {kommentar}")
        return zeilen

    vorsatz = None
    saison = _SEASON.match(haupt)
    if saison:
        von = MONTH_NAMES.get(saison.group(1).lower())
        bis = MONTH_NAMES.get(saison.group(2).lower())
        if von and bis:
            vorsatz, haupt = f"{von}–{bis}", saison.group(3).strip()

    kern = haupt.strip(" ;,")
    # 'Tu-Sa "nach Vereinbarung"': Tage ohne Uhrzeit, dafuer mit Kommentar. Der
    # Kommentar IST hier die Oeffnungszeit.
    if kern and kommentar and _ONLY_DAYS.match(kern):
        tage = _render_days(kern)
        if tage:
            return [f"{tage}: {kommentar}"]

    zeilen = _regeln_uebersetzen(kern) if kern else []
    if zeilen is None:
        return [raw]  # unveraendert - lieber roh als falsch
    if vorsatz:
        zeilen = [f"{vorsatz} — {z}" for z in zeilen]
    if kommentar:
        zeilen.append(f"Hinweis: {kommentar}")
    return zeilen or [raw]


def format_opening_hours(values: list[str] | None) -> list[str] | None:
    """Gibt Zeilen wie 'Mo–Fr: 09:00–13:00 und 15:00–18:00 Uhr' zurueck."""
    if not values:
        return None

    lines: list[str] = []
    for value in values:
        raw = (value or "").strip()
        # Nur abstreifen, wenn der ganze Wert in Anfuehrungszeichen steht - sonst
        # verliert 'Th-Su 18:00-23:00 "bei schoenem Wetter"' sein schliessendes
        # Zeichen und sieht auf der Seite aus wie ein Tippfehler.
        if len(raw) > 1 and raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1].strip()
        if not raw:
            continue
        lines.extend(_eintrag_uebersetzen(raw))

    return lines or None
