"""Erstellt echte Stripe Payment Links - keine eigene Checkout-Seite noetig, Stripe
hostet die Zahlungsseite selbst. Test-Keys (sk_test_...) funktionieren sofort ohne
Geschaeftsverifizierung; fuer echte Auszahlungen muss der Stripe-Account spaeter
verifiziert werden (live keys sk_live_...)."""

import stripe

from app.config import settings


def create_payment_link(business_name: str, amount_eur: float) -> str:
    stripe.api_key = settings.stripe_secret_key
    price = stripe.Price.create(
        currency="eur",
        unit_amount=int(round(amount_eur * 100)),
        product_data={"name": f"Website fuer {business_name}"},
    )
    link = stripe.PaymentLink.create(line_items=[{"price": price.id, "quantity": 1}])
    return link.url
