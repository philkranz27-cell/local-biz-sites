-- status-Verlauf eines Leads:
-- found -> (no_email_found | site_generated) -> emailed -> replied / won / lost
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    city TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    existing_website TEXT,
    website_verdict TEXT,
    contact_email TEXT,
    rating REAL,
    user_ratings_total INTEGER,
    opening_hours_json TEXT,
    status TEXT NOT NULL DEFAULT 'found',
    site_slug TEXT,
    email_subject TEXT,
    email_body TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    found_at TEXT NOT NULL,
    site_generated_at TEXT,
    emailed_at TEXT,
    deal_status TEXT NOT NULL DEFAULT 'offen',
    deal_price TEXT,
    deal_notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_city ON leads(city);

CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    sent_at TEXT NOT NULL
);

-- Widersprueche. Wer hier steht, wird nie (wieder) angeschrieben. Rechtlich wichtig:
-- Ein Widerspruch muss dauerhaft und nachweisbar beachtet werden - ihn nur im Postfach
-- zu lesen und im Kopf zu behalten reicht nicht.
-- Adresse in Kleinbuchstaben, damit "Info@X.de" und "info@x.de" derselbe Eintrag sind.
CREATE TABLE IF NOT EXISTS blocklist (
    email TEXT PRIMARY KEY,
    grund TEXT,
    erstellt_am TEXT NOT NULL
);
