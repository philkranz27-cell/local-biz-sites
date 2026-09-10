"""Harte Regeln fuer Seitentexte - im Code statt im Prompt.

Zwei Runden Arbeit am Prompt (10.09.2026) haben gezeigt, dass das Modell die Regeln
nicht zuverlaessig befolgt, und jede Runde bricht es andere:
- Runde 1: keine Erfindungen mehr, dafuer Amtston ("Kartenzahlung ist moeglich",
  "Sie erhalten ein Dessert") und Barrierefreiheit als Leistung im Angebot.
- Runde 2: waermer, aber "ruhiges Ambiente" und "Unser Team" wieder drin; bei einem
  anderen Betrieb vier statt drei Highlights, drei davon wortgleich mit dem Faktenband.

Was im Code steht, gilt dagegen immer - die Absicherung der Schlagzeile hat es
vorgemacht, drei von drei. Deshalb prueft dieses Modul jeden erzeugten Text, bevor er
auf eine Seite kommt.

Zwei Arten von Eingriffen:
- reparieren, kostet nichts: Saetze mit Ausstattungs- oder Stimmungsbehauptungen
  streichen, Highlights auf drei kuerzen, Doppelungen mit dem Faktenband entfernen
- melden, wenn nach der Reparatur zu wenig uebrig ist - dann entscheidet der Aufrufer,
  ob er einen neuen Versuch startet
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Behauptungen, die niemand belegt hat: Raeume, Stimmung, Personal, Herkunft, Verfahren,
# Zusatzleistungen. Wortstaemme, damit "gemuetliche" und "Gemuetlichkeit" mitfallen.
ERFUNDEN = re.compile(
    r"ambiente|atmosph|gemütlich|ruhig|modern|stilvoll|lichtdurchflutet|elegant|\burig|"
    r"einladende[nrs]? (?:raum|räum|einrichtung)|terrasse|biergarten|innenhof|garten|"
    r"lounge|kamin|unser team|team aus|meister|familienbetrieb|generation|seit \d{4}|"
    r"hausgemacht|hauseigen|selbstgemacht|regional|saisonal|nachhaltig|bio-|frisch gemahlen|"
    # "vegetarische Gerichte" ist belegt, "rein vegetarisch" macht daraus eine andere Art
    # Betrieb - so geschehen beim Gutshof Menterschwaige am 10.09.
    r"rein vegetarisch|rein vegan|ausschließlich vegetarisch|ausschließlich vegan|"
    r"nur vegetarisch|nur vegan|100 ?% vegetarisch|100 ?% vegan|"
    r"handgemacht|handgeschöpft|catering|lieferdienst|lieferservice|take-?away|"
    r"prämiert|ausgezeichnet|zertifiziert",
    re.IGNORECASE,
)

# Behoerdenton: haelt keine Regel des Rechts, aber jede Regel guter Werbung.
AMTSTON = re.compile(
    # "erhalten sie" in umgedrehter Wortstellung: "Im Troy Salon erhalten Sie eine Beratung"
    # rutschte beim ersten Test an "sie erhalten" vorbei.
    r"sie erhalten|erhalten sie|ist möglich|sind möglich|steht ihnen zur verfügung|stehen ihnen zur "
    r"verfügung|stehen zur verfügung|steht zur verfügung|werden angeboten|wird angeboten|"
    r"aus unserem angebot",
    re.IGNORECASE,
)


class TextAbgelehnt(Exception):
    """Der Text hat die Pruefung auch nach dem gezielten Reparaturversuch nicht bestanden.

    Die Seite behaelt dann ihren bisherigen Text. Die Pipeline zaehlt das als Fehlversuch;
    nach drei Fehlversuchen bleibt der Betrieb aussen vor, damit er nicht jeden Durchlauf
    Kontingent verbrennt."""

# Ausstattung ist keine Leistung und kein Highlight - sie steht im eigenen Faktenband.
AUSSTATTUNG = re.compile(
    r"barrierefrei|wlan|w-lan|internet|kartenzahlung|zahlungsart|ec-karte|kreditkarte|"
    r"sitzpl|außenpl|aussenpl|plätze im freien|im freien|klimatisiert|klimaanlage|parkpl",
    re.IGNORECASE,
)

_SATZENDE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Pruefergebnis:
    reparaturen: list[str] = field(default_factory=list)
    probleme: list[str] = field(default_factory=list)

    @property
    def in_ordnung(self) -> bool:
        return not self.probleme


def _saetze_filtern(text: str, ergebnis: Pruefergebnis, feld: str) -> str:
    behalten = []
    for satz in _SATZENDE.split((text or "").strip()):
        if not satz:
            continue
        grund = ("Behauptung" if ERFUNDEN.search(satz)
                 else "Amtston" if AMTSTON.search(satz)
                 else "Ausstattung" if AUSSTATTUNG.search(satz) else None)
        if grund:
            ergebnis.reparaturen.append(f"{feld}: Satz gestrichen ({grund}): {satz[:60]}")
        else:
            behalten.append(satz)
    return " ".join(behalten)


def pruefe(copy, fakten: list[str] | None = None, *, stadt: str = "", name: str = "") -> Pruefergebnis:
    """Prueft und repariert `copy` (GeneratedSiteCopy) an Ort und Stelle."""
    ergebnis = Pruefergebnis()
    fakten_klein = {f.strip().lower() for f in (fakten or [])}

    # Kopfzeilen lassen sich nicht sinnvoll satzweise kuerzen - dort nur melden.
    for feld in ("tagline", "headline", "subheadline"):
        wert = getattr(copy, feld, "") or ""
        if ERFUNDEN.search(wert):
            ergebnis.probleme.append(f"{feld} enthaelt eine Behauptung: {wert}")

    if name and (len(copy.headline) > 45 or (stadt and stadt.lower() in copy.headline.lower())):
        ergebnis.reparaturen.append(f"headline ersetzt: {copy.headline}")
        copy.headline = name

    copy.about = _saetze_filtern(copy.about, ergebnis, "about")
    if len(_SATZENDE.split(copy.about.strip())) < 2 or len(copy.about) < 80:
        ergebnis.probleme.append("about: nach dem Aussortieren zu duenn")

    # Leistungen: Ausstattung raus, Behauptungen raus, Amtston-Beschreibungen leeren.
    leistungen = []
    for s in copy.services:
        if AUSSTATTUNG.search(s.name) or ERFUNDEN.search(s.name):
            ergebnis.reparaturen.append(f"services: Eintrag entfernt: {s.name}")
            continue
        beschreibung = _saetze_filtern(s.description, ergebnis, f"services/{s.name}")
        if not beschreibung:
            ergebnis.probleme.append(f"services/{s.name}: keine brauchbare Beschreibung")
        s.description = beschreibung
        leistungen.append(s)
    copy.services = leistungen
    if len(leistungen) < 4:
        ergebnis.probleme.append(f"services: nur {len(leistungen)} brauchbare Eintraege")

    # Highlights: keine Ausstattung, keine Behauptung, nicht wortgleich mit dem Faktenband,
    # keine Doppelungen, genau drei.
    highlights, gesehen = [], set()
    for h in copy.highlights:
        schluessel = h.strip().lower()
        if (AUSSTATTUNG.search(h) or ERFUNDEN.search(h) or schluessel in fakten_klein
                or schluessel in gesehen or (stadt and stadt.lower() in schluessel)):
            ergebnis.reparaturen.append(f"highlights: entfernt: {h}")
            continue
        gesehen.add(schluessel)
        highlights.append(h.strip())
    for s in leistungen:  # auffuellen aus dem Angebot, das bereits geprueft ist
        if len(highlights) >= 3:
            break
        # Auch hier gegen das Faktenband abgleichen: Sonst kommt ein gerade entferntes
        # "Frühstück" als Leistungsname durch die Hintertür zurück (Testfall Sorry Johnny).
        if s.name.strip().lower() not in gesehen and s.name.strip().lower() not in fakten_klein:
            highlights.append(s.name.strip())
            gesehen.add(s.name.strip().lower())
            ergebnis.reparaturen.append(f"highlights: aufgefuellt mit {s.name}")
    copy.highlights = highlights[:3]
    if len(copy.highlights) < 3:
        ergebnis.probleme.append(f"highlights: nur {len(copy.highlights)} brauchbar")

    return ergebnis
