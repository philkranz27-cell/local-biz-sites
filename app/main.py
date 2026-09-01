import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import db
from app.api.routes import router
from app.config import settings
from app.scheduler import create_scheduler

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SITES_DIR = PROJECT_ROOT / "data" / "sites"
SITES_DIR.mkdir(parents=True, exist_ok=True)

scheduler = create_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.start()
    logging.getLogger(__name__).info("Scheduler started with jobs: %s", [j.id for j in scheduler.get_jobs()])
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Local Biz Sites", lifespan=lifespan)
app.mount("/sites", StaticFiles(directory=str(SITES_DIR), html=True), name="sites")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
app.include_router(router)
