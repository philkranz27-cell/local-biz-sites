import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app import db
from app.config import settings
from app.models import BlockRequest, DealUpdate, PaymentLinkRequest, ReservationRequest
from app.outreach.inbox import fetch_recent_messages
from app.outreach.mailer import send_reservation_notification
from app.payments import create_payment_link
from app import progress, publisher
from app.pipeline import run_pipeline
from app.sources import overpass

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

router = APIRouter()

_basic_auth = HTTPBasic(auto_error=True)


def require_admin(credentials: HTTPBasicCredentials = Depends(_basic_auth)) -> str:
    """Schuetzt Dashboard und Verwaltungs-Endpunkte. Wichtig, weil die App per Tunnel
    oeffentlich erreichbar ist - ohne das koennte jeder mit der Adresse die Firmenkontakte,
    Mail-Entwuerfe und sogar den Posteingang (/api/inbox) abrufen.

    Faellt bewusst zu (deny), wenn kein Passwort gesetzt ist - lieber ausgesperrt als offen."""
    if not settings.dashboard_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_PASSWORD ist nicht gesetzt - Dashboard aus Sicherheitsgruenden gesperrt.",
        )
    user_ok = secrets.compare_digest(credentials.username, settings.dashboard_user)
    pass_ok = secrets.compare_digest(credentials.password, settings.dashboard_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falsche Zugangsdaten",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
def dashboard(request: Request):
    leads = db.get_all_leads()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "leads": leads,
            "stats": db.get_stats(),
            "total_leads": len(leads),
            "screened_leads": db.count_screened(),
            "emails_drafted": sum(1 for l in leads if l["email_subject"]),
            "emails_sent": sum(1 for l in leads if l["status"] == "emailed"),
            "deals_active": sum(1 for l in leads if l["deal_status"] not in ("offen", "abgelehnt")),
            "imap_configured": settings.imap_configured,
            "stripe_configured": settings.stripe_configured,
            "imap_user": settings.imap_user,
            "source_health": overpass.source_health(),
            "publish_health": publisher.publish_health(),
            "blocklist": db.get_blocklist(),
            "reservations": db.get_reservations(),
        },
    )


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.post("/api/run-pipeline", dependencies=[Depends(require_admin)])
def api_run_pipeline(background_tasks: BackgroundTasks):
    """Manueller Trigger fuer Tests, statt auf das naechste Scheduler-Intervall zu warten."""
    background_tasks.add_task(run_pipeline)
    return {"status": "started"}


@router.post("/api/pipeline/pause", dependencies=[Depends(require_admin)])
def api_pause():
    """Haelt die Pipeline an - auch mitten im Durchlauf. Die Phasen pruefen den Schalter
    zwischen den einzelnen Betrieben, ein laufender Durchlauf bricht also zuegig ab
    statt erst nach zwanzig weiteren Versuchen."""
    progress.pause()
    return {"status": "ok", "paused": True}


@router.post("/api/pipeline/resume", dependencies=[Depends(require_admin)])
def api_resume():
    progress.resume()
    return {"status": "ok", "paused": False}


@router.get("/api/progress", dependencies=[Depends(require_admin)])
def api_progress(seit: int = 0):
    """Live-Verlauf fuer das Dashboard. `seit` ist die zuletzt gesehene Meldungs-ID,
    damit nur das Neue uebertragen wird statt jedes Mal der ganze Verlauf."""
    return progress.snapshot(seit)


@router.get("/api/stats", dependencies=[Depends(require_admin)])
def api_stats():
    return db.get_stats()


@router.post("/api/reservation/{slug}")
def api_reservation(slug: str, payload: ReservationRequest):
    """Popup auf einer Demo-Site sendet hierhin. Geht als Benachrichtigung an uns (den
    Betreiber), nicht an den Betrieb - siehe send_reservation_notification."""
    lead = db.get_lead_by_slug(slug)
    if lead is None:
        raise HTTPException(status_code=404, detail="unknown demo site")

    # ZUERST speichern. Frueher wurde die Anfrage nur per Mail verschickt - faellt der
    # Versand aus (gesperrtes Postfach, SMTP-Stoerung), war sie unwiederbringlich weg,
    # und der Interessent sah nur eine Fehlermeldung. Dabei ist genau das das
    # wertvollste Signal im ganzen System.
    reservation_id = db.add_reservation(lead["id"], slug, payload)

    try:
        send_reservation_notification(lead["name"], slug, payload)
        db.mark_reservation_notified(reservation_id)
    except Exception:
        # Kein Fehler nach aussen: Die Anfrage IST angekommen, nur die Benachrichtigung
        # nicht. Sie steht im Dashboard und geht nicht verloren.
        logger.exception("Reservierung %s gespeichert, Benachrichtigung fehlgeschlagen", reservation_id)

    return {"status": "ok"}


@router.post("/api/blocklist", dependencies=[Depends(require_admin)])
def api_block(payload: BlockRequest):
    """Widerspruch eintragen. Ab dann wird diese Adresse nicht mehr angeschrieben -
    dauerhaft und nachweisbar, statt nur im Postfach zu stehen."""
    neu = db.block_email(payload.email, payload.grund or "")
    return {"status": "ok", "neu": neu}


@router.delete("/api/blocklist/{email}", dependencies=[Depends(require_admin)])
def api_unblock(email: str):
    db.unblock_email(email)
    return {"status": "ok"}


@router.post("/api/lead/{lead_id}/deal", dependencies=[Depends(require_admin)])
def api_update_deal(lead_id: int, payload: DealUpdate):
    db.update_deal(lead_id, payload.deal_status, payload.deal_price, payload.deal_notes)
    return {"status": "ok"}


@router.get("/api/inbox", dependencies=[Depends(require_admin)])
def api_inbox():
    """Fuer die E-Mails-Ansicht im Dashboard - zeigt die letzten Mails aus dem
    Geschaefts-Postfach per IMAP, falls konfiguriert."""
    if not settings.imap_configured:
        return {"configured": False, "messages": []}
    try:
        return {"configured": True, "messages": fetch_recent_messages(15)}
    except Exception:
        logger.exception("IMAP-Abruf fehlgeschlagen")
        return {"configured": True, "messages": [], "error": "Abruf fehlgeschlagen - App-Passwort pruefen"}


@router.post("/api/lead/{lead_id}/payment-link", dependencies=[Depends(require_admin)])
def api_create_payment_link(lead_id: int, payload: PaymentLinkRequest):
    if not settings.stripe_configured:
        raise HTTPException(status_code=400, detail="Stripe nicht konfiguriert")
    lead = db.get_lead_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    try:
        url = create_payment_link(lead["name"], payload.amount_eur)
    except Exception:
        logger.exception("Stripe Payment Link fehlgeschlagen fuer Lead %s", lead_id)
        raise HTTPException(status_code=502, detail="stripe error")
    db.set_payment_link(lead_id, url)
    return {"url": url}
