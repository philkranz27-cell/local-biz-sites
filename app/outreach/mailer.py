import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import ReservationRequest

OPT_OUT_NOTE = (
    "\n\n---\n"
    "Falls kein Interesse besteht: einfach kurz antworten, dann meldet sich hier niemand "
    "erneut.\n"
    f"{settings.sender_impressum}"
)

# Der Prompt weist das Sprachmodell an, weder Anrede noch Grussformel zu schreiben -
# "die wird automatisch angehaengt". Genau das fehlte aber: Die Mails begannen mitten
# im Satz ("ich habe fuer den Gutshof ...") und endeten ohne Namen. Beides gehoert
# hierhin und nicht ins Sprachmodell, weil es bei jeder Mail gleich ist.
GREETING = "Guten Tag,\n\n"


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
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


def send_outreach_email(to_email: str, subject: str, body: str) -> None:
    _send(to_email, subject, GREETING + body + _signature() + OPT_OUT_NOTE)


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
