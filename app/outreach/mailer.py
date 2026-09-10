import json
import re
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import ReservationRequest
from app.outreach.vorteile import vorteile

# Art. 14 DSGVO: Wer Daten nicht bei der betroffenen Person selbst erhebt, muss ihr
# mitteilen, woher sie stammen. Viele Adressaten sind Einzelunternehmer, ihre
# Kontaktdaten sind damit personenbezogene Daten. Ein Satz erfuellt das - er stand
# bisher nur in den FAQ der Website, nicht in der Mail selbst.
OPT_OUT_NOTE = (
    "\n\n---\n"
    "Falls kein Interesse besteht: einfach kurz antworten, dann meldet sich hier niemand "
    "erneut.\n"
    "Ihre Kontaktdaten stammen aus dem öffentlich einsehbaren OpenStreetMap-Eintrag "
    "Ihres Betriebs. Auf Wunsch lösche ich sie.\n"
    f"{settings.sender_impressum}"
)

# Der Prompt weist das Sprachmodell an, weder Anrede noch Grussformel zu schreiben -
# "die wird automatisch angehaengt". Genau das fehlte aber: Die Mails begannen mitten
# im Satz ("ich habe fuer den Gutshof ...") und endeten ohne Namen. Beides gehoert
# hierhin und nicht ins Sprachmodell, weil es bei jeder Mail gleich ist.
GREETING = "Guten Tag,\n\n"

# Die Fotos auf den Demo-Seiten sind Stockbilder, keine Aufnahmen des Betriebs - echte
# gibt es fuer diese Betriebe nirgends in einer Form, die wir verwenden duerften.
# Ohne diesen Hinweis sieht ein Wirt fremde Raeume und haelt die Seite fuer unbrauchbar.
# Steht bewusst hier und nicht im Prompt: Er muss in JEDER Mail stehen, nicht mal so und
# mal anders formuliert - und er darf keinen Preis nennen.
PHOTO_NOTE = (
    "\n\nDie Fotos auf der Seite sind Platzhalter. Ihre eigenen Bilder, Texte, Farben "
    "und Angebote setze ich selbstverständlich ein – sagen Sie einfach, wie Sie es "
    "haben möchten."
)


def _signature() -> str:
    """Name des Absenders aus der Anbieterkennzeichnung ziehen - dort steht er ohnehin
    und muss nicht an zwei Stellen gepflegt werden."""
    name = (settings.sender_impressum or "").split(",")[0].strip()
    return f"\n\nViele Grüße\n{name}" if name else ""


def _send(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.from_name} <{settings.from_email}>"
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(message)


def akquise_mail_text(body: str, kategorie: str | None = None, stadt: str | None = None,
                      extras: dict | None = None) -> str:
    """Der komplette Text, wie er beim Betrieb ankommt.

    Eine Funktion fuer Versand UND Vorschau im Dashboard - sonst zeigt das Dashboard
    etwas anderes, als tatsaechlich rausgeht. Der Vorteile-Block steht nach dem
    eigentlichen Anschreiben: erst "hier ist Ihr Entwurf", dann "darum lohnt es sich"."""
    punkte = vorteile(kategorie, stadt, extras)
    block = "\n\nWas Ihnen eine eigene Website bringt:\n" + "\n".join(f"– {p}" for p in punkte)
    return GREETING + _ohne_anrede(body) + block + PHOTO_NOTE + _signature() + OPT_OUT_NOTE


