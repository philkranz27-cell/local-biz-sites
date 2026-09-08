"""Taegliche Sicherungskopie der Datenbank.

Die Datenbank ist der einzige Ort, an dem die gefundenen Betriebe, die erzeugten
Seiten und der Kontaktstand stehen. Geht sie verloren, ist die Arbeit von Wochen weg -
die Seiten selbst liegen zwar noch in docs/, aber wer schon angeschrieben wurde,
wer widersprochen hat und welcher Betrieb zu welcher Seite gehoert, steht nur hier.

sqlite3.Connection.backup() kopiert konsistent, auch waehrend die Pipeline schreibt -
ein blosses Kopieren der Datei waere im WAL-Betrieb nicht sicher.
"""

import logging
import sqlite3
from datetime import date
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Zwei Wochen zurueck reicht: ein Fehler faellt spaetestens beim naechsten Blick aufs
# Dashboard auf, und mehr Kopien fuellen nur die Platte.
AUFBEWAHRUNG = 14


def sicherungsordner() -> Path:
    ordner = Path(settings.db_path).parent / "sicherungen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def sichern() -> Path | None:
    quelle = Path(settings.db_path)
    if not quelle.exists():
        logger.warning("Keine Datenbank unter %s - nichts zu sichern", quelle)
        return None

    ziel = sicherungsordner() / f"app-{date.today():%Y-%m-%d}.db"
    with sqlite3.connect(quelle) as auf, sqlite3.connect(ziel) as ab:
        auf.backup(ab)

    _aufraeumen()
    logger.info("Datenbank gesichert nach %s (%.1f MB)", ziel, ziel.stat().st_size / 1e6)
    return ziel


def _aufraeumen() -> None:
    kopien = sorted(sicherungsordner().glob("app-*.db"))
    for alt in kopien[:-AUFBEWAHRUNG]:
        alt.unlink(missing_ok=True)
        logger.info("Alte Sicherung entfernt: %s", alt.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sichern()
