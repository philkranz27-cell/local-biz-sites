"""Tests fuer die kurze Akquise-Mail und die Nachfass-Mail.

Aufruf:  .venv/Scripts/python.exe tests/test_kurzmail.py
"""

import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.outreach import kurzmail  # noqa: E402

LEAD = {"name": "Kreta", "city": "Karlsruhe", "category": "restaurant", "site_slug": "kreta-ka",
        "osm_extras_json": None}


def _mit_preis(preis, pruefung):
    alt = kurzmail.settings.angebot_preis
    kurzmail.settings.angebot_preis = preis
    try:
        pruefung()
    finally:
        kurzmail.settings.angebot_preis = alt


def test_kurz_mit_preis_link_und_abmeldung():
    def pruefung():
        text = kurzmail.erstmail(LEAD)
        assert "einmalig 299 €" in text
        assert "/sites/kreta-ka/?q=mail" in text
        assert "Falls kein Interesse besteht" in text          # Abmeldehinweis bleibt
        assert "OpenStreetMap" in text                          # Herkunft der Daten bleibt
        assert len(text.split("---")[0].split()) < 110          # wirklich kurz
        assert kurzmail.betreff(LEAD) == "Kurze Frage zu Kreta"
    _mit_preis("einmalig 299 €", pruefung)


def test_ohne_preis_keine_mail():
    def pruefung():
        for funktion in (kurzmail.erstmail, kurzmail.nachfassmail):
            try:
                funktion(LEAD)
            except kurzmail.PreisFehlt:
                continue
            raise AssertionError(f"{funktion.__name__} lief ohne Preis")
    _mit_preis("", pruefung)


def test_anrede_mit_inhaber():
    def pruefung():
        lead = dict(LEAD, osm_extras_json='{"inhaber": "Maria Papadopoulou"}')
        assert kurzmail.erstmail(lead).startswith("Guten Tag Maria Papadopoulou,")
    _mit_preis("299 €", pruefung)


def test_nachfass_nur_einmal_und_nicht_nach_antwort():
    alt = db.settings.db_path
    with tempfile.TemporaryDirectory() as ordner:
        db.settings.db_path = str(pathlib.Path(ordner) / "test.db")
        try:
            db.init_db()
            vor_acht = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            vor_zwei = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            with db.get_connection() as conn:
                for i, (gemailt, name) in enumerate(((vor_acht, "alt"), (vor_zwei, "neu"),
                                                     (vor_acht, "geantwortet")), start=1):
                    conn.execute("INSERT INTO leads (id, place_id, name, category, city, found_at, "
                                 "site_slug, contact_email, status, emailed_at) VALUES "
                                 "(?, ?, ?, 'cafe', 'Bonn', '2026-09-01', ?, ?, 'emailed', ?)",
                                 (i, f"p{i}", name, f"s{i}", f"{name}@x.de", gemailt))
                conn.execute("INSERT INTO antworten (lead_id, nachricht_id, art, empfangen_am) "
                             "VALUES (3, '<a>', 'antwort', ?)", (vor_zwei,))
            stichtag = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            assert [r["name"] for r in db.get_nachfass_kandidaten(stichtag, 10)] == ["alt"]
            db.mark_nachfass(1)
            assert db.get_nachfass_kandidaten(stichtag, 10) == []
        finally:
            db.settings.db_path = alt


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
