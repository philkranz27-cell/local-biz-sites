"""Tests fuer die Suche nach einer vorhandenen Website ueber Name und Stadt.

Die Faelle stammen aus der Pruefung vom 18.09.2026 - echte Treffer und echte Fehlgriffe.
Ohne Netz: Getestet werden die Regeln, nicht das Abrufen.

Aufruf:  .venv/Scripts/python.exe tests/test_website_suche.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import website_suche  # noqa: E402
from app.website_suche import (_ascii, _klartext, _ortsmerkmale, _passt,  # noqa: E402
                               _starker_domaintreffer, _woerter, kandidaten)


def _pruefe(html, name, adresse, stadt):
    return _passt(_klartext(html), _ascii(html, True), _woerter(name, True),
                  _ortsmerkmale(adresse, stadt))


def test_kandidaten_enthalten_die_ueblichen_schreibweisen():
    k = kandidaten("Café Magnolie", "Braunschweig")
    for erwartet in ("cafemagnolie.de", "cafe-magnolie.de", "magnolie.de", "magnolie-braunschweig.de"):
        assert erwartet in k, (erwartet, k)


def test_kandidaten_mit_umlaut_in_beiden_formen():
    k = kandidaten("Fräulein Coffea", "Bochum")
    assert "fraeuleincoffea.de" in k and "fraeulein-coffea.de" in k
    assert "frauleincoffea.de" in k


def test_kandidaten_k_wie_kartoffel():
    """Das einzelne "K" darf nicht als Fuellwort verschwinden."""
    assert "k-wie-kartoffel.de" in kandidaten("K wie Kartoffel", "Bochum")


def test_seite_mit_name_und_stadt_passt():
    html = "<title>Casa del Gatto Bonn</title><p>Italienisches Restaurant in Bonn</p>"
    assert _pruefe(html, "Casa del Gatto", "Poppelsdorfer Allee 5, 53115 Bonn", "Bonn")


def test_inkassobuero_troy_ist_kein_friseur():
    """troy.de: "troy" steht drauf, Muenchen nur irgendwo im Quelltext, "Salon" gar nicht."""
    html = ('<title>troy - wir erfinden Inkasso neu</title><p>troy Inkasso fuer Unternehmen</p>'
            '<script>{"office":"München"}</script>')
    assert not _pruefe(html, "Troy Salon", "Sendlinger Str. 1, 80331 München", "München")


def test_stadt_nur_im_quelltext_reicht_nicht_postleitzahl_schon():
    html_stadt = '<p>Espresso Garage</p><script>{"city":"kiel"}</script>'
    html_plz = '<p>Espresso Garage</p><script>{"zip":"24103"}</script>'
    assert not _pruefe(html_stadt, "espresso garage", "Ringstraße 58, 24103 Kiel", "Kiel")
    assert _pruefe(html_plz, "espresso garage", "Ringstraße 58, 24103 Kiel", "Kiel")


def test_leere_seite_nur_mit_stadt_in_der_domain_sicher():
    assert _starker_domaintreffer("bloom-hamburg.de", "bloom", "Hamburg")
    assert not _starker_domaintreffer("flower-power.com", "Flower Power", "Wiesbaden")
    assert not _starker_domaintreffer("kosmonaut.de", "Kosmonaut", "Regensburg")


def test_finde_website_unsicherer_treffer_heisst_vielleicht():
    """Leere Seite unter dem genauen Namen: nicht sicher, aber auch nicht anschreiben."""
    alt = (website_suche.pruefe_maildomain, website_suche.pruefe_domain_fuer_betrieb)
    website_suche.pruefe_maildomain = lambda email: None
    website_suche.pruefe_domain_fuer_betrieb = (
        lambda d, *a, **k: ("https://harryab.com/", False) if d == "harryab.com" else (None, False))
    try:
        befund = website_suche.finde_website("HARRY AB", "Bonn", None, "harryab12@gmx.de")
    finally:
        website_suche.pruefe_maildomain, website_suche.pruefe_domain_fuer_betrieb = alt
    assert befund.ergebnis == "vielleicht" and befund.url == "https://harryab.com/"


def test_finde_website_osm_zuerst():
    befund = website_suche.finde_website("X", "Y", None, None, osm_website="https://x.de")
    assert befund.ergebnis == "website" and befund.quelle == "osm"


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
