import json
import logging
import time

import groq

from app.config import settings
from app.models import GeneratedSiteCopy, OutreachEmail

logger = logging.getLogger(__name__)

_client: groq.Groq | None = None

# Der 2-stufige Entwurf+Ueberarbeitung-Ansatz braucht mehr Tokens/Minute als Groqs
# kostenloses Free-Tier-Limit (8000 TPM) bei mehreren Leads pro Durchlauf hergibt.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SEC = 20

# Sprachlicher Stil je Design-Vorlage, damit Text und Optik zusammenpassen statt sich
# generisch anzufuehlen (siehe app/sitegen/generator.py fuer die Vorlagen-Auswahl).
STYLE_HINTS = {
    "modern_minimal.html.j2": (
        "Klar, direkt, modern-frisch, aber in fliessenden, natuerlichen Saetzen "
        "geschrieben - keine abgehackten Fragmente, keine Ausschmueckung."
    ),
    "warm_editorial.html.j2": "Warm, einladend, mit sinnlichen Details (Handwerk, Gemuetlichkeit, Atmosphaere).",
    "bold_dark.html.j2": (
        "Laessig, selbstbewusst, mit Attituede, aber in ganzen Saetzen - kurze pointierte "
        "Saetze sind ok, keine Teilsatz-Stakkato-Aneinanderreihung."
    ),
    "elegant_boutique.html.j2": "Gehoben, ruhig, exklusiv, zurueckhaltend elegant. Keine Ausrufezeichen, kein Superlativ-Overkill.",
}

STYLE_COMMON_RULE = (
    "Bleib durchgehend bei der foermlichen Anrede ('Sie') - auch im laessigen Stil kein "
    "ploetzlicher Wechsel zu 'Du' oder Imperativ-Befehlen wie 'Komm vorbei'."
)


def _get_client() -> groq.Groq:
    global _client
    if _client is None:
        _client = groq.Groq(api_key=settings.groq_api_key)
    return _client


def _structured(system_prompt: str, user_prompt: str, schema_model: type, temperature: float = 0.5) -> dict:
    client = _get_client()
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return _call(client, system_prompt, user_prompt, schema_model, temperature)
        except groq.RateLimitError:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            logger.warning("Groq-Rate-Limit erreicht, warte %ds (Versuch %d/%d)", RATE_LIMIT_BACKOFF_SEC, attempt + 1, RATE_LIMIT_RETRIES)
            time.sleep(RATE_LIMIT_BACKOFF_SEC)


def _call(client: groq.Groq, system_prompt: str, user_prompt: str, schema_model: type, temperature: float) -> dict:
    response = client.chat.completions.create(
        model=settings.analysis_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": schema_model.__name__, "schema": schema_model.model_json_schema()},
        },
    )
    return json.loads(response.choices[0].message.content)


SITE_COPY_SYSTEM_PROMPT = """\
Du bist Texter fuer hochwertige, individuelle Website-Entwuerfe fuer lokale Betriebe \
(Restaurants, Friseure, Baeckereien, Cafes, Bars, Fitnessstudios, Blumenlaeden), auf \
Basis oeffentlicher OpenStreetMap-Daten. Zwei Dinge sind entscheidend:

1. EHRLICHKEIT: Erfinde keine Fakten - keine falschen Auszeichnungen, keine erfundenen \
Spezialitaeten, Jahreszahlen, Kundenzitate oder Testimonials. "highlights" muessen \
generisch-aber-glaubwuerdig bleiben (z.B. "Persoenliche Beratung", "Zentrale Lage"), \
nie konkrete unbelegbare Behauptungen wie "seit 1985" oder "preisgekroent".

2. EINZIGARTIGKEIT: Jeder Text muss sich klar von einem austauschbaren Standard-Text \
unterscheiden - nutze den konkreten Betriebsnamen, die Stadt und die Kategorie, um eine \
eigene Stimme zu finden statt generischer Floskeln wie "Willkommen bei X" oder "geniessen \
Sie". Halte dich an den vorgegebenen Sprachstil fuer dieses Design.

Schreibe alles auf Deutsch (image_query ausgenommen). Antworte NUR mit den angeforderten \
Feldern."""

REFINE_SYSTEM_PROMPT = """\
Du bist ein strenger Lektor fuer Website-Texte lokaler Betriebe. Du bekommst einen ersten \
Entwurf als JSON. Deine Aufgabe: identifiziere jede Floskel und austauschbare Formulierung \
(z.B. "geniessen Sie", "Willkommen bei", "hochwertige Produkte" ohne Kontext, "das Herz \
von X" falls Standardphrase) und schreibe den KOMPLETTEN Text neu, sodass er sich \
erkennbar auf genau diesen Betrieb bezieht - Name, Ort, Kategorie und Sprachstil muessen \
durchscheinen. Wenn ein Feld schon gut und konkret ist, darfst du es beibehalten - aber \
sei kritisch, der Standard ist hoch. Erfinde weiterhin keine Fakten (keine Jahreszahlen, \
Auszeichnungen, Zitate). Antworte NUR mit dem kompletten ueberarbeiteten JSON im exakt \
gleichen Format wie der Entwurf."""


