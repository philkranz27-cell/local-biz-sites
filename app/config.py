from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # Absoluter Pfad, damit .env unabhaengig vom Arbeitsverzeichnis gefunden wird, egal
    # von wo aus uvicorn gestartet wird.
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    groq_api_key: str = ""
    analysis_model: str = "openai/gpt-oss-120b"

    pexels_api_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    from_name: str = "Website-Angebot"
    sender_impressum: str = ""

    # Posteingang im Dashboard (E-Mails-Ansicht) - IMAP mit App-Passwort, kein OAuth/Google-
    # Cloud-Projekt noetig. Anleitung: https://myaccount.google.com/apppasswords (braucht
    # 2-Faktor-Auth auf dem Google-Konto).
    imap_host: str = "imap.gmail.com"
    imap_user: str = ""
    imap_password: str = ""

    # Stripe Payment Links fuer die Zahlungen-Ansicht - kostenloser Account, Test-Keys
    # funktionieren sofort ohne Geschaeftsverifizierung (fuer echte Auszahlungen muss der
    # Account spaeter bei Stripe verifiziert werden).
    stripe_secret_key: str = ""

    # Zugangsschutz fuer Dashboard + Verwaltungs-Endpunkte. Zwingend noetig, sobald die App
    # ueber einen Tunnel oeffentlich erreichbar ist - sonst kaeme jeder mit der Adresse an
    # Firmenkontakte, Mail-Entwuerfe und den Posteingang. Leeres Passwort = Dashboard
    # gesperrt (fail closed), die oeffentlichen Demo-Seiten bleiben davon unberuehrt.
    dashboard_user: str = "admin"
    dashboard_password: str = ""

    search_cities: str = (
        "Berlin,Hamburg,München,Köln,Frankfurt am Main,Stuttgart,Düsseldorf,Leipzig,"
        "Dortmund,Essen,Bremen,Dresden,Hannover,Nürnberg,Duisburg,Bochum,Wuppertal,"
        "Bielefeld,Bonn,Münster,Karlsruhe,Mannheim,Augsburg,Wiesbaden,Mönchengladbach,"
        "Braunschweig,Chemnitz,Kiel,Aachen,Magdeburg,Freiburg im Breisgau,Krefeld,Lübeck,"
        "Erfurt,Mainz,Rostock,Kassel,Potsdam,Saarbrücken,Oldenburg,Osnabrück,Leverkusen,"
        "Heidelberg,Darmstadt,Regensburg,Paderborn,Ingolstadt,Würzburg,Wolfsburg,Trier,"
        "Reutlingen,Koblenz,Jena,Erlangen,Siegen,Hildesheim"
    )
    search_categories: str = "restaurant,hair_salon,bakery,cafe,bar,gym,florist"
    # Obergrenze der Treffer je Stadt+Kategorie-Abfrage. Wichtig: Overpass liefert ohne
    # Offset immer dieselben ersten N Treffer - mit 20 war die Quelle nach einem Durchlauf
    # durch alle Staedte erschoepft ("20 Treffer, 0 neu"). 200 kostet kaum mehr Zeit
    # (15s statt 10s), 1000 laeuft in den Timeout. Begrenzt nur die Suche; wie viele
    # Websites/Mails daraus entstehen, deckeln die Phasen unten getrennt.
    max_leads_per_run: int = 200
    max_emails_per_day: int = 15

    db_path: str = "data/app.db"
    port: int = 8000
    base_url: str = "http://localhost:8000"

    # Mindestabstand zwischen Durchlaeufen. Ein voller Durchlauf ueber die ganze
    # Staedte-/Kategorienliste dauert bei dieser Listengroesse laenger als dieser Wert -
    # APScheduler laesst per Default keine Ueberlappung zu (max_instances=1), der naechste
    # Durchlauf startet also in der Praxis direkt nach Ende des vorherigen. Effekt: die
    # Pipeline sucht quasi durchgehend.
    poll_interval_pipeline_sec: int = 60

    log_level: str = "INFO"

    @property
    def city_list(self) -> list[str]:
        return [c.strip() for c in self.search_cities.split(",") if c.strip()]

    @property
    def category_list(self) -> list[str]:
        return [c.strip() for c in self.search_categories.split(",") if c.strip()]

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def pexels_configured(self) -> bool:
        return bool(self.pexels_api_key)

    @property
    def mail_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.from_email)

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_user and self.imap_password)

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key)


settings = Settings()
