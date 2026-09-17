"""Tests fuer die Antwort-Erkennung.

Laeuft komplett ohne Netz und ohne echte Datenbank: Das IMAP-Postfach ist nachgebaut,
die Datenbank-Funktionen sind durch eine Liste ersetzt.

Aufruf:  .venv/Scripts/python.exe tests/test_antworten.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.outreach import antworten  # noqa: E402
from app.outreach.antworten import _imap_datum, adresse_in_meldung, auszug  # noqa: E402

NL = chr(10)


def _mail(von, betreff, datum, text, message_id):
    return (f"From: {von}{NL}Subject: {betreff}{NL}Date: {datum}{NL}Message-ID: {message_id}{NL}"
            f"Content-Type: text/plain; charset=utf-8{NL}{NL}{text}").encode("utf-8")


class FakeImap:
    """Beantwortet SEARCH ... FROM "<kriterium>" mit den passenden Mails."""

    postfach: dict[bytes, bytes] = {}
    abgesetzt: list = []

    def __init__(self, host):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def login(self, user, passwort):
        pass

    def list(self):
        return "OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/Alle Nachrichten"']

    def select(self, ordner, readonly=False):
        FakeImap.abgesetzt.append(("select", ordner, readonly))
        return "OK", [b"1"]

    def search(self, charset, *kriterien):
        gesucht = kriterien[-1].strip('"').lower()
        treffer = [n for n, roh in self.postfach.items()
                   if gesucht in roh.split(NL.encode())[0].decode().lower()]
        return "OK", [b" ".join(treffer)]

    def fetch(self, nummer, teil):
        FakeImap.abgesetzt.append(("fetch", teil))
        return "OK", [(b"1 (BODY[] {1}", self.postfach[nummer]), b")"]


def _lauf(postfach, leads):
    gespeichert = []
    FakeImap.postfach = postfach
    FakeImap.abgesetzt = []
    alt = (antworten.imaplib.IMAP4_SSL, antworten.db.get_angeschriebene_leads,
           antworten.db.add_antwort, antworten.settings.imap_password)
    ids = set()

    def add_antwort(**felder):
        if felder["nachricht_id"] in ids:
            return False
        ids.add(felder["nachricht_id"])
        gespeichert.append(felder)
        return True

    antworten.imaplib.IMAP4_SSL = FakeImap
    antworten.db.get_angeschriebene_leads = lambda: leads
    antworten.db.add_antwort = add_antwort
    antworten.settings.imap_password = "test"
    antworten.settings.imap_user = antworten.settings.imap_user or "test@example.com"
    try:
        neu = antworten.pruefe_antworten()
    finally:
        (antworten.imaplib.IMAP4_SSL, antworten.db.get_angeschriebene_leads,
         antworten.db.add_antwort, antworten.settings.imap_password) = alt
    return neu, gespeichert


LEADS = [
    {"id": 1, "name": "Landhaus Wibbecke", "contact_email": "info@landhaus-wibbecke.de",
     "emailed_at": "2026-09-17T15:40:00+00:00"},
    {"id": 2, "name": "Friseursalon", "contact_email": "salon@gmx.de",
     "emailed_at": "2026-09-17T15:36:00+00:00"},
]


def test_antwort_wird_erkannt():
    postfach = {b"1": _mail("Inhaber <info@landhaus-wibbecke.de>", "Re: Demo-Website",
                            "Thu, 17 Sep 2026 19:10:00 +0200", "Klingt gut, rufen Sie an.", "<a1@x>")}
    neu, gespeichert = _lauf(postfach, LEADS)
    assert neu == 1
    assert gespeichert[0]["lead_id"] == 1 and gespeichert[0]["art"] == "antwort"
    assert gespeichert[0]["auszug"] == "Klingt gut, rufen Sie an."


def test_andere_person_derselben_firmendomain_zaehlt():
    postfach = {b"1": _mail("chef@landhaus-wibbecke.de", "Re: Demo", "Thu, 17 Sep 2026 20:00:00 +0200",
                            "Interesse!", "<a2@x>")}
    neu, gespeichert = _lauf(postfach, LEADS)
    assert neu == 1 and gespeichert[0]["lead_id"] == 1


def test_fremde_gmx_adresse_zaehlt_nicht():
    """Bei Freemailern sagt die Domain nichts - irgendwer@gmx.de ist nicht der Salon."""
    postfach = {b"1": _mail("irgendwer@gmx.de", "Hallo", "Thu, 17 Sep 2026 20:00:00 +0200", "x", "<a3@x>")}
    neu, _ = _lauf(postfach, LEADS)
    assert neu == 0


def test_mail_vor_dem_versand_zaehlt_nicht():
    """17:30 in Deutschland ist 15:30 UTC - vor dem Versand um 15:40 UTC."""
    postfach = {b"1": _mail("info@landhaus-wibbecke.de", "alt", "Thu, 17 Sep 2026 17:30:00 +0200",
                            "frueher", "<a4@x>")}
    neu, _ = _lauf(postfach, LEADS)
    assert neu == 0


def test_dieselbe_mail_wird_nur_einmal_gespeichert():
    """Der Job laeuft alle fuenf Minuten und findet dieselbe Mail jedes Mal - in der echten
    Datenbank (hier eine Wegwerf-Kopie) landet sie trotzdem nur einmal."""
    import tempfile
    from app import db

    alt = db.settings.db_path
    with tempfile.TemporaryDirectory() as ordner:
        db.settings.db_path = str(pathlib.Path(ordner) / "test.db")
        try:
            db.init_db()
            with db.get_connection() as conn:
                conn.execute("INSERT INTO leads (id, place_id, name, category, city, found_at) "
                             "VALUES (1, 'p1', 'Test', 'cafe', 'Bonn', '2026-09-01')")
            felder = dict(lead_id=1, nachricht_id="<x@y>", art="antwort", absender="a",
                          betreff="b", auszug="c", empfangen_am="2026-09-17T18:00:00+00:00")
            assert db.add_antwort(**felder) is True
            assert db.add_antwort(**felder) is False
            assert len(db.get_antworten()) == 1
        finally:
            db.settings.db_path = alt


def test_unzustellbar_wird_dem_betrieb_zugeordnet():
    meldung = _mail("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", "Delivery Status Notification",
                    "Thu, 17 Sep 2026 18:00:00 +0200",
                    "Your message wasn't delivered to SALON@gmx.de because the address couldn't be found.",
                    "<b1@x>")
    neu, gespeichert = _lauf({b"1": meldung}, LEADS)
    assert neu == 1
    assert gespeichert[0]["art"] == "unzustellbar" and gespeichert[0]["lead_id"] == 2


def test_nur_lesend():
    postfach = {b"1": _mail("info@landhaus-wibbecke.de", "Re", "Thu, 17 Sep 2026 20:00:00 +0200", "ja", "<a6@x>")}
    _lauf(postfach, LEADS)
    assert ("select", '"[Gmail]/Alle Nachrichten"', True) in FakeImap.abgesetzt
    assert all(teil == "(BODY.PEEK[])" for art, *rest in FakeImap.abgesetzt if art == "fetch"
               for teil in rest)


def test_zitat_wird_abgeschnitten():
    text = NL.join(["Ja, gerne!", "", "Am 17.09.2026 um 17:40 schrieb Philipp Kranz:",
                    "> Guten Tag,", "> für das Landhaus ..."])
    assert auszug(text) == "Ja, gerne!"


def test_imap_datum_englisch():
    assert _imap_datum("2026-09-07T15:40:00+00:00") == "07-Sep-2026"
    assert _imap_datum("2026-03-01T00:00:00+00:00") == "01-Mar-2026"


def test_adresse_in_meldung():
    assert adresse_in_meldung("failed: INFO@cinebar.de", ["info@cinebar.de"]) == "info@cinebar.de"
    assert adresse_in_meldung("nichts", ["info@cinebar.de"]) is None


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
            except Exception as exc:
                fehler += 1
                print(f"  ABBRUCH {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'alle Tests bestanden' if not fehler else f'{fehler} Test(s) fehlgeschlagen'}")
    sys.exit(1 if fehler else 0)
