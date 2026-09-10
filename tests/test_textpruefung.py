"""Tests fuer die Textpruefung - die ersten Tests des Projekts.

Die Faelle stammen aus echten Ausgaben vom 10.09.2026, als zwei Runden Arbeit am Prompt
jeweils andere Regeln gebrochen haben. Laeuft ohne KI und ohne Kontingent.

Aufruf:  .venv/Scripts/python.exe tests/test_textpruefung.py
    oder .venv/Scripts/python.exe -m pytest tests
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.models import GeneratedSiteCopy, ServiceItem  # noqa: E402
from app.sitegen.textpruefung import AMTSTON, ERFUNDEN, pruefe  # noqa: E402


def _copy(**felder) -> GeneratedSiteCopy:
    basis = dict(tagline="Gutes Essen", headline="Betrieb", subheadline="Restaurant in Stadt",
                 about="", highlights=[], services=[], cta_text="Tisch reservieren",
                 image_query="restaurant")
    basis.update(felder)
    return GeneratedSiteCopy(**basis)


def _leistung(name: str, beschreibung: str) -> ServiceItem:
    return ServiceItem(name=name, description=beschreibung)


def test_sauberer_text_bleibt_unangetastet():
    """Die Pruefung darf gute Texte nicht beschaedigen - sonst lehnt sie alles ab."""
    copy = _copy(
        headline="Kreta",
        subheadline="Griechisches Restaurant in Karlsruhe",
        about=("Morgens ein Kaffee, mittags eine warme Mahlzeit, abends ein Glas Wein mit "
               "Freunden. Bei Kreta dreht sich alles um griechische Küche. Kommen Sie vorbei "
               "und probieren Sie sich durch die Karte."),
        highlights=["Mezedes zum Teilen", "Grillteller", "Griechischer Wein"],
        services=[
            _leistung("Grillteller", "Gegrilltes Fleisch mit Beilagen, direkt vom Grill auf den Tisch."),
            _leistung("Mezedes", "Kleine Vorspeisen zum Teilen für den ganzen Tisch."),
            _leistung("Mittagstisch", "Wechselnde Gerichte für die Mittagspause."),
            _leistung("Griechischer Wein", "Weiß, rot oder rosé – passend zum Essen."),
        ],
    )
    ergebnis = pruefe(copy, ["Plätze im Freien"], stadt="Karlsruhe", name="Kreta")
    assert ergebnis.in_ordnung, ergebnis.probleme
    assert ergebnis.reparaturen == [], ergebnis.reparaturen


def test_troy_salon_team_und_ambiente_werden_gestrichen():
    copy = _copy(
        tagline="Stilvolle Haarpflege",
        headline="Troy Salon",
        subheadline="Ihr Haarstudio in München",
        about=("Im Troy Salon erhalten Sie eine persönliche Beratung, die Ihre Vorstellungen "
               "berücksichtigt. Unser Team arbeitet mit Sorgfalt, um Ihren gewünschten Look zu "
               "realisieren. Während der Behandlung können Sie das ruhige Ambiente genießen. "
               "Sie verlassen den Salon mit einem frischen, gepflegten Aussehen."),
        highlights=["Präziser Schnitt", "Farbberatung", "Styling"],
        services=[_leistung("Haarschnitt", "Ein individueller Schnitt, der Ihren Stil unterstreicht."),
                  _leistung("Färbung", "Farben, die Ihrem Haar neuen Glanz verleihen."),
                  _leistung("Styling", "Professionelles Styling für jeden Anlass."),
                  _leistung("Haarpflege", "Pflegende Behandlungen, die Ihr Haar geschmeidig machen.")],
    )
    ergebnis = pruefe(copy, [], stadt="München", name="Troy Salon")
    assert "Ambiente" not in copy.about and "Team" not in copy.about
    assert "erhalten Sie" not in copy.about, "umgedrehte Wortstellung muss auch fallen"
    assert any("tagline" in p for p in ergebnis.probleme), "stilvoll in der tagline melden"


def test_gutshof_amtston_wird_abgelehnt():
    copy = _copy(
        headline="Gutshof Menterschwaige",
        about=("Im Gutshof Menterschwaige in München bieten wir vegetarische Gerichte für "
               "Frühstück, Mittag- und Abendessen. Sie können vor Ort speisen und dabei "
               "kostenfreies WLAN nutzen. Kartenzahlung ist möglich."),
        highlights=["Vegetarische Vorspeisen", "Vegetarische Hauptgerichte", "Vegetarische Desserts"],
        services=[_leistung("Vorspeise", "Sie erhalten eine leichte vegetarische Vorspeise."),
                  _leistung("Hauptgericht", "Sie erhalten ein vegetarisches Hauptgericht."),
                  _leistung("Dessert", "Sie erhalten ein süßes vegetarisches Dessert."),
                  _leistung("Getränke", "Sie erhalten eine Auswahl an Getränken.")],
    )
    ergebnis = pruefe(copy, ["Vegetarische Gerichte", "WLAN für Gäste", "Kartenzahlung möglich"],
                      stadt="München", name="Gutshof Menterschwaige")
    assert not ergebnis.in_ordnung
    assert "WLAN" not in copy.about and "Kartenzahlung" not in copy.about
    assert all("erhalten" not in s.description for s in copy.services)


def test_sorry_johnny_faktenband_wird_nicht_gedoppelt():
    fakten = ["Frühstück", "Kaffeespezialitäten", "Vegetarische Gerichte", "Plätze im Freien"]
    copy = _copy(
        headline="Sorry Johnny",
        about="Bei Sorry Johnny können Sie Frühstück genießen. Das Café bietet Sitzplätze im Freien.",
        highlights=["Kaffeespezialitäten", "Frühstück", "Vegetarische Gerichte", "Sitzplätze im Freien"],
        services=[_leistung("Frühstück", "Sie erhalten ein Frühstück aus unserem Angebot.")],
    )
    ergebnis = pruefe(copy, fakten, stadt="München", name="Sorry Johnny")
    assert not ergebnis.in_ordnung
    assert len(copy.highlights) <= 3
    assert not any(h.lower() in {f.lower() for f in fakten} for h in copy.highlights)
    assert not any("Sitzpl" in h for h in copy.highlights)


def test_zu_lange_schlagzeile_mit_stadt_wird_ersetzt():
    copy = _copy(headline="Restaurant im Gutshof Menterschwaige, München")
    pruefe(copy, [], stadt="München", name="Gutshof Menterschwaige")
    assert copy.headline == "Gutshof Menterschwaige"


def test_gutshof_rein_vegetarisch_und_saisonal_fallen():
    """Live-Ausgabe vom 10.09. nach der Reparatur: belegt war nur 'Vegetarische Gerichte'."""
    copy = _copy(
        headline="Gutshof Menterschwaige",
        about=("Im Gutshof Menterschwaige in München finden Sie ein rein vegetarisches Menü, das "
               "Sie sowohl zum Mittag als auch zum Abend genießen können. Unsere Küche arbeitet "
               "mit frischen, saisonalen Zutaten und legt Wert auf kreative Kombinationen. Wir "
               "freuen uns, Sie zu einem genussvollen Besuch begrüßen zu dürfen."),
    )
    pruefe(copy, ["Vegetarische Gerichte"], stadt="München", name="Gutshof Menterschwaige")
    assert "rein vegetarisch" not in copy.about
    assert "saisonal" not in copy.about


def test_aussenplaetze_sind_ausstattung():
    copy = _copy(about=("Ein Kaffee am Morgen, ein Stück Kuchen am Nachmittag. Dazu ein "
                        "Frühstück für den Start in den Tag. An den verfügbaren Außenplätzen "
                        "können Sie das Stadtleben beobachten."))
    pruefe(copy, ["Plätze im Freien"], stadt="München", name="Sorry Johnny")
    assert "Außenpl" not in copy.about


def test_wortgrenzen_keine_fehlalarme():
    assert ERFUNDEN.search("traurig") is None, "'urig' darf nicht in 'traurig' anschlagen"
    assert ERFUNDEN.search("Ein uriges Lokal") is not None, "'urig' als eigenes Wort schon"
    assert AMTSTON.search("Hier erhalten Sie Ihren Kaffee") is not None


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