def _draft_site_copy(
    name: str, category: str, city: str, address: str | None, rating: float | None, review_count: int | None, style_hint: str
) -> dict:
    rating_line = f"Google-Bewertung: {rating} Sterne ({review_count} Bewertungen)." if rating else "Noch keine Bewertungen bekannt."
    address_line = f"Adresse: {address}" if address else ""
    user_prompt = (
        f"Betrieb: {name}\nKategorie: {category}\nStadt: {city}\n{address_line}\n{rating_line}\n"
        f"Sprachstil fuer dieses Design: {style_hint} {STYLE_COMMON_RULE}\n\n"
        "Schreibe:\n"
        "- tagline: 2-5 Woerter, sehr kurzer einpraegsamer Claim\n"
        "- headline: kurz, nennt den Betriebsnamen\n"
        "- subheadline: 1 Satz, stellt Kategorie und Stadt klar heraus (lokaler Bezug wichtig)\n"
        "- about: 3-4 Saetze, einladend und konkret fuer diese Betriebsart, keine Floskeln\n"
        "- highlights: genau 3 kurze, glaubwuerdige USP-Stichpunkte (je 2-4 Woerter)\n"
        "- services: 4-6 Eintraege mit name (kurz) und description (ein knapper Satz), "
        "typisch fuer diese Betriebsart\n"
        "- cta_text: kurzer Call-to-Action-Button-Text passend zur Kategorie "
        "(z.B. 'Tisch reservieren', 'Termin vereinbaren', 'Jetzt anrufen')\n"
        "- image_query: 3-5 englische Suchbegriffe fuer ein stimmungsvolles, thematisch "
        "passendes Stockfoto auf Pexels (z.B. 'cozy italian restaurant candlelight'), "
        "spezifisch genug fuer ein Foto mit Charakter, nicht nur der Kategoriename"
    )
    return _structured(SITE_COPY_SYSTEM_PROMPT, user_prompt, GeneratedSiteCopy, temperature=0.9)


def _refine_site_copy(draft: dict, name: str, category: str, city: str, style_hint: str) -> dict:
    user_prompt = (
        f"Betrieb: {name}\nKategorie: {category}\nStadt: {city}\nSprachstil: {style_hint} {STYLE_COMMON_RULE}\n\n"
        f"Entwurf:\n{json.dumps(draft, ensure_ascii=False)}"
    )
    return _structured(REFINE_SYSTEM_PROMPT, user_prompt, GeneratedSiteCopy, temperature=0.7)


def generate_site_copy(
    name: str,
    category: str,
    city: str,
    address: str | None,
    rating: float | None,
    review_count: int | None,
    style_hint: str,
) -> GeneratedSiteCopy:
    """Zweistufig: Entwurf, dann kritische Ueberarbeitung gegen Floskeln - mehr Aufwand
    pro Seite, damit sich Texte nicht wie maschinell durchgereicht anfuehlen."""
    draft = _draft_site_copy(name, category, city, address, rating, review_count, style_hint)
    refined = _refine_site_copy(draft, name, category, city, style_hint)
    return GeneratedSiteCopy.model_validate(refined)


EMAIL_SYSTEM_PROMPT = """\
Du schreibst kurze, freundliche Akquise-E-Mails auf Deutsch an lokale Betriebe. Ziel: \
auf eine bereits fertig gebaute Demo-Website fuer den Betrieb hinweisen und dezent \
Interesse an einer bezahlten Uebernahme wecken. Ton: persoenlich, kurz (max. 120 \
Woerter im Fliesstext), kein Hochglanz-Marketing-Sprech, keine Superlative, keine \
falschen Behauptungen ueber den Betrieb, keine konkrete Preisnennung. Erwaehne konkret \
den Betriebsnamen und dass es sich um eine unverbindliche Demo handelt. Baue sinngemaess \
ein, dass man sich bei Interesse gerne ueber die genauen Konditionen/Preise austauschen \
kann (keine Zahl nennen, nur das Angebot zum Austausch). Schliesse NICHT mit einer \
Anrede/Grussformel oder Signatur ab - die wird automatisch angehaengt. Antworte NUR mit \
subject und body (body = nur der Fliesstext ohne Anrede am Anfang oder Gruss am Ende)."""


def generate_outreach_email(name: str, category: str, city: str, demo_url: str) -> OutreachEmail:
    user_prompt = (
        f"Betrieb: {name}\nKategorie: {category}\nStadt: {city}\nDemo-Link: {demo_url}\n\n"
        "Schreibe subject und body wie im System-Prompt beschrieben."
    )
    data = _structured(EMAIL_SYSTEM_PROMPT, user_prompt, OutreachEmail)
    return OutreachEmail.model_validate(data)
