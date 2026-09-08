import logging
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.config import settings
from app.outreach.mailer import send_outreach_email
from app.sitegen.generator import generate_site
from app import progress
from app.publisher import veroeffentlichen
from app.sources.overpass import find_leads
from app.llm import generate_outreach_email

logger = logging.getLogger(__name__)


def _start_of_today_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


# Ein kompletter Suchlauf ueber alle Staedte und Kategorien sind 56x7 = 392 Abfragen und
# dauert bei ~80s pro Abfrage rund 9 Stunden. Weil run_pipeline die Phasen nacheinander
# ausfuehrt, kam die Website-Erzeugung dahinter praktisch nie an die Reihe - 83 fertig
# qualifizierte Leads lagen unbearbeitet da. Deshalb pro Durchlauf nur ein kleines Stueck
# der Liste abarbeiten und beim naechsten Mal dort weitermachen.
FIND_COMBOS_PER_RUN = 12
_CURSOR_FILE = Path(settings.db_path).parent / "find_cursor.txt"


def _load_cursor() -> int:
    """Position in der Stadt/Kategorie-Liste. Liegt in einer Datei, damit ein Neustart
    (der Rechner faehrt nachts hoch und runter) nicht wieder bei Berlin anfaengt."""
    try:
        return int(_CURSOR_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def _save_cursor(value: int) -> None:
    try:
        _CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CURSOR_FILE.write_text(str(value), encoding="utf-8")
    except OSError:
        logger.warning("Konnte Suchposition nicht speichern (%s)", _CURSOR_FILE)


def phase_find_leads() -> None:
    """Nach Nutzervorgabe nur Betriebe ohne Website UND mit bekannter Kontakt-Mail
    behalten - alles andere wird direkt aussortiert (kein Scraping/Impressum-Suche noetig,
    die Mail kommt ausschliesslich aus OSM-eigenen contact:email/email-Tags)."""
    combos = [(city, category) for city in settings.city_list for category in settings.category_list]
    if not combos:
        return

    start = _load_cursor() % len(combos)
    for offset in range(min(FIND_COMBOS_PER_RUN, len(combos))):
        if progress.is_paused():
            break
        position = (start + offset) % len(combos)
        city, category = combos[position]
        _save_cursor(position + 1)

        leads = find_leads(category, city, settings.max_leads_per_run)
        inserted = 0
        for lead in leads:
            lead_id = db.insert_lead(lead)
            if lead_id is None:
                continue
            inserted += 1
            if lead.existing_website:
                db.set_status(lead_id, "excluded_has_website")
            elif lead.osm_email:
                db.set_website_verdict(lead_id, "osm_tagged", lead.osm_email)
            else:
                db.set_status(lead_id, "excluded_no_email")
        logger.info(
            "Gefunden %s/%s: %d Treffer, %d neu (Position %d/%d)",
            category, city, len(leads), inserted, position + 1, len(combos),
        )
        progress.log(
            "suche" if leads else "fehler",
            f"{city} / {category}: {len(leads)} Treffer, {inserted} neu"
            f"  ·  Position {position + 1} von {len(combos)}",
            gruppe=None if leads else "suche:ohne-treffer",
        )


def phase_generate_sites() -> None:
    if not settings.groq_configured:
        progress.set_phase("websites", "Websites übersprungen – kein Groq-Zugang hinterlegt")
        return
    wartend = db.get_leads_by_status("email_found", limit=20)
    progress.set_phase("websites", f"Websites bauen – {len(wartend)} Betriebe in der Warteschlange")
    for row in wartend:
        if progress.is_paused():
            break
        try:
            slug = generate_site(row)
            db.set_site_generated(row["id"], slug)
            progress.log("websites", f"Website fertig: {row['name']} ({row['city']})")
        except progress.Angehalten:
            break
        except Exception as exc:
            logger.exception("Site-Generierung fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])
            progress.log("fehler", f"Website fehlgeschlagen: {row['name']} – {type(exc).__name__}",
                         gruppe=f"website:{type(exc).__name__}")


def phase_draft_emails() -> None:
    if not settings.groq_configured:
        return
    wartend = db.get_leads_by_status("site_generated", limit=20)
    progress.set_phase("entwuerfe", f"Mail-Entwürfe schreiben – {len(wartend)} offen")
    for row in wartend:
        if progress.is_paused():
            break
        try:
            demo_url = f"{settings.base_url}/sites/{row['site_slug']}/"
            email = generate_outreach_email(row["name"], row["category"], row["city"], demo_url)
            db.set_email_draft(row["id"], email.subject, email.body + f"\n\nHier die Demo: {demo_url}")
            progress.log("entwuerfe", f"Entwurf fertig: {row['name']}")
        except progress.Angehalten:
            break
        except Exception as exc:
            logger.exception("E-Mail-Entwurf fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])
            progress.log("fehler", f"Entwurf fehlgeschlagen: {row['name']} – {type(exc).__name__}",
                         gruppe=f"entwurf:{type(exc).__name__}")


def phase_send_emails() -> None:
    if not settings.mail_configured:
        logger.info("SMTP nicht konfiguriert, ueberspringe Versand")
        return
    sent_today = db.count_emails_sent_since(_start_of_today_iso())
    budget = settings.max_emails_per_day - sent_today
    if budget <= 0:
        progress.set_phase(
            "versand",
            "Versand pausiert – Tagesdeckel erreicht"
            if settings.max_emails_per_day else "Versand aus – MAX_EMAILS_PER_DAY steht auf 0",
        )
        return
    progress.set_phase("versand", f"Versand – noch {budget} Mails heute möglich")
    for row in db.get_leads_by_status("ready_to_send", limit=budget):
        if progress.is_paused():
            break
        # Widerspruch beachten. Steht vor dem Versand, nicht danach - eine gesperrte
        # Adresse darf gar nicht erst angeschrieben werden.
        if db.is_blocked(row["contact_email"]):
            db.set_status(row["id"], "blocked")
            logger.info("Uebersprungen, Adresse gesperrt: %s", row["contact_email"])
            continue
        try:
            send_outreach_email(row["contact_email"], row["email_subject"], row["email_body"])
            db.mark_emailed(row["id"])
            logger.info("Mail gesendet an Lead %s (%s)", row["id"], row["contact_email"])
            progress.log("versand", f"Mail gesendet an {row['name']} <{row['contact_email']}>")
        except Exception as exc:
            logger.exception("Versand fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])
            progress.log("fehler", f"Versand fehlgeschlagen: {row['name']} – {type(exc).__name__}",
                         gruppe=f"versand:{type(exc).__name__}")


def run_pipeline() -> None:
    # Verarbeitung zuerst, Suche zuletzt: der Rechner laeuft nicht durchgehend, sondern in
    # Schueben von ein bis zwei Stunden. Wer zuerst sucht, verbraucht das ganze Zeitfenster
    # mit Suchen und liefert am Ende keine einzige fertige Website.
    if progress.is_paused():
        return

    progress.start_run()
    try:
        phase_generate_sites()
        if progress.is_paused():
            return
        # Erst veroeffentlichen, dann Mails entwerfen und verschicken: Der Link in einer
        # Mail muss ab dem Moment funktionieren, in dem sie rausgeht - nicht erst beim
        # naechsten Durchlauf.
        progress.set_phase("veroeffentlichen", "Seiten veröffentlichen")
        if veroeffentlichen():
            progress.log("veroeffentlichen", "Demo-Seiten hochgeladen")
        phase_draft_emails()
        if progress.is_paused():
            return
        phase_send_emails()
        if progress.is_paused():
            return
        progress.set_phase("suche", "Neue Betriebe suchen")
        phase_find_leads()
    finally:
        # Auch bei einem Abbruch soll das Dashboard nicht ewig "läuft" anzeigen.
        progress.end_run()
