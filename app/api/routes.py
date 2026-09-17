import hashlib
import hmac
import logging
import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app import db
from app.uebernahme import uebernehmen
from app.config import settings
from app.models import (AufnahmeRequest, BlockRequest, DealUpdate, PaymentLinkRequest,
                        ReservationRequest)
from app.outreach.mailer import (akquise_mail_fuer_lead, send_aufnahme_notification,
                                send_reservation_notification)
from app.payments import create_payment_link
from app import progress, publisher
from app.pipeline import run_pipeline
from app.sources import overpass

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

router = APIRouter()

# auto_error aus: Fehlt der Basic-Login, darf noch das Anmelde-Cookie greifen.
_basic_auth = HTTPBasic(auto_error=False)

# Der eingebaute Browser der Claude-App zeigt bei Basic-Auth keinen Login-Dialog, nur
# {"detail":"Not authenticated"}. Deshalb zusaetzlich eine Anmeldeseite mit Cookie.
# Der Cookie-Wert ist ein HMAC ueber das Passwort: kein Sitzungsspeicher noetig, und
# ein neues Passwort macht alle alten Cookies automatisch ungueltig.
SITZUNGS_COOKIE = "pw_sitzung"


def _sitzungswert() -> str:
    return hmac.new(settings.dashboard_password.encode(), b"philswebsites-dashboard",
                    hashlib.sha256).hexdigest()


def _zugang_ok(user: str, passwort: str) -> bool:
    user_ok = secrets.compare_digest(user.encode(), settings.dashboard_user.encode())
    pass_ok = secrets.compare_digest(passwort.encode(), settings.dashboard_password.encode())
    return user_ok and pass_ok


def require_admin(request: Request,
                  credentials: HTTPBasicCredentials | None = Depends(_basic_auth)) -> str:
    """Schuetzt Dashboard und Verwaltungs-Endpunkte. Wichtig, weil die App per Tunnel
    oeffentlich erreichbar ist - ohne das koennte jeder mit der Adresse die Firmenkontakte,
    Mail-Entwuerfe und die Kontaktdaten der Betriebe abrufen.

    Faellt bewusst zu (deny), wenn kein Passwort gesetzt ist - lieber ausgesperrt als offen."""
    if not settings.dashboard_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_PASSWORD ist nicht gesetzt - Dashboard aus Sicherheitsgruenden gesperrt.",
        )
    cookie = request.cookies.get(SITZUNGS_COOKIE, "")
    if cookie and secrets.compare_digest(cookie, _sitzungswert()):
        return settings.dashboard_user
    if credentials and _zugang_ok(credentials.username, credentials.password):
        return credentials.username
    # Die Startseite leitet zur Anmeldung um; API-Aufrufe bekommen weiter ein 401.
    if request.method == "GET" and request.url.path == "/":
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Falsche Zugangsdaten",
        headers={"WWW-Authenticate": "Basic"},
    )


_LOGIN_SEITE = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PhilsWebsites – Anmelden</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f4f5;display:grid;place-items:center;
min-height:100vh;margin:0}form{background:#fff;padding:28px;border-radius:12px;width:300px;
box-shadow:0 2px 12px rgba(0,0,0,.08)}h1{font-size:18px;margin:0 0 16px}label{display:block;
font-size:13px;margin:10px 0 4px}input{width:100%;box-sizing:border-box;padding:9px;
border:1px solid #ccc;border-radius:6px;font-size:15px}button{margin-top:18px;width:100%;
padding:10px;border:0;border-radius:6px;background:#111;color:#fff;font-size:15px}
.fehler{color:#b91c1c;font-size:13px;margin:0 0 8px}</style></head><body>
<form method="post" action="/login"><h1>PhilsWebsites</h1>{FEHLER}
<label for="u">Benutzer</label><input id="u" name="user" autocomplete="username" required>
<label for="p">Passwort</label><input id="p" name="passwort" type="password"
autocomplete="current-password" required><button>Anmelden</button></form></body></html>"""


@router.get("/login", response_class=HTMLResponse)
def login_seite():
    return _LOGIN_SEITE.replace("{FEHLER}", "")


@router.post("/login")
async def login(request: Request):
    formular = await request.form()
    if not settings.dashboard_password or not _zugang_ok(str(formular.get("user", "")),
                                                          str(formular.get("passwort", ""))):
        return HTMLResponse(_LOGIN_SEITE.replace(
            "{FEHLER}", '<p class="fehler">Benutzer oder Passwort falsch.</p>'), status_code=401)
    antwort = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    antwort.set_cookie(SITZUNGS_COOKIE, _sitzungswert(), max_age=60 * 60 * 24 * 90,
                       httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return antwort


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
            "deals_active": sum(1 for l in leads if l["deal_status"] not in ("offen", "kontaktiert", "abgelehnt")),
            "stripe_configured": settings.stripe_configured,
            "source_health": overpass.source_health(),
            "publish_health": publisher.publish_health(),
            "aufnahmen": db.get_aufnahmen(),
            "briefkandidaten": db.get_briefkandidaten(),
            "status_zaehler": db.zaehle_status(),
            "blocklist": db.get_blocklist(),
            "reservations": db.get_reservations(),
            # Der komplette Text, wie er beim Betrieb ankaeme - nicht nur der von der KI
            # geschriebene Teil. Sonst sieht man hier etwas anderes, als rausgeht.
            "mail_texte": {l["id"]: akquise_mail_fuer_lead(l) for l in leads if l["email_body"]},
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


@router.post("/api/aufnahme/{slug}")
def api_aufnahme(slug: str, payload: AufnahmeRequest):
    """Der Betrieb liefert nach der Zusage seine echten Inhalte. Oeffentlich erreichbar
    wie das Anfrageformular - der Kunde hat kein Passwort fuer das Dashboard."""
    lead = db.get_lead_by_slug(slug)
    if lead is None:
        raise HTTPException(status_code=404, detail="unknown demo site")

    felder = payload.model_dump()
    # Erst speichern, dann benachrichtigen - siehe Reservierungen: eine Zulieferung des
    # Kunden darf nicht an einer Mailstoerung verloren gehen.
    aufnahme_id = db.add_aufnahme(lead["id"], slug, felder)
    try:
        send_aufnahme_notification(lead["name"], slug, felder)
        db.mark_aufnahme_notified(aufnahme_id)
    except Exception:
        logger.exception("Aufnahmebogen %s gespeichert, Benachrichtigung fehlgeschlagen", aufnahme_id)
    return {"status": "ok"}


@router.post("/api/aufnahme/{aufnahme_id}/uebernehmen", dependencies=[Depends(require_admin)])
def api_aufnahme_uebernehmen(aufnahme_id: int):
    """Angaben in die Seite einarbeiten und sie neu bauen - ohne KI, sofort."""
    try:
        slug = uebernehmen(aufnahme_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Uebernahme von Aufnahmebogen %s fehlgeschlagen", aufnahme_id)
        raise HTTPException(status_code=500, detail="Uebernahme fehlgeschlagen")
    return {"status": "ok", "slug": slug}


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
