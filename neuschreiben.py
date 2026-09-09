"""Schreibt die Texte bereits erzeugter Demo-Seiten neu.

Warum: Die Seiten wurden mit der alten, zu laschen Ehrlichkeitsregel geschrieben. Dort
stehen Behauptungen, die niemand nachgepruefst hat - "hausgemachte Kuchen aus unserer
hauseigenen Backstube", "Catering fuer Events", "regionale Zutaten". Kann stimmen, ist
aber erfunden. Der neue Prompt verbietet das und bekommt stattdessen die belegten
Angaben aus OpenStreetMap mit.

Warum in Etappen: Das kostenlose Groq-Kontingent liegt bei 200.000 Token pro Tag, ein
Seitentext braucht rund 3.000 (Entwurf plus Lektorat). Es passen also etwa 60 Seiten in
einen Tag. Das Skript hoert von selbst auf, wenn das Kontingent erschoepft ist, und
macht beim naechsten Aufruf dort weiter, wo es aufgehoert hat - der bereits neu
geschriebene Text steht in site_copy_json und wird nicht noch einmal erzeugt.

Reihenfolge: zuerst die Betriebe, die einen Brief bekommen (data/auswahl.json), danach
die uebrigen. Wer angeschrieben wird, soll die bessere Seite sehen.

Aufruf:  .venv/Scripts/python.exe neuschreiben.py [--anzahl=60] [--nur-auswahl]
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

import groq

from app import db
from app.publisher import veroeffentlichen
from app.sitegen.generator import generate_site

AUSWAHL = pathlib.Path("data/auswahl.json")


def _reihenfolge() -> list:
    """Briefempfaenger zuerst, dann der Rest - beide in stabiler Reihenfolge."""
    bevorzugt = set()
    if AUSWAHL.exists():
        bevorzugt = set(json.loads(AUSWAHL.read_text(encoding="utf-8")))

    with db.get_connection() as conn:
        leads = conn.execute(
            "SELECT * FROM leads WHERE site_slug IS NOT NULL AND site_copy_json IS NULL "
            "AND status NOT IN ('excluded_kette') ORDER BY id"
        ).fetchall()
    return sorted(leads, key=lambda l: (l["site_slug"] not in bevorzugt, l["id"]))


def main() -> int:
    grenze = 60
    nur_auswahl = "--nur-auswahl" in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith("--anzahl="):
            grenze = int(arg.split("=", 1)[1])

    offen = _reihenfolge()
    if nur_auswahl and AUSWAHL.exists():
        bevorzugt = set(json.loads(AUSWAHL.read_text(encoding="utf-8")))
        offen = [l for l in offen if l["site_slug"] in bevorzugt]

    if not offen:
        print("Alle Seiten sind bereits neu geschrieben.")
        return 0

    print(f"{len(offen)} Seiten offen, bis zu {grenze} in diesem Lauf.\n")
    fertig = fehler = 0
    for lead in offen[:grenze]:
        try:
            generate_site(lead)
            fertig += 1
            print(f"  {fertig:3}. {lead['name'][:38]}")
        except groq.RateLimitError:
            print(f"\nTageskontingent erschoepft nach {fertig} Seiten. "
                  f"Morgen erneut aufrufen, der Rest steht noch aus.")
            break
        except Exception as exc:  # eine kaputte Seite darf den Lauf nicht beenden
            fehler += 1
            print(f"  FEHLER bei {lead['name'][:34]}: {type(exc).__name__}: {exc}")
        time.sleep(1)  # der Groq-Freitarif begrenzt auch Anfragen pro Minute

    print(f"\nneu geschrieben: {fertig} | Fehler: {fehler}")
    if fertig:
        print("veroeffentlicht:", veroeffentlichen())
    with db.get_connection() as conn:
        rest = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE site_slug IS NOT NULL "
            "AND site_copy_json IS NULL AND status NOT IN ('excluded_kette')"
        ).fetchone()[0]
    print(f"noch offen: {rest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
