"""Veroeffentlicht die erzeugten Demo-Seiten automatisch auf GitHub Pages.

Ohne das muesste nach jeder neuen Seite jemand von Hand publish.py aufrufen und
pushen - bei einer Anlage, die rund um die Uhr neue Betriebe findet, ist das nichts.
Der Link in einer Mail muss ab dem Moment funktionieren, in dem die Mail rausgeht.

Braucht einen GitHub-Token mit Schreibrecht auf das Repository (GITHUB_TOKEN in .env).
Ohne Token passiert hier gar nichts - die Seiten werden dann nur lokal gespiegelt und
jemand veroeffentlicht sie von Hand.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUELLE = PROJECT_ROOT / "data" / "sites"
ZIEL = PROJECT_ROOT / "docs" / "sites"

NOINDEX = '<meta name="robots" content="noindex, nofollow">'
ROBOTS = "User-agent: *\nDisallow: /sites/\n"

_letzte_veroeffentlichung = 0.0


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout
    )


def _push_url() -> str:
    """Token nur fuer diesen einen Aufruf in die Adresse setzen, nicht dauerhaft im
    Remote speichern - sonst steht er im Klartext in .git/config."""
    return f"https://x-access-token:{settings.github_token}@github.com/{settings.github_repo}.git"


def _ohne_token(text: str) -> str:
    """Damit der Token nie im Log landet, egal was git ausgibt."""
    if settings.github_token:
        return text.replace(settings.github_token, "***")
    return text


def spiegeln() -> int:
    """Kopiert die Demo-Seiten nach docs/ und gibt die Anzahl zurueck."""
    if not QUELLE.is_dir():
        return 0
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    shutil.copytree(QUELLE, ZIEL)

    # Sicherheitsnetz fuer Seiten, die vor der Umstellung erzeugt wurden.
    for datei in ZIEL.rglob("index.html"):
        text = datei.read_text(encoding="utf-8")
        if 'name="robots"' not in text and "<head>" in text:
            datei.write_text(text.replace("<head>", "<head>\n" + NOINDEX, 1), encoding="utf-8")

    (PROJECT_ROOT / "docs" / "robots.txt").write_text(ROBOTS, encoding="utf-8")
    return sum(1 for _ in ZIEL.rglob("index.html"))


def veroeffentlichen() -> bool:
    """Spiegelt, committet und pusht - aber nur, wenn sich wirklich etwas geaendert hat.

    Gibt True zurueck, wenn etwas veroeffentlicht wurde. Faellt bei jedem Problem
    leise zurueck: Ein Fehler hier darf die Pipeline nicht anhalten, die Seiten
    liegen ja weiterhin lokal vor."""
    global _letzte_veroeffentlichung

    if not settings.publish_configured:
        return False

    # Nicht bei jedem Durchlauf pushen - sonst entsteht alle paar Minuten ein Commit.
    abstand = settings.publish_min_interval_min * 60
    if _letzte_veroeffentlichung and time.time() - _letzte_veroeffentlichung < abstand:
        return False

    try:
        anzahl = spiegeln()
        if not anzahl:
            return False

        _git("add", "--", "docs")
        # --quiet gibt Rueckgabewert 1, wenn es nichts zu committen gibt.
        if _git("diff", "--cached", "--quiet", "--", "docs").returncode == 0:
            _letzte_veroeffentlichung = time.time()
            return False

        commit = _git("commit", "-m", f"Demo-Seiten aktualisiert ({anzahl} Seiten)", "--", "docs")
        if commit.returncode != 0:
            logger.warning("Commit fehlgeschlagen: %s", _ohne_token(commit.stderr.strip())[:200])
            return False

        push = _git("push", _push_url(), "HEAD:main", timeout=300)
        if push.returncode != 0:
            # Meist: jemand hat in der Zwischenzeit selbst gepusht. Einmal nachziehen.
            logger.info("Push abgelehnt, versuche rebase: %s", _ohne_token(push.stderr.strip())[:150])
            if _git("pull", "--rebase", _push_url(), "main", timeout=300).returncode != 0:
                logger.warning("Rebase fehlgeschlagen - Veroeffentlichung uebersprungen")
                return False
            push = _git("push", _push_url(), "HEAD:main", timeout=300)
            if push.returncode != 0:
                logger.warning("Push endgueltig fehlgeschlagen: %s", _ohne_token(push.stderr.strip())[:200])
                return False

        _letzte_veroeffentlichung = time.time()
        logger.info("Demo-Seiten veroeffentlicht (%d Seiten)", anzahl)
        return True

    except Exception:
        logger.exception("Veroeffentlichung fehlgeschlagen")
        return False
