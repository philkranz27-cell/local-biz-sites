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
from app.website_suche import finde_website
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
                # Ob es trotzdem eine Website gibt, prueft phase_websites_pruefen - vorher
                # wird fuer den Betrieb weder eine Seite gebaut noch geschrieben.
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


WEBSITE_PRUEFUNGEN_PRO_LAUF = 40


def _website_pruefen(row, websuche: bool = False):
    befund = finde_website(row["name"], row["city"], row["address"], row["contact_email"],
                           row["existing_website"], websuche=websuche)
    neu = db.speichere_websitebefund(row["id"], befund.ergebnis, befund.url, befund.quelle,
                                     vollstaendig(row["address"]))
    if befund.ergebnis != "keine":
        logger.info("Website-Pruefung %s (%s): %s %s -> %s", row["name"], row["city"],
                    befund.ergebnis, befund.url or "", neu)
    return befund


def phase_websites_pruefen() -> None:
    """Prueft, ob Betriebe schon eine Website haben, bevor irgendetwas fuer sie passiert.

    Eigener Job im Minutentakt (app/scheduler.py), damit er nicht hinter der langen
    Pipeline wartet. Die Websuche (knappes Kontingent) nur fuer Betriebe, die demnaechst
    angeschrieben werden - per Mail oder per Brief."""
    from concurrent.futures import ThreadPoolExecutor

    offen = db.get_ungepruefte_leads(WEBSITE_PRUEFUNGEN_PRO_LAUF)
    if not offen:
        return

    def pruefen(row):
        bald = row["status"] in ("ready_to_send", "site_generated") or (
            row["status"] == "nur_anschrift" and row["site_slug"])
        try:
            return _website_pruefen(row, websuche=bald)
        except Exception:
            logger.exception("Website-Pruefung fehlgeschlagen fuer Lead %s", row["id"])
            return None

    with ThreadPoolExecutor(20) as pool:
        befunde = [b for b in pool.map(pruefen, offen) if b]
    gefunden = sum(1 for b in befunde if b.ergebnis in ("website", "vielleicht"))
    if gefunden:
        progress.log("suche", f"Website-Prüfung: {gefunden} von {len(befunde)} Betrieben haben schon eine",
                     gruppe="suche:website-pruefung")


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

    # Nur Betriebe, bei denen die Website-Pruefung schon durch ist - sonst baut man eine
    # Demo-Seite fuer jemanden, der laengst eine hat, und verbraucht Groq-Tokens dafuer.
    wartend = [r for r in db.get_leads_by_status("email_found", limit=60)
               if r["website_geprueft_am"]][:20]
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
    # Harter Zaun: Liegt eine Mailauswahl vor, geht ausschliesslich an diese Betriebe Post
    # raus - unabhaengig davon, was der Tagesdeckel noch erlauben wuerde.
    auswahl = _slugliste(_MAILAUSWAHL_DATEI)
    kandidaten = db.get_leads_by_status("ready_to_send", limit=500 if auswahl else budget)
    if auswahl:
        kandidaten = [r for r in kandidaten if r["site_slug"] in auswahl][:budget]
    kandidaten = kandidaten[:MAILS_PRO_DURCHLAUF]
    if not kandidaten:
        progress.set_phase("versand", "Versand – nichts offen in der Mailauswahl"
                           if auswahl else "Versand – nichts offen")
        return

    progress.set_phase("versand", f"Versand – noch {budget} Mails heute möglich")
    for row in kandidaten:
        if progress.is_paused():
            break
        # Widerspruch beachten. Steht vor dem Versand, nicht danach - eine gesperrte
        # Adresse darf gar nicht erst angeschrieben werden.
        if db.is_blocked(row["contact_email"]):
            db.set_status(row["id"], "blocked")
            logger.info("Uebersprungen, Adresse gesperrt: %s", row["contact_email"])
            continue
        # Letzte Sicherung vor dem Versand: Hat der Betrieb schon eine Website? In der
        # ersten Runde am 17.09. traf das auf 10 von 20 zu - OSM kannte ihre Seiten nicht.
        if not row["website_geprueft_am"]:
            befund = _website_pruefen(row, websuche=True)
            if befund.ergebnis != "keine":
                progress.log("versand", f"Übersprungen: {row['name']} – "
                             + ("hat schon eine Website" if befund.ergebnis in ("website", "vielleicht")
                                else "Mail-Domain tot"))
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

# Dieselbe Idee fuer den Mailversand: eine Liste von site_slug, an die geschrieben werden
# darf. Ohne sie wuerde der Tagesdeckel einfach die ersten Leads nach ID nehmen - darunter
# die 20 Briefempfaenger, die dann Brief UND Mail bekaemen.
_MAILAUSWAHL_DATEI = Path(settings.db_path).parent / "mailauswahl.json"

# Nicht alle Mails in derselben Minute: Zwanzig gleichzeitig an fremde Adressen sieht fuer
# jeden Spamfilter nach einer Welle aus. Die Pipeline laeuft jede Minute, so verteilt sich
# der Versand von selbst ueber eine knappe halbe Stunde.
MAILS_PRO_DURCHLAUF = 3


def _slugliste(datei: Path) -> set[str]:
    try:
        return set(json.loads(datei.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


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
    bevorzugt = _slugliste(_AUSWAHL_DATEI)
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
        # Der Versand laeuft nicht hier, sondern als eigener Job jede Minute (siehe
        # app/scheduler.py). Zweimal aufgerufen koennten beide Stellen gleichzeitig
        # denselben Betrieb greifen und ihm die Mail doppelt schicken.
        phase_rewrite_texts()
        if progress.is_paused():
            return
        phase_generate_sites()
        if progress.is_paused():
            return
        # Erst veroeffentlichen, dann Mails entwerfen: Der Link in einer Mail muss ab dem
        # Moment funktionieren, in dem sie rausgeht. Verschickt wird der Entwurf deshalb
        # erst im naechsten Durchlauf, ganz oben - eine Minute spaeter.
        progress.set_phase("veroeffentlichen", "Seiten veröffentlichen")
        if veroeffentlichen():
            progress.log("veroeffentlichen", "Demo-Seiten hochgeladen")
        phase_draft_emails()
        if progress.is_paused():
            return
        progress.set_phase("suche", "Neue Betriebe suchen")
        phase_find_leads()
    finally:
        # Auch bei einem Abbruch soll das Dashboard nicht ewig "läuft" anzeigen.
        progress.end_run()
