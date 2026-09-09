from typing import Optional

from pydantic import BaseModel


class Lead(BaseModel):
    """A business found via Google Places, before we know its website quality."""

    place_id: str
    name: str
    category: str
    city: str
    address: Optional[str] = None
    phone: Optional[str] = None
    existing_website: Optional[str] = None
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    opening_hours_json: Optional[str] = None
    osm_image: Optional[str] = None
    """image-Tag aus OSM, falls der Betrieb dort ein echtes Foto hinterlegt hat.
    Selten (in der Stichprobe 1 von 60), aber der einzige rechtlich saubere Weg zu
    einem Bild, das wirklich diesen Betrieb zeigt."""

    osm_extras_json: Optional[str] = None
    """Weitere OSM-Angaben als JSON: Barrierefreiheit, Aussenplaetze, Kueche, Ernaehrung,
    WLAN, Zahlungsarten, Facebook/Instagram, Inhabername. Die stehen bei den meisten
    Betrieben in der Karte und machen den Unterschied zwischen einer Seite, die zu diesem
    Betrieb gehoert, und einer, die zu jedem passt."""

    osm_email: Optional[str] = None
    """Direkt aus OSM-Tags (contact:email/email) - falls vorhanden, sparen wir uns das
    Scraping der Impressum-Seite fuer diesen Lead."""


class ServiceItem(BaseModel):
    name: str
    description: str


class GeneratedSiteCopy(BaseModel):
    """LLM-generated marketing copy for the demo site. No claims about the business we
    can't back up from the Places data we actually have (ratings, opening hours) - no
    fabricated testimonials, years-in-business claims, or awards."""

    tagline: str
    """Sehr kurzer Claim, 2-5 Woerter, erscheint klein ueber der Headline."""
    headline: str
    subheadline: str
    about: str
    highlights: list[str]
    """3 kurze, generische aber glaubwuerdige USP-Stichpunkte (keine erfundenen Fakten)."""
    services: list[ServiceItem]
    cta_text: str
    image_query: str
    """Englischer Suchbegriff fuer ein passendes, stimmungsvolles Stockfoto (Pexels)."""


class OutreachEmail(BaseModel):
    subject: str
    body: str


class BlockRequest(BaseModel):
    """Widerspruch: Diese Adresse wird nie (wieder) angeschrieben."""

    email: str
    grund: Optional[str] = None


class DealUpdate(BaseModel):
    deal_status: str
    deal_price: Optional[str] = None
    deal_notes: Optional[str] = None


class PaymentLinkRequest(BaseModel):
    amount_eur: float


class ReservationRequest(BaseModel):
    """Eingabe aus dem Anfrage-Popup auf einer Demo-Site."""

    customer_name: str
    contact: str
    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[str] = None
    message: Optional[str] = None


class AufnahmeRequest(BaseModel):
    """Aufnahmebogen: was ein Betrieb nach der Zusage liefert, damit aus dem
    Demo-Entwurf seine echte Seite wird. Alle Felder freiwillig - wer nur die
    Oeffnungszeiten korrigieren will, soll nicht den ganzen Bogen ausfuellen muessen."""

    ansprechpartner: Optional[str] = None
    telefon: Optional[str] = None
    email: Optional[str] = None
    ueber_uns: Optional[str] = None
    angebot: Optional[str] = None
    highlights: Optional[str] = None
    oeffnungszeiten: Optional[str] = None
    wunschadresse: Optional[str] = None
    farbwunsch: Optional[str] = None
    sonstiges: Optional[str] = None
