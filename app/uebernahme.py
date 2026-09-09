"""Aus dem Aufnahmebogen eines Betriebs seine echte Seite machen.

Bis hierher endete alles bei der Zusage: finden, Seite bauen, anschreiben - und dann?
Es gab keinen Weg vom "Ja" zur fertigen Website. Genau an der Stelle haette man bei der
ersten Zusage improvisiert.

Der Kunde fuellt den Aufnahmebogen aus (philswebsites.de/start/), seine Angaben landen
in der Tabelle `aufnahmen`, und hier werden sie zu den Seitentexten. Bewusst OHNE KI:
Was der Betrieb ueber sich schreibt, ist besser als alles Erfundene, es kostet kein
Tageskontingent, und es ist reproduzierbar - derselbe Bogen ergibt immer dieselbe Seite.

Leer gelassene Felder aendern nichts. Wer nur das Angebot korrigiert, behaelt den Rest.
"""

from __future__ import annotations

import json

from app import db
from app.llm import GeneratedSiteCopy
from app.models import ServiceItem
from app.sitegen.generator import generate_site

# Ohne vorhandenen Text (aeltere Seiten haben keinen gespeicherten) muessen Schlagzeile
# und Aufforderung von Hand gesetzt werden - auch das ohne KI.
CTA_JE_KATEGORIE = {
    "restaurant": "Tisch reservieren",
    "cafe": "Tisch reservieren",
    "bar": "Tisch reservieren",
    "bakery": "Vorbestellen",
    "hair_salon": "Termin vereinbaren",
    "gym": "Probetraining anfragen",
    "florist": "Anfrage senden",
}

KATEGORIE_DEUTSCH = {
    "restaurant": "Restaurant", "cafe": "Café", "bar": "Bar", "bakery": "Bäckerei",
    "hair_salon": "Friseursalon", "gym": "Fitnessstudio", "florist": "Blumenladen",
}


def _zeilen(text: str | None) -> list[str]:
    return [z.strip(" -•\t") for z in (text or "").splitlines() if z.strip(" -•\t")]


def _leistungen(text: str | None) -> list[ServiceItem]:
    """Eine Leistung je Zeile. "Name: Beschreibung" wird getrennt, sonst steht der
    ganze Text als Name - der Kunde soll nicht in ein Format gezwungen werden."""
    eintraege = []
    for zeile in _zeilen(text):
        name, trenner, beschreibung = zeile.partition(":")
        eintraege.append(ServiceItem(
            name=(name if trenner else zeile).strip()[:60],
            description=beschreibung.strip() if trenner else "",
        ))
    return eintraege


def _grundtext(lead) -> GeneratedSiteCopy:
    """Notduerftiger Text fuer Seiten ohne gespeicherte Fassung - reine Tatsachen."""
    kategorie = KATEGORIE_DEUTSCH.get(lead["category"], lead["category"])
    return GeneratedSiteCopy(
        tagline=lead["city"],
        headline=lead["name"],
        subheadline=f"{kategorie} in {lead['city']}",
        about="",
        highlights=[],
        services=[],
        cta_text=CTA_JE_KATEGORIE.get(lead["category"], "Anfrage senden"),
        image_query=lead["category"],
    )


def uebernehmen(aufnahme_id: int) -> str:
    """Angaben einarbeiten und die Seite neu bauen. Gibt den Slug zurueck."""
    aufnahme = db.get_aufnahme(aufnahme_id)
    if aufnahme is None:
        raise ValueError(f"Aufnahmebogen {aufnahme_id} gibt es nicht")

    lead = db.get_lead_by_slug(aufnahme["site_slug"])
    if lead is None:
        raise ValueError(f"Kein Betrieb zu {aufnahme['site_slug']}")

    vorhanden = lead["site_copy_json"] if "site_copy_json" in lead.keys() else None
    copy = GeneratedSiteCopy.model_validate_json(vorhanden) if vorhanden else _grundtext(lead)

    if (aufnahme["ueber_uns"] or "").strip():
        copy.about = aufnahme["ueber_uns"].strip()
    highlights = _zeilen(aufnahme["highlights"])
    if highlights:
        copy.highlights = highlights[:3]
    leistungen = _leistungen(aufnahme["angebot"])
    if leistungen:
        copy.services = leistungen

    db.speichere_site_copy(lead["id"], copy.model_dump_json())

    # Korrigierte Oeffnungszeiten schlagen die Kartenangabe - der Betrieb kennt sie
    # besser als OpenStreetMap. Als eine Zeile pro Angabe, der Formatierer laesst
    # deutschen Text unveraendert stehen.
    zeiten = _zeilen(aufnahme["oeffnungszeiten"])
    if zeiten:
        with db.get_connection() as conn:
            conn.execute("UPDATE leads SET opening_hours_json = ? WHERE id = ?",
                         (json.dumps(zeiten, ensure_ascii=False), lead["id"]))

    # Ab jetzt steht der Text des Betriebs auf der Seite. Sie darf nicht laenger
    # behaupten, ihre Texte seien Beispiele - das waere gegenueber dem Kunden falsch.
    db.setze_seiten_status(lead["id"], "kundenentwurf")

    slug = generate_site(db.get_lead_by_slug(aufnahme["site_slug"]))
    db.mark_aufnahme_uebernommen(aufnahme_id)
    return slug
