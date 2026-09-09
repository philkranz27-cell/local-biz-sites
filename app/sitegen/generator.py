import hashlib
import json
import re
import sqlite3
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app import db
from app.llm import STYLE_HINTS, GeneratedSiteCopy, generate_site_copy
from app.config import settings
from app.sources.osm_extras import fakten
from app.sitegen.images import get_photos
from app.sitegen.opening_hours import format_opening_hours
from app.sitegen.osm_photo import hole_foto

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).parent / "templates"
SITES_DIR = PROJECT_ROOT / "data" / "sites"

_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

ALL_TEMPLATES = ["modern_minimal.html.j2", "warm_editorial.html.j2", "bold_dark.html.j2", "elegant_boutique.html.j2"]

# Welche Design-Sprachen zu welcher Betriebsart passen - je Kategorie 2 Optionen, damit
# nicht jeder Betrieb derselben Kategorie identisch aussieht.
TEMPLATE_POOLS = {
    "restaurant": ["modern_minimal.html.j2", "warm_editorial.html.j2"],
    "bakery": ["warm_editorial.html.j2", "modern_minimal.html.j2"],
    "cafe": ["warm_editorial.html.j2", "modern_minimal.html.j2"],
    "hair_salon": ["elegant_boutique.html.j2", "warm_editorial.html.j2"],
    "florist": ["elegant_boutique.html.j2", "warm_editorial.html.j2"],
    "bar": ["bold_dark.html.j2", "modern_minimal.html.j2"],
    "gym": ["bold_dark.html.j2", "modern_minimal.html.j2"],
}

# Nur der Akzentton wechselt zwischen Leads - Ink/Paper bleiben pro Template fest, damit
# jedes Design in sich stimmig bleibt.
PALETTES = [
    {"accent": "#c0392b", "accent_dark": "#922b21"},
    {"accent": "#2c7a4b", "accent_dark": "#1e5c38"},
    {"accent": "#b8860b", "accent_dark": "#8a6508"},
    {"accent": "#1f5f8b", "accent_dark": "#154a6e"},
    {"accent": "#8e44ad", "accent_dark": "#6c3483"},
    {"accent": "#d35400", "accent_dark": "#a84300"},
]


def _stable_hash(s: str) -> int:
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


def pick_template(category: str, place_id: str) -> str:
    pool = TEMPLATE_POOLS.get(category, ALL_TEMPLATES)
    return pool[_stable_hash(place_id) % len(pool)]


def pick_palette(place_id: str) -> dict:
    return PALETTES[(_stable_hash(place_id) // 7) % len(PALETTES)]


def slugify(name: str, city: str, place_id: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", f"{name}-{city}".lower()).strip("-")
    return f"{base}-{place_id[-6:]}"


def _hat(lead: sqlite3.Row, spalte: str) -> bool:
    return spalte in lead.keys() and lead[spalte]


def generate_site(lead: sqlite3.Row) -> str:
    """Generates the static demo site for a lead, writes it to disk, returns its slug."""
    template_name = pick_template(lead["category"], lead["place_id"])
    palette = pick_palette(lead["place_id"])
    style_hint = STYLE_HINTS[template_name]

    # Angaben aus der Karte: die einzigen Inhalte auf der Seite, die nachweislich zu
    # diesem Betrieb gehoeren. Erst ab zwei lohnt ein eigener Abschnitt - ein einzelnes
    # "teilweise barrierefrei" unter einer Ueberschrift wirkt duenner als gar nichts.
    extras = json.loads(lead["osm_extras_json"]) if _hat(lead, "osm_extras_json") else {}
    fakten_liste = fakten(extras)
    if len(fakten_liste) < 2:
        fakten_liste = []
    soziale_netze = extras.get("soziale_netze") or {}

    # Einmal geschriebenen Text behalten. Ohne ihn wuerde jede Aenderung an einer Vorlage
    # auch den Inhalt neu wuerfeln - und kostet ein KI-Kontingent, das taeglich begrenzt
    # ist. Mit ihm ist ein Neuaufbau kostenlos und liefert exakt dieselbe Seite.
    gespeichert = lead["site_copy_json"] if _hat(lead, "site_copy_json") else None
    copy = GeneratedSiteCopy.model_validate_json(gespeichert) if gespeichert else generate_site_copy(
        lead["name"],
        lead["category"],
        lead["city"],
        lead["address"],
        lead["rating"],
        lead["user_ratings_total"],
        style_hint,
        fakten_liste,
    )
    if not gespeichert:
        db.speichere_site_copy(lead["id"], copy.model_dump_json())

    photos = get_photos(copy.image_query, lead["category"], count=4)
    hero_image = photos[0] if photos else None
    gallery_images = photos[1:4] if len(photos) > 1 else []

    # Hat der Betrieb in OSM ein echtes Foto hinterlegt, kommt das nach vorne - ein
    # Bild des Betriebs schlaegt jedes Stimmungsbild. Kommt selten vor (Stichprobe:
    # 1 von 60), lohnt sich aber genau bei denen, wo es klappt.
    echtes_foto = hole_foto(lead["osm_image"] if "osm_image" in lead.keys() else None)
    if echtes_foto:
        if hero_image:
            gallery_images = ([hero_image] + gallery_images)[:3]
        hero_image = echtes_foto

    slug = slugify(lead["name"], lead["city"], lead["place_id"])
    # OSM-Rohsyntax ("Su-Th 17:00-23:30") in lesbares Deutsch uebersetzen, bevor sie
    # auf der Seite eines potenziellen Kunden landet.
    opening_hours = format_opening_hours(
        json.loads(lead["opening_hours_json"]) if lead["opening_hours_json"] else None
    )

    html = _env.get_template(template_name).render(
        name=lead["name"],
        city=lead["city"],
        category=lead["category"],
        tagline=copy.tagline,
        headline=copy.headline,
        subheadline=copy.subheadline,
        about=copy.about,
        highlights=copy.highlights,
        services=copy.services,
        cta_text=copy.cta_text,
        phone=lead["phone"],
        address=lead["address"],
        rating=lead["rating"],
        review_count=lead["user_ratings_total"],
        opening_hours=opening_hours,
        hero_image=hero_image,
        gallery_images=gallery_images,
        accent=palette["accent"],
        accent_dark=palette["accent_dark"],
        slug=slug,
        api_base=settings.api_base,
        fakten=fakten_liste,
        soziale_netze=soziale_netze,
    )

    site_dir = SITES_DIR / slug
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    return slug
