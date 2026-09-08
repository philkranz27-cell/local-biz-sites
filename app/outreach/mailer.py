import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import ReservationRequest

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


def send_outreach_email(to_email: str, subject: str, body: str) -> None:
    _send(to_email, subject, GREETING + body + PHOTO_NOTE + _signature() + OPT_OUT_NOTE)


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
    _send(settings.from_email, f"Demo-Anfrage: {business_name}", "\n".join(lines))
