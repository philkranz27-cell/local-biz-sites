import logging
from datetime import datetime, timezone

from app import db
from app.config import settings
from app.outreach.mailer import send_outreach_email
from app.sitegen.generator import generate_site
from app.sources.overpass import find_leads
from app.llm import generate_outreach_email

logger = logging.getLogger(__name__)


def _start_of_today_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def phase_find_leads() -> None:
    """Nach Nutzervorgabe nur Betriebe ohne Website UND mit bekannter Kontakt-Mail
    behalten - alles andere wird direkt aussortiert (kein Scraping/Impressum-Suche noetig,
    die Mail kommt ausschliesslich aus OSM-eigenen contact:email/email-Tags)."""
    for city in settings.city_list:
        for category in settings.category_list:
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
            logger.info("Gefunden %s/%s: %d Treffer, %d neu", category, city, len(leads), inserted)


def phase_generate_sites() -> None:
    if not settings.groq_configured:
        return
    for row in db.get_leads_by_status("email_found", limit=20):
        try:
            slug = generate_site(row)
            db.set_site_generated(row["id"], slug)
        except Exception:
            logger.exception("Site-Generierung fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])


def phase_draft_emails() -> None:
    if not settings.groq_configured:
        return
    for row in db.get_leads_by_status("site_generated", limit=20):
        try:
            demo_url = f"{settings.base_url}/sites/{row['site_slug']}/"
            email = generate_outreach_email(row["name"], row["category"], row["city"], demo_url)
            db.set_email_draft(row["id"], email.subject, email.body + f"\n\nHier die Demo: {demo_url}")
        except Exception:
            logger.exception("E-Mail-Entwurf fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])


def phase_send_emails() -> None:
    if not settings.mail_configured:
        logger.info("SMTP nicht konfiguriert, ueberspringe Versand")
        return
    sent_today = db.count_emails_sent_since(_start_of_today_iso())
    budget = settings.max_emails_per_day - sent_today
    if budget <= 0:
        return
    for row in db.get_leads_by_status("ready_to_send", limit=budget):
        try:
            send_outreach_email(row["contact_email"], row["email_subject"], row["email_body"])
            db.mark_emailed(row["id"])
            logger.info("Mail gesendet an Lead %s (%s)", row["id"], row["contact_email"])
        except Exception:
            logger.exception("Versand fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])


def run_pipeline() -> None:
    phase_find_leads()
    phase_generate_sites()
    phase_draft_emails()
    phase_send_emails()
