"""Tests fuer die Pruefung, ob die Mail-Domain eines Betriebs schon eine Website hat.

Anlass: Von den ersten 20 angeschriebenen Betrieben hatten acht eine eigene Seite, die
OpenStreetMap nicht kannte. Getestet wird nur die Auswertung, ohne Netz.

Aufruf:  .venv/Scripts/python.exe tests/test_website_pruefung.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.website_pruefung import bewerte_antwort, pruefe_maildomain  # noqa: E402

SEITE = "<html><head><title>Cine Bar</title></head><body>" + "Cocktails und Kino " * 30 + "</body></html>"


def test_echte_seite_zaehlt_als_website():
    assert bewerte_antwort("cinebar.de", 200, "https://www.cinebar.de/", SEITE) == "website"


def test_umleitung_auf_fremde_domain_ist_tot():
    """intershop-bochum.de leitete auf eine Glücksspielseite um."""
    assert bewerte_antwort("intershop-bochum.de", 200, "https://botak123.it.com/", SEITE) == "tot"


def test_domain_zum_verkauf_ist_tot():
    html = "<title>Der Domainname schechs.de steht zum Verkauf</title>"
    assert bewerte_antwort("schechs.de", 200, "https://schechs.de/", html) == "tot"


def test_abgelaufene_squarespace_seite_ist_tot():
    html = "<title>Squarespace - Website Expired</title>"
    assert bewerte_antwort("palinske.de", 404, "https://www.palinske.de/", html) == "tot"


def test_einfaches_404_heisst_keine_seite():
    assert bewerte_antwort("beispiel.de", 404, "https://beispiel.de/", "<h1>Not Found</h1>") == "keine"


def test_fast_leere_seite_zaehlt_im_zweifel_als_website():
    """Baukasten-Seiten liefern oft nur ein Geruest - lieber nicht anschreiben."""
    html = "<html><body><div id='root'></div><script src='app.js'></script></body></html>"
    assert bewerte_antwort("baukasten.de", 200, "https://baukasten.de/", html) == "website"


def test_www_und_ohne_www_sind_dieselbe_domain():
    assert bewerte_antwort("cafemagnolie.de", 200, "https://www.cafemagnolie.de/home", SEITE) == "website"


def test_umleitung_auf_instagram_heisst_keine_website():
    """croenlein.com zeigt nur auf das Instagram-Profil - genau die Zielgruppe."""
    assert bewerte_antwort("croenlein.com", 200, "https://www.instagram.com/croenlein_/", SEITE) == "keine"


def test_umleitung_auf_eigene_andere_endung_ist_website():
    assert bewerte_antwort("losteria.de", 200, "https://losteria.net/de/", SEITE) == "website"


def test_umleitung_auf_fremden_betrieb_ist_tot():
    """schnittwerke.com zeigt inzwischen auf ein anderes Haarstudio."""
    assert bewerte_antwort("schnittwerke.com", 200, "https://haarstudioandi.de", SEITE) == "tot"


def test_freemailer_wird_nicht_geprueft():
    assert pruefe_maildomain("harryab12@gmx.de") is None
    assert pruefe_maildomain("cafecamus.basim@gmail.com") is None
    assert pruefe_maildomain(None) is None


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
