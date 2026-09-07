"""Live-Verlauf der Pipeline fuer das Dashboard.

Bisher konnte man "Pipeline jetzt starten" druecken und sah nichts - der Fortschritt
stand nur im Log auf der Festplatte. Hier sammeln die Phasen kurze Meldungen ein, die
das Dashboard abholt und anzeigt.

Bewusst nur im Arbeitsspeicher: Der Verlauf ist eine Momentaufnahme fuers Zuschauen,
kein Protokoll. Wer die Historie braucht, liest data/server.log.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# Ein Durchlauf erzeugt je nach Phase einige Dutzend Meldungen. 200 reichen, um den
# aktuellen Durchlauf komplett zu sehen, ohne unbegrenzt Speicher zu belegen.
MAX_EVENTS = 200

_lock = threading.Lock()
_events: deque[dict] = deque(maxlen=MAX_EVENTS)
_state = {"phase": None, "started_at": None, "running": False}
_counter = 0


def start_run() -> None:
    global _counter
    with _lock:
        _state["running"] = True
        _state["started_at"] = time.time()
        _state["phase"] = None
        _events.clear()
        _counter = 0
    log("start", "Durchlauf gestartet")


def end_run() -> None:
    with _lock:
        _state["running"] = False
        _state["phase"] = None
    log("ende", "Durchlauf beendet")


def set_phase(phase: str, text: str) -> None:
    with _lock:
        _state["phase"] = phase
    log(phase, text)


def log(phase: str, text: str) -> None:
    """Eine Meldung anhaengen. Wird aus dem Scheduler-Thread aufgerufen, deshalb gesperrt."""
    global _counter
    with _lock:
        _counter += 1
        _events.append({"id": _counter, "zeit": time.time(), "phase": phase, "text": text})


def snapshot(seit_id: int = 0) -> dict:
    """Zustand plus alle Meldungen neuer als seit_id - so holt das Dashboard beim
    Nachfragen nur das Neue statt jedes Mal die ganze Liste."""
    with _lock:
        events = [e for e in _events if e["id"] > seit_id]
        laeuft_seit = int(time.time() - _state["started_at"]) if _state["started_at"] else None
        return {
            "running": _state["running"],
            "phase": _state["phase"],
            "laeuft_seit_sek": laeuft_seit,
            "letzte_id": _counter,
            "events": events,
        }
