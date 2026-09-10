import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db
from app.api.routes import router
from app.config import settings
from app.scheduler import create_scheduler

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Der Server laeuft unsichtbar im Hintergrund. Ohne Logdatei war jede Ausnahme verloren -
# so geschehen am 10.09.: Ein Seitentext scheiterte in der Pipeline nach 7 Sekunden, und
# der Grund liess sich nicht mehr feststellen.
_LOG_DATEI = Path(settings.db_path).parent / "logs" / "server.log"
_LOG_DATEI.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(_LOG_DATEI, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ],
)

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


app = FastAPI(title="PhilsWebsites", lifespan=lifespan)

# Die Demo-Seiten liegen jetzt statisch auf GitHub Pages, das Reservierungs-Formular
# ruft von dort aus diese Anwendung auf - also eine andere Herkunft. Ohne CORS wuerde
# der Browser die Anfrage blockieren. Bewusst eng: nur die Seiten-Adresse, nur POST,
# und nur fuer den Reservierungs-Endpunkt sinnvoll (das Dashboard schuetzt Basic-Auth,
# die hier nicht mitgeschickt wird - allow_credentials bleibt aus).
# Der Browser schickt als Origin nur Schema + Host, nie den Pfad. Aus
# ".../philkranz27-cell.github.io/local-biz-sites" muss also
# "https://philkranz27-cell.github.io" werden, sonst passt der Vergleich nie.
def _origin(url: str) -> str:
    teile = urlsplit(url)
    return f"{teile.scheme}://{teile.netloc}" if teile.scheme and teile.netloc else ""


_allowed_origins = sorted({o for o in (_origin(settings.base_url), _origin(settings.api_base)) if o})
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/sites", StaticFiles(directory=str(SITES_DIR), html=True), name="sites")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
app.include_router(router)
