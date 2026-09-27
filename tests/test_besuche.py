"""Tests fuer den Besuchszaehler der Demo-Seiten.

Laeuft gegen eine Wegwerf-Datenbank, nicht gegen die echte.

Aufruf:  .venv/Scripts/python.exe tests/test_besuche.py
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.api.routes import router  # noqa: E402
from app.outreach.mailer import akquise_mail_text  # noqa: E402

HANDY = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1"
RECHNER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def _mit_testdatenbank(pruefung):
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    alt = db.settings.db_path
    with tempfile.TemporaryDirectory() as ordner:
        db.settings.db_path = str(pathlib.Path(ordner) / "test.db")
        try:
            db.init_db()
            with db.get_connection() as conn:
                conn.execute("INSERT INTO leads (id, place_id, name, category, city, found_at, site_slug) "
                             "VALUES (1, 'p1', 'Kreta', 'restaurant', 'Karlsruhe', '2026-09-01', 'kreta-ka')")
            pruefung(TestClient(app))
        finally:
            db.settings.db_path = alt


def _senden(client, daten, agent=HANDY, slug="kreta-ka"):
    return client.post(f"/api/besuch/{slug}", content=json.dumps(daten),
                       headers={"Content-Type": "text/plain", "User-Agent": agent})


def test_besuch_wird_mit_quelle_und_geraet_gezaehlt():
    def pruefung(client):
        assert _senden(client, {"quelle": "mail"}).json()["status"] == "ok"
        _senden(client, {"quelle": "brief"}, agent=RECHNER)
        zeilen = db.get_letzte_besuche()
        assert {(z["quelle"], z["geraet"]) for z in zeilen} == {("mail", "handy"), ("brief", "rechner")}
        assert db.get_besuche_je_lead()[1]["anzahl"] == 2
    _mit_testdatenbank(pruefung)


def test_eigene_klicks_zaehlen_nicht():
    def pruefung(client):
        _senden(client, {"quelle": "direkt", "intern": True})
        assert db.get_besuche_je_lead() == {}
        assert db.get_letzte_besuche() == []
    _mit_testdatenbank(pruefung)


def test_bots_und_link_vorschauen_werden_ignoriert():
    def pruefung(client):
        for agent in ("Googlebot/2.1", "Mozilla/5.0 (compatible; Microsoft Office Preview)", "python-httpx/0.27", ""):
            assert _senden(client, {}, agent=agent).json()["status"] == "ignoriert"
        assert db.get_letzte_besuche() == []
    _mit_testdatenbank(pruefung)


def test_unbekannte_seite_und_fremde_quelle():
    def pruefung(client):
        assert _senden(client, {}, slug="gibt-es-nicht").json()["status"] == "ignoriert"
        _senden(client, {"quelle": "<script>"})
        assert db.get_letzte_besuche()[0]["quelle"] == "direkt"
    _mit_testdatenbank(pruefung)


def test_kaputter_inhalt_wird_trotzdem_gezaehlt():
    def pruefung(client):
        r = client.post("/api/besuch/kreta-ka", content="kein json",
                        headers={"Content-Type": "text/plain", "User-Agent": HANDY})
        assert r.json()["status"] == "ok"
    _mit_testdatenbank(pruefung)


def test_demo_link_in_der_mail_bekommt_quelle():
    mail = akquise_mail_text("ich habe eine Seite gebaut.\n\nHier die Demo: "
                             "https://philswebsites.de/sites/kreta-ka/", "restaurant", "Karlsruhe")
    assert "https://philswebsites.de/sites/kreta-ka/?q=mail" in mail


if __name__ == "__main__":
    fehler = 0
    for name, funktion in list(globals().items()):
        if name.startswith("test_") and callable(funktion):
            try:
                funktion()
                print(f"  ok     {name}")
            except AssertionError as exc:
                fehler += 1
                print(f"  FEHLER {name}: {exc}")
    print(f"\n{'alle Tests bestanden' if not fehler else f'{fehler} Test(s) fehlgeschlagen'}")
    sys.exit(1 if fehler else 0)
