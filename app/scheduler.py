import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.pipeline import run_pipeline
from app.sicherung import sichern

logger = logging.getLogger(__name__)


def _pipeline_job() -> None:
    try:
        run_pipeline()
    except Exception:
        logger.exception("Pipeline-Durchlauf fehlgeschlagen")


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
    # Nachts um vier ist die Pipeline zwischen zwei Durchlaeufen am ruhigsten.
    scheduler.add_job(
        _sicherungs_job,
        "cron",
        hour=4,
        minute=0,
        id="sicherung",
    )
    return scheduler