# Die KI beginnt ihren Text trotz Anweisung manchmal selbst mit "Hallo," - zusammen mit
# der festen Anrede davor stand dann "Guten Tag, Hallo, ich habe ..." in der Mail
# (gesehen bei der Baeckerei Schladitz). Nur eine Anrede ganz am Anfang wird entfernt.
_ANREDE_AM_ANFANG = re.compile(
    r"^\s*(?:hallo|guten tag|guten morgen|sehr geehrte[rs]?(?: damen und herren)?|liebe[rs]?)"
    # Entweder hoechstens ein Wort ("Hallo zusammen,") oder eine Anrede an ein Team, die
    # beliebig viele Woerter haben darf ("Hallo Amie Nails Team,"). Eine Anrede an eine
    # Person ("Hallo Herr Mueller,") bleibt stehen - lieber doppelt als ein halber Name.
    r"(?:\s+[^\s,!]+|\s+[^,!\n]{1,50}?[-\s]team)?\s*[,!]\s*",
    re.IGNORECASE,
)


def _ohne_anrede(body: str) -> str:
    # Nur entfernen, Gross- und Kleinschreibung nicht anfassen: Nach "Hallo," schreibt die
    # KI ohnehin klein weiter, und steht dort ein Name ("Troy Salon ..."), waere ein
    # erzwungener Kleinbuchstabe falsch.
    return _ANREDE_AM_ANFANG.sub("", body or "", count=1)


def send_outreach_email(to_email: str, subject: str, body: str, kategorie: str | None = None,
                        stadt: str | None = None, extras: dict | None = None) -> None:
    _send(to_email, subject, akquise_mail_text(body, kategorie, stadt, extras))


def akquise_mail_fuer_lead(lead) -> str:
    """Kompletter Mailtext fuer einen Lead aus der Datenbank - fuer die Dashboard-Vorschau."""
    extras = json.loads(lead["osm_extras_json"]) if lead["osm_extras_json"] else None
    return akquise_mail_text(lead["email_body"] or "", lead["category"], lead["city"], extras)


def send_reservation_notification(business_name: str, slug: str, req: ReservationRequest) -> None:
    """Geht an den Betreiber (nicht an den Betrieb!) wenn jemand das Anfrage-Popup auf
    einer Demo-Site ausfuellt - meist der Betriebsinhaber selbst beim Testen der Demo."""
    lines = [
        f"Neue Anfrage ueber die Demo-Site von '{business_name}' (/{slug}/):",
        "",
        f"Name: {req.customer_name}",
        f"Kontakt: {req.contact}",
    ]
    if req.date:
        lines.append(f"Datum: {req.date}")
    if req.time:
        lines.append(f"Uhrzeit: {req.time}")
    if req.party_size:
        lines.append(f"Personen: {req.party_size}")
    if req.message:
        lines.append(f"Nachricht: {req.message}")
    _send(settings.notify_email or settings.from_email,
          f"Demo-Anfrage: {business_name}", "\n".join(lines))


def send_aufnahme_notification(business_name: str, slug: str, felder: dict) -> None:
    """Meldung an uns, sobald ein Betrieb seinen Aufnahmebogen abgeschickt hat.
    Das ist der wichtigste Moment im ganzen Ablauf - ab hier gibt es einen Kunden."""
    BEZEICHNUNG = {
        "ansprechpartner": "Ansprechpartner", "telefon": "Telefon", "email": "E-Mail",
        "ueber_uns": "Über uns", "angebot": "Angebot", "highlights": "Highlights",
        "oeffnungszeiten": "Öffnungszeiten", "wunschadresse": "Wunschadresse",
        "farbwunsch": "Farbwunsch", "sonstiges": "Sonstiges",
    }
    lines = [f"{business_name} hat den Aufnahmebogen ausgefüllt (/{slug}/).", ""]
    for schluessel, titel in BEZEICHNUNG.items():
        wert = (felder.get(schluessel) or "").strip()
        if wert:
            lines.append(f"{titel}:")
            lines.extend("  " + z for z in wert.splitlines())
            lines.append("")
    lines.append("Im Dashboard unter Zahlungen: „Angaben übernehmen“ baut die Seite damit neu.")
    _send(settings.notify_email or settings.from_email,
          f"Aufnahmebogen: {business_name}", "\n".join(lines))
