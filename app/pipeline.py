import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import groq

from app import db
from app.anschrift import vollstaendig
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
            elif lead.osm_extras_json and '"kette"' in lead.osm_extras_json:
                # Filialbetrieb (Kieser, Clever fit, Blume 2000 ...). Ueber die Website
                # entscheidet die Zentrale, nicht der Standort - ein Brief dorthin ist
                # Porto ohne Aussicht.
                db.set_status(lead_id, "excluded_kette")
            elif lead.osm_email:
                db.set_website_verdict(lead_id, "osm_tagged", lead.osm_email)
            elif vollstaendig(lead.address):
                # Keine Mailadresse, aber eine Anschrift, an die ein Brief ankommt.
                # Frueher landeten diese Betriebe unter "excluded_no_email" und waren
                # damit weg - das war die halbe Zielgruppe, denn der Briefweg braucht
                # gar keine Mailadresse.
                db.set_status(lead_id, "nur_anschrift")
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
    # Solange alte Seiten auf ihren neuen Text warten, wird nichts Neues gebaut.
    # Grund: Das kostenlose Tageskontingent reicht fuer rund 60 Seiten - entweder neue
    # bauen oder alte erneuern, nicht beides. Die vorhandenen Seiten haben Vorrang, denn
    # auf sie zeigen die verschickten QR-Codes, und ihre Texte enthalten noch erfundene
    # Behauptungen. Sobald phase_rewrite_texts alle erneuert hat, laeuft der Neubau von
    # selbst wieder.
    offen = db.zaehle_ohne_text()
    if offen:
        progress.set_phase("websites",
                           f"Neubau ruht – {offen} vorhandene Seiten warten auf ihren neuen Text")
        progress.log("websites", f"Neubau pausiert: {offen} Seiten brauchen erst neuen Text",
                     gruppe="websites:neubau-ruht")
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
        except groq.RateLimitError:
            # Vorübergehend, nicht der Fehler dieses Betriebs: NICHT als Fehlversuch
            # zählen. Sonst sortiert ein aufgebrauchtes Tageskontingent nach drei
            # Durchläufen völlig gesunde Leads dauerhaft aus.
            progress.log("fehler", "Tageskontingent erschöpft – Rest wartet auf morgen",
                         gruppe="websites:kontingent")
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
        except groq.RateLimitError:
            progress.log("fehler", "Tageskontingent erschöpft – Rest wartet auf morgen",
                         gruppe="entwuerfe:kontingent")
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
            extras = json.loads(row["osm_extras_json"]) if row["osm_extras_json"] else None
            send_outreach_email(row["contact_email"], row["email_subject"], row["email_body"],
                                row["category"], row["city"], extras)
            db.mark_emailed(row["id"])
            logger.info("Mail gesendet an Lead %s (%s)", row["id"], row["contact_email"])
            progress.log("versand", f"Mail gesendet an {row['name']} <{row['contact_email']}>")
        except Exception as exc:
            logger.exception("Versand fehlgeschlagen fuer Lead %s", row["id"])
            db.mark_error(row["id"])
            progress.log("fehler", f"Versand fehlgeschlagen: {row['name']} – {type(exc).__name__}",
                         gruppe=f"versand:{type(exc).__name__}")


# Pro Durchlauf nur ein Stueck: Die Pipeline laeuft jede Minute, und ein Durchlauf soll
# nicht eine halbe Stunde lang an Texten haengen, waehrend Suche und Veroeffentlichung
# warten.
TEXTE_PRO_DURCHLAUF = 10
_AUSWAHL_DATEI = Path(settings.db_path).parent / "auswahl.json"


def phase_rewrite_texts() -> None:
    """Erneuert die Texte bestehender Seiten mit der aktuellen Fassung des Prompts.

    Lief frueher als taeglich geplante Aufgabe - die konnte nie funktionieren: Sie
    brauchte fuer jeden Lauf eine Freigabe, die beim automatischen Start niemand
    erteilt, und lief nur bei geoeffneter App. Hier laeuft es im Server, der ohnehin
    durchgehend arbeitet, das Kontingent kennt und keine Freigaben braucht.

    Briefempfaenger zuerst: Wer angeschrieben wird, soll die bessere Seite sehen.
    """
    offen = db.get_leads_ohne_text()
    if not offen:
        return
    try:
        bevorzugt = set(json.loads(_AUSWAHL_DATEI.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        bevorzugt = set()
    offen.sort(key=lambda l: (l["site_slug"] not in bevorzugt, l["id"]))

    progress.set_phase("websites", f"Texte erneuern – {len(offen)} Seiten offen")
    for row in offen[:TEXTE_PRO_DURCHLAUF]:
        if progress.is_paused():
            break
        try:
            generate_site(row)
            progress.log("websites", f"Text erneuert: {row['name']} ({row['city']})")
        except progress.Angehalten:
            break
        except groq.RateLimitError:
            # Wie beim Neubau: kein Fehler des Betriebs, also nicht mitzaehlen.
            progress.log("fehler", "Tageskontingent erschöpft – Texte erneuern geht morgen weiter",
                         gruppe="texte:kontingent")
            break
        except Exception:
            logger.exception("Text erneuern fehlgeschlagen fuer Lead %s", row["id"])
            db.text_fehlgeschlagen(row["id"])
            progress.log("fehler", f"Text erneuern fehlgeschlagen: {row['name']}",
                         gruppe="texte:fehler")


def run_pipeline() -> None:
    # Verarbeitung zuerst, Suche zuletzt: der Rechner laeuft nicht durchgehend, sondern in
    # Schueben von ein bis zwei Stunden. Wer zuerst sucht, verbraucht das ganze Zeitfenster
    # mit Suchen und liefert am Ende keine einzige fertige Website.
    if progress.is_paused():
        return

    progress.start_run()
    try:
        phase_rewrite_texts()
        if progress.is_paused():
            return
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
