"""Prueft, ob eine Anschrift fuer einen Brief taugt.

Stand bisher dreimal im Projekt (briefe.py, adressen.py, und implizit in der Pipeline),
jedes Mal leicht anders. Ein Brief an eine unvollstaendige Anschrift kommt nicht an und
kostet trotzdem Porto - die Regel gehoert an genau eine Stelle.

OpenStreetMap liefert Anschriften haeufig bruchstueckhaft: mal nur "50667", mal nur einen
Strassennamen ohne Hausnummer. Beides reicht nicht.
"""

from __future__ import annotations

import re

# Fuenfstellige Postleitzahl, nicht Teil einer laengeren Zahl.
PLZ = re.compile(r"(?<!\d)\d{5}(?!\d)")
# Hausnummer am Ende des Strassenteils, also vor dem Komma: "Hauptstrasse 12a, 86972 ..."
HAUSNUMMER = re.compile(r"\d+\s*[a-zA-Z]?\s*,")


def vollstaendig(adresse: str | None) -> bool:
    """True, wenn Strasse mit Hausnummer UND Postleitzahl vorhanden sind."""
    text = (adresse or "").strip()
    return bool(PLZ.search(text)) and bool(HAUSNUMMER.search(text))
