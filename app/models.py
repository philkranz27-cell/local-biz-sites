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
