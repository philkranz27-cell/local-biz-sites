import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import Lead

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

MAX_ERROR_COUNT = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    p = Path(settings.db_path)
    return p if p.is_absolute() else PROJECT_ROOT / p


@contextmanager
def get_connection():
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Lightweight migration: CREATE TABLE IF NOT EXISTS above doesn't add columns to an
        # already-existing table, so patch older databases up to the current schema here.
        existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
        if "deal_status" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN deal_status TEXT NOT NULL DEFAULT 'offen'")
        if "deal_price" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN deal_price TEXT")
        if "deal_notes" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN deal_notes TEXT")
        if "stripe_payment_link" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN stripe_payment_link TEXT")
        if "osm_image" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN osm_image TEXT")
        if "osm_extras_json" not in existing_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN osm_extras_json TEXT")
        if "site_copy_json" not in existing_columns:
            # Ohne den gespeicherten Text laesst sich eine Seite nur neu bauen, indem die
            # KI den Text neu erfindet - jede Aenderung an der Vorlage wuerde also auch
            # den Inhalt wuerfeln. Mit ihm ist Neuaufbau kostenlos und vorhersagbar.
            conn.execute("ALTER TABLE leads ADD COLUMN site_copy_json TEXT")


def insert_lead(lead: Lead) -> int | None:
    """Insert a newly found lead. Returns the new row id, or None if already known."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO leads
                (place_id, name, category, city, address, phone, existing_website,
                 rating, user_ratings_total, opening_hours_json, osm_image,
                 osm_extras_json, status, found_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'found', ?)
            """,
            (
                lead.place_id,
                lead.name,
                lead.category,
                lead.city,
                lead.address,
                lead.phone,
                lead.existing_website,
                lead.rating,
                lead.user_ratings_total,
                lead.opening_hours_json,
                lead.osm_image,
                lead.osm_extras_json,
                _now(),
            ),
        )
        if cursor.rowcount == 0:
            return None
        return cursor.lastrowid


def get_leads_by_status(status: str, limit: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE status = ? AND error_count < ? ORDER BY id ASC LIMIT ?",
            (status, MAX_ERROR_COUNT, limit),
        ).fetchall()


def set_website_verdict(lead_id: int, verdict: str, contact_email: str) -> None:
    """Wird nur fuer Leads ohne Website mit direkt in OSM getaggter Mail aufgerufen
    (verdict='osm_tagged') - alles andere wird schon in phase_find_leads aussortiert."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET website_verdict = ?, contact_email = ?, status = 'email_found' WHERE id = ?",
            (verdict, contact_email, lead_id),
        )


def set_site_generated(lead_id: int, slug: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET site_slug = ?, status = 'site_generated', site_generated_at = ? WHERE id = ?",
            (slug, _now(), lead_id),
        )


def set_email_draft(lead_id: int, subject: str, body: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET email_subject = ?, email_body = ?, status = 'ready_to_send' WHERE id = ?",
            (subject, body, lead_id),
        )


def mark_emailed(lead_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE leads SET status = 'emailed', emailed_at = ?,
                deal_status = CASE WHEN deal_status = 'offen' THEN 'kontaktiert' ELSE deal_status END
            WHERE id = ?
            """,
            (_now(), lead_id),
        )
        conn.execute("INSERT INTO send_log (lead_id, sent_at) VALUES (?, ?)", (lead_id, _now()))


def update_deal(lead_id: int, deal_status: str, deal_price: str | None, deal_notes: str | None) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE leads SET deal_status = ?, deal_price = ?, deal_notes = ? WHERE id = ?",
            (deal_status, deal_price, deal_notes, lead_id),
        )


def mark_error(lead_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE leads SET error_count = error_count + 1 WHERE id = ?", (lead_id,))


def set_status(lead_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))


def count_emails_sent_since(since_iso: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM send_log WHERE sent_at >= ?", (since_iso,)
        ).fetchone()
        return row["n"] if row else 0


