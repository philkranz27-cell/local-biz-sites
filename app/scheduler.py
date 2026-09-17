import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.pipeline import phase_send_emails, run_pipeline
from app.sicherung import sichern

logger = logging.getLogger(__name__)


def _pipeline_job() -> None:
    try:
        run_pipeline()
    except Exception:
        logger.exception("Pipeline-Durchlauf fehlgeschlagen")


def _versand_job() -> None:
    """Eigener Takt fuer den Versand.

    Ein Pipeline-Durchlauf dauert von Minuten bis Stunden - Seitentexte, Veroeffentlichung
    und die Suche ueber 805 Stadt-Kategorie-Paare. Solange er laeuft, faellt jeder weitere
    Durchlauf aus ("maximum number of running instances reached"), und damit lag auch der
    Versand still: drei Mails, dann stundenlang nichts. Als eigener Job haengt er nicht
    mehr an der Pipeline.
    """
    try:
        phase_send_emails()
    except Exception:
        logger.exception("Mailversand fehlgeschlagen")


def _sicherungs_job() -> None:
    try:
        sichern()
    except Exception:
        logger.exception("Sicherung der Datenbank fehlgeschlagen")


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _pipeline_job,
        "interval",
        seconds=settings.poll_interval_pipeline_sec,
        id="pipeline",
        next_run_time=datetime.now(),
    )
    # Jede Minute drei Mails, unabhaengig davon, was die Pipeline gerade tut.
    scheduler.add_job(
        _versand_job,
        "interval",
        seconds=60,
        id="versand",
        next_run_time=datetime.now(),
    )
    # Nachts um vier ist die Pipeline zwischen zwei Durchlaeufen am ruhigsten.
    scheduler.add_job(
        _sicherungs_job,
        "cron",
        hour=4,
        minute=0,
        id="sicherung",
    )
    return scheduler
