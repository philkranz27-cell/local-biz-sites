"""Tests fuer den kompletten Text der Akquise-Mail.

Anlass: Die Mail an die Baeckerei Schladitz begann mit "Guten Tag, Hallo, ich habe ..." -
die feste Anrede plus eine zweite, die die KI selbst geschrieben hatte.

Aufruf:  .venv/Scripts/python.exe tests/test_mailtext.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.outreach.mailer import _ohne_anrede, akquise_mail_text  # noqa: E402


def test_hallo_am_anfang_wird_entfernt():
    assert _ohne_anrede("Hallo, ich habe für Sie eine Seite gebaut.") == "ich habe für Sie eine Seite gebaut."


def test_guten_tag_am_anfang_wird_entfernt():
    assert _ohne_anrede("Guten Tag,\n\nfür die Bäckerei habe ich").startswith("für die Bäckerei")


def test_sehr_geehrte_damen_und_herren():
    assert _ohne_anrede("Sehr geehrte Damen und Herren, ich habe").startswith("ich habe")


def test_ohne_anrede_bleibt_alles_gleich():
    text = "Für den Troy Salon habe ich eine Demo-Website erstellt."
    assert _ohne_anrede(text) == text


def test_name_nach_anrede_behaelt_grossschreibung():
    assert _ohne_anrede("Hallo, Troy Salon hat eine neue Seite.") == "Troy Salon hat eine neue Seite."


def test_anrede_an_ein_team_wird_entfernt():
    """Echte Faelle aus den Entwuerfen vom 10.09."""
    assert _ohne_anrede("Hallo Amie Nails Team,  ich habe für Ihren Salon").startswith("ich habe")
    assert _ohne_anrede("Hallo Antonios Eis-Cafe-Team, ich habe für Ihr Café").startswith("ich habe")
    assert _ohne_anrede("Hallo Frollein Sommer-Team, ich habe für Ihr Café").startswith("ich habe")


def test_unklare_anrede_wird_nicht_angefasst():
    """Lieber eine doppelte Anrede als einen abgeschnittenen Namen."""
    text = "Hallo Herr Müller, ich habe eine Seite gebaut."
    assert _ohne_anrede(text) == text


def test_komplette_mail_hat_genau_eine_anrede():
    mail = akquise_mail_text("Hallo, ich habe für die Bäckerei eine Seite gebaut.", "bakery", "Leipzig")
    assert mail.count("Guten Tag") == 1
    assert "Hallo" not in mail
    assert "Was Ihnen eine eigene Website bringt:" in mail


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