def get_lead_by_slug(slug: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM leads WHERE site_slug = ?", (slug,)).fetchone()


def get_lead_by_id(lead_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def set_payment_link(lead_id: int, url: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE leads SET stripe_payment_link = ? WHERE id = ?", (url, lead_id))


def get_all_leads(limit: int = 500) -> list[sqlite3.Row]:
    """Nur qualifizierte Leads (keine Website + bekannte Mail).

    Ausgeschlossene Leads bleiben in der DB (fuer Dedup ueber place_id), tauchen aber
    nicht im Dashboard auf. "nur_anschrift" ebenfalls nicht: davon gibt es rund 9.000,
    sie haben eine eigene Ansicht (get_briefkandidaten) und wuerden diese Liste sonst
    vollstaendig verdraengen."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE status NOT LIKE 'excluded_%' AND status != 'nur_anschrift' "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def count_screened() -> int:
    """Alle jemals geprueften Betriebe, auch die aussortierten.

    Die aussortierten bleiben in der Tabelle, damit dieselbe Baeckerei nicht bei jedem
    Durchlauf erneut bewertet wird. Fuers Dashboard ist die Zahl trotzdem wichtig: 127
    qualifizierte Leads sehen nach wenig aus, bis daneben steht, dass dafuer ueber
    zwoelftausend Betriebe durchgesehen wurden."""
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM leads").fetchone()["n"]


def get_stats() -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM leads "
            "WHERE status NOT LIKE 'excluded_%' AND status != 'nur_anschrift' GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}


# --- Anfragen von den Demo-Seiten -------------------------------------------------


def add_reservation(lead_id: int | None, slug: str, req) -> int:
    """Anfrage festhalten, BEVOR die Benachrichtigung versucht wird. Scheitert der
    Mailversand, ist die Anfrage trotzdem da."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO reservations
                (lead_id, site_slug, kundenname, kontakt, datum, uhrzeit, personen,
                 nachricht, erstellt_am)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (lead_id, slug, req.customer_name, req.contact, req.date, req.time,
             req.party_size, req.message, _now()),
        )
        return cur.lastrowid


def mark_reservation_notified(reservation_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE reservations SET benachrichtigt = 1 WHERE id = ?", (reservation_id,))


def get_reservations(limit: int = 50) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT r.*, l.name AS betrieb, l.city AS stadt
            FROM reservations r LEFT JOIN leads l ON l.id = r.lead_id
            ORDER BY r.id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()


# --- Sperrliste ------------------------------------------------------------------
# Ein Widerspruch muss dauerhaft beachtet werden. Adressen immer klein vergleichen,
# sonst schluepft "Info@X.de" an einem Eintrag "info@x.de" vorbei.


def block_email(email: str, grund: str = "") -> bool:
    """Adresse sperren. Gibt False zurueck, wenn sie schon gesperrt war."""
    email = (email or "").strip().lower()
    if not email:
        return False
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO blocklist (email, grund, erstellt_am) VALUES (?, ?, ?)",
            (email, grund.strip() or None, datetime.now(timezone.utc).isoformat()),
        )
        return cur.rowcount > 0


def unblock_email(email: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM blocklist WHERE email = ?", ((email or "").strip().lower(),))


def is_blocked(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    with get_connection() as conn:
        return conn.execute("SELECT 1 FROM blocklist WHERE email = ?", (email,)).fetchone() is not None


def get_blocklist() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM blocklist ORDER BY erstellt_am DESC").fetchall()


def speichere_site_copy(lead_id: int, copy_json: str) -> None:
    """Den einmal erzeugten Seitentext festhalten, damit die Seite spaeter ohne neuen
    KI-Aufruf identisch neu gebaut werden kann."""
    with get_connection() as conn:
        conn.execute("UPDATE leads SET site_copy_json = ? WHERE id = ?", (copy_json, lead_id))


def get_briefkandidaten(limit: int = 150) -> list[sqlite3.Row]:
    """Betriebe ohne Mailadresse, aber mit brieffaehiger Anschrift.

    Bewusst begrenzt: davon gibt es rund 9.000, die gehoeren nicht alle in eine
    HTML-Tabelle. Die Gesamtzahl liefert zaehle_status().
    """
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE status = 'nur_anschrift' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()


def zaehle_status() -> dict[str, int]:
    """Alle Status mit Anzahl - auch die aussortierten, anders als get_stats()."""
    with get_connection() as conn:
        return {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM leads GROUP BY status")}
