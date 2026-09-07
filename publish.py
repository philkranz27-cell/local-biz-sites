"""Spiegelt die erzeugten Demo-Seiten nach docs/, wo GitHub Pages sie ausliefert.

Von Hand aufrufen, wenn kein GITHUB_TOKEN hinterlegt ist. Ist einer hinterlegt,
erledigt die Pipeline das von selbst (siehe app/publisher.py).

Warum ueberhaupt: Die Seiten lagen bisher nur auf dem Laptop und waren ueber den
Tailscale-Funnel erreichbar. Der Laptop schlaeft aber die meiste Zeit - ein Betrieb,
der die Mail abends oeffnet, waere auf einen toten Link geklickt.

Aufruf:  .venv/Scripts/python.exe publish.py
"""

from __future__ import annotations

import sys

from app.config import settings
from app.publisher import spiegeln, veroeffentlichen


def main() -> int:
    if settings.publish_configured:
        # Mit Token gleich den ganzen Weg gehen, sonst nur spiegeln.
        if veroeffentlichen():
            print("Demo-Seiten gespiegelt und hochgeladen.")
            return 0
        print("Nichts zu veroeffentlichen (keine Aenderung) oder Upload fehlgeschlagen -")
        print("Einzelheiten stehen im Log.")
        return 0

    anzahl = spiegeln()
    if not anzahl:
        print("Keine Demo-Seiten gefunden unter data/sites.")
        return 1

    print(f"{anzahl} Demo-Seiten nach docs/sites/ gespiegelt.")
    print("\nKein GITHUB_TOKEN hinterlegt - bitte selbst hochladen:")
    print('  git add docs && git commit -m "Demo-Seiten aktualisiert" && git push')
    return 0


if __name__ == "__main__":
    sys.exit(main())
