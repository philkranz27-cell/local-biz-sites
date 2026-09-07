"""Spiegelt die erzeugten Demo-Seiten nach docs/, wo GitHub Pages sie ausliefert.

Warum ueberhaupt: Die Seiten lagen bisher nur auf dem Laptop und waren ueber den
Tailscale-Funnel erreichbar. Der Laptop schlaeft aber die meiste Zeit - ein Betrieb,
der die Mail abends oeffnet, waere auf einen toten Link geklickt. GitHub Pages ist
kostenlos und dauerhaft erreichbar.

Das Reservierungs-Formular ruft weiterhin die laufende Anwendung auf (API_BASE_URL),
denn dafuer braucht es einen Server. Klappt das nicht, sagt das Formular das ehrlich
und nennt die Telefonnummer des Betriebs.

Aufruf:  .venv/Scripts/python.exe publish.py
Danach:  git add docs && git commit && git push
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
QUELLE = PROJECT_ROOT / "data" / "sites"
ZIEL = PROJECT_ROOT / "docs" / "sites"

# Suchmaschinen sollen die Entwuerfe nicht indexieren - es sind unverbindliche Vorschlaege
# fuer Betriebe, die nichts davon wissen, und sie duerfen nicht mit deren echter Seite
# verwechselt werden. Die Absicherung steckt als <meta name="robots"> in jeder Seite;
# diese Datei hilft nur zusaetzlich und nur dann, wenn die Seiten spaeter unter einer
# eigenen Domain im Wurzelverzeichnis liegen (bei einem Projekt-Pfad wie
# /local-biz-sites/ wertet kein Crawler eine robots.txt aus).
ROBOTS = "User-agent: *\nDisallow: /sites/\n"

NOINDEX = '<meta name="robots" content="noindex, nofollow">'


def main() -> int:
    if not QUELLE.is_dir():
        print(f"Keine Demo-Seiten gefunden unter {QUELLE}")
        return 1

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    shutil.copytree(QUELLE, ZIEL)

    # Sicherheitsnetz: aeltere Seiten wurden vor der Umstellung erzeugt und haben den
    # noindex-Hinweis noch nicht. Lieber hier nachtragen als darauf vertrauen.
    nachgetragen = 0
    for datei in ZIEL.rglob("index.html"):
        text = datei.read_text(encoding="utf-8")
        if 'name="robots"' not in text and "<head>" in text:
            datei.write_text(text.replace("<head>", "<head>\n" + NOINDEX, 1), encoding="utf-8")
            nachgetragen += 1

    (PROJECT_ROOT / "docs" / "robots.txt").write_text(ROBOTS, encoding="utf-8")

    seiten = sum(1 for _ in ZIEL.rglob("index.html"))
    print(f"{seiten} Demo-Seiten nach docs/sites/ gespiegelt")
    if nachgetragen:
        print(f"  davon {nachgetragen} nachtraeglich auf noindex gesetzt")
    print("\nNaechster Schritt:")
    print('  git add docs && git commit -m "Demo-Seiten veroeffentlicht" && git push')
    return 0


if __name__ == "__main__":
    sys.exit(main())
