"""Tests fuer die Vorteile in Brief und Mail.

Die wichtigste Zusicherung steht ganz unten: keine Zahlen, keine Versprechen. Ein
Werbebrief mit erfundener Statistik oder "mehr Umsatz garantiert" waere irrefuehrende
Werbung - und diese Saetze gehen an echte Betriebe.

Aufruf:  .venv/Scripts/python.exe tests/test_vorteile.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.outreach.vorteile import KATEGORIEN, vorteile  # noqa: E402


def test_immer_genau_drei():
    for kategorie in list(KATEGORIEN) + ["unbekannt", None]:
        assert len(vorteile(kategorie, "Augsburg")) == 3, kategorie


def test_branchenvorteil_steht_vorn():
    assert "Schnitts" in vorteile("hair_salon", "München")[0]
    assert "Tischreservierungen" in vorteile("restaurant", "München")[0]


def test_stadt_und_artikel_im_zweiten_punkt():
    assert "in Karlsruhe online nach einem Restaurant sucht" in vorteile("restaurant", "Karlsruhe")[1]
    assert "nach einer Bäckerei" in vorteile("bakery", "Leipzig")[1]


def test_ohne_stadt_kein_doppeltes_leerzeichen():
    assert "  " not in vorteile("cafe", None)[1]


def test_facebook_einwand_wird_aufgegriffen():
    punkte = vorteile("cafe", "Bonn", {"soziale_netze": {"Facebook": "https://facebook.com/x"}})
    assert "Facebook-Auftritt bleibt" in punkte[2]
    ohne = vorteile("cafe", "Bonn", {})
    assert "Facebook" not in ohne[2]


def test_keine_zahlen_und_keine_versprechen():
    """Kein Prozent, keine Statistik, kein Umsatz- oder Ranking-Versprechen."""
    verboten = re.compile(r"\d|%|garantiert|mehr umsatz|mehr kunden|platz 1|ganz oben|verdoppel", re.I)
    for kategorie in list(KATEGORIEN) + [None]:
        for extras in ({}, {"soziale_netze": {"Instagram": "https://instagram.com/x"}}):
            for punkt in vorteile(kategorie, "Stadt", extras):
                assert not verboten.search(punkt), punkt


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
