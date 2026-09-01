# Local Biz Sites

Findet automatisch lokale Betriebe (Restaurants, Friseure, Bäckereien, Cafés, ...) **ohne
eigene Website, bei denen aber eine Kontakt-Mailadresse öffentlich bekannt ist**, baut
ihnen automatisch eine kostenlose Demo-Website (KI-Texte + Template, live erreichbar) und
verschickt automatisch eine kurze Akquise-Mail mit Link zur Demo. Alle anderen Betriebe
(mit vorhandener Website, oder ohne auffindbare Mail) werden komplett ignoriert — kein
Scraping fremder Websites, keine Ansprache ohne bekannten Kontakt. Läuft komplett
unbeaufsichtigt als Scheduler-Job.

## Wichtiger rechtlicher Hinweis — bitte lesen

Automatisierte Werbe-E-Mails an Geschäfte, mit denen vorher **keine Geschäftsbeziehung**
bestand, fallen in Deutschland unter **§7 UWG** (unzumutbare Belästigung) — das gilt
grundsätzlich auch für B2B-Mails, nicht nur an Privatpersonen. In der Praxis wird das
selten verfolgt, aber es ist ein bekannter Abmahn-Hebel (spezialisierte Kanzleien/
Mitbewerber). Dieses Projekt automatisiert den Versand bewusst voll (deine Entscheidung),
enthält aber ein paar Dinge, die das Risiko zumindest reduzieren:

- Jede Mail enthält eine vollständige Absenderkennzeichnung (`SENDER_IMPRESSUM` in `.env`)
  und einen klaren Hinweis, dass eine kurze Antwort reicht, damit sich niemand mehr meldet.
- Ein täglicher Versand-Deckel (`MAX_EMAILS_PER_DAY`) verhindert Massenversand.
- Die generierten Demo-Sites tragen im Footer deutlich sichtbar "unverbindlicher
  Demo-Entwurf, keine offizielle Website des Betriebs" — damit niemand denkt, du hättest
  dich als der Betrieb selbst ausgegeben.

Trotzdem: das eigentliche Risiko trägst du als Betreiber. Bei ernsthaftem Volumen lohnt
sich eine kurze Rechtsberatung, bevor die Stückzahl signifikant wird. Diese Doku ist keine
Rechtsberatung.

## Wie die Pipeline funktioniert

1. **Leads finden** (`app/sources/overpass.py`): OpenStreetMap (Overpass API) pro
   Stadt × Kategorie aus `SEARCH_CITIES` / `SEARCH_CATEGORIES`. Komplett kostenlos, kein
   Account, kein Key — dafür inkonsistentere Daten als bei einem kommerziellen Anbieter
   (kein Rating, Öffnungszeiten/Website nicht bei jedem Eintrag gepflegt).
2. **Filtern** (`app/pipeline.py:phase_find_leads`): hat der Betrieb ein `website`-Tag →
   sofort ausgeschlossen (`excluded_has_website`), unabhängig von der Qualität dieser
   Website — es wird nie eine fremde Website besucht oder gescraped. Kein `website`-Tag,
   aber auch kein direkt in OSM getaggtes `contact:email`/`email` → ebenfalls ausgeschlossen
   (`excluded_no_email`), da kein automatisierter Kontaktweg vorgesehen ist. Nur die
   Schnittmenge — keine Website, aber bekannte Mail — geht weiter (`email_found`).
   Ausgeschlossene Leads bleiben nur intern in der DB (Dedup über `place_id`), tauchen im
   Dashboard nicht auf.
3. **Demo-Website generieren** (`app/sitegen/`): Groq-LLM schreibt individuelle Texte
   (Tagline, Headline, About, 3 Highlights, 4-6 Leistungen mit Beschreibung, passender
   CTA — keine erfundenen Fakten, keine Fake-Testimonials) und einen englischen
   Bildsuchbegriff. Ein zu Name/Kategorie/Ort passendes Stockfoto (Hero + bis zu 3
   Galeriebilder) kommt von der Pexels-API. Layout und Akzentfarbe werden deterministisch
   aus der OSM-ID abgeleitet, je Kategorie aus 2 passenden von 4 grundverschiedenen
   Design-Vorlagen (`app/sitegen/templates/*.html.j2`: clean-modern, warm-editorial,
   dunkel-bold, elegant-boutique) × 6 Akzentfarben — zwei Betriebe sehen also so gut wie
   nie identisch aus. Ergebnis liegt unter `data/sites/{slug}/index.html`, live erreichbar
   unter `/sites/{slug}/`.
4. **Mail entwerfen und senden** (`app/llm.py`, `app/outreach/`): Groq-LLM schreibt eine
   kurze, persönliche Mail mit Link zur Demo, Versand per SMTP.

Der komplette Zustand jedes Leads steht in SQLite (`leads`-Tabelle, Status-Spalte) — nichts
wird zweimal angeschrieben, `place_id` (die OSM-ID, z.B. `node/12345`) ist eindeutig.

## Was hier bewusst NICHT drin ist (Phase 2)

- **Bezahlung/Checkout**: wenn ein Betrieb antwortet und kaufen will, läuft das aktuell
  manuell (du verhandelst per Mail/Telefon). Ein Stripe-Payment-Link + automatisches
  Deployment auf eine eigene Domain lässt sich später ergänzen, sobald der erste Verkauf
  zeigt, dass die Ansprache funktioniert.
- **Antwort-Erkennung**: Antworten landen aktuell in deinem normalen Postfach (`FROM_EMAIL`),
  nicht automatisch im Dashboard. Für den Start reicht das.
- **Follow-up-Sequenzen** (2. Anschreiben nach ein paar Tagen ohne Antwort) — bewusst nicht
  in v1, um das Abmahnrisiko nicht durch wiederholte Kontaktaufnahme zu erhöhen.

## 1. API-Zugänge besorgen

Alle drei komplett kostenlos, keine Kreditkarte nötig (die Lead-Suche selbst über
OpenStreetMap braucht gar keinen Account). Pexels ist optional — ohne Key entstehen die
Demo-Sites trotzdem, nur ohne Fotos.

| Dienst | Kostenlos? | Wo bekommen |
|---|---|---|
| Groq (Website-Texte + E-Mail-Entwürfe) | Ja, dauerhaft, keine Kreditkarte | [console.groq.com/keys](https://console.groq.com/keys) |
| Pexels (Stockfotos, optional) | Ja, dauerhaft, keine Kreditkarte | [pexels.com/api](https://www.pexels.com/api/) → "Get Started", Key wird sofort angezeigt |
| SMTP-Versand | Ja, z.B. Brevo 300 Mails/Tag gratis | [app.brevo.com/settings/keys/smtp](https://app.brevo.com/settings/keys/smtp) (oder ein Gmail-App-Passwort) |

## 2. Lokal einrichten und testen

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env      # dann die Keys eintragen
uvicorn app.main:app --reload
```

Dashboard unter `http://localhost:8000` öffnen — dort ein "Pipeline jetzt starten"-Button
für einen manuellen Testlauf, statt auf das Scheduler-Intervall (`POLL_INTERVAL_PIPELINE_SEC`,
Standard 6 Stunden) zu warten. `/healthz` sollte `{"status":"ok"}` liefern.

**Empfehlung für den ersten Test:** `MAX_EMAILS_PER_DAY=0` setzen und dir im Dashboard erst
ein paar generierte Demo-Sites + E-Mail-Entwürfe ansehen (Spalte "Demo" verlinkt die Seite),
bevor der erste echte Versand läuft.

## 3. Deployment auf einen 24/7-Server

```bash
docker build -t local-biz-sites .
docker run -d --env-file .env -v %cd%/data:/app/data -p 8000:8000 --restart unless-stopped local-biz-sites
```

Auf Railway/Render: Repo verbinden, `Dockerfile` wird automatisch erkannt, alle Variablen
aus `.env.example` als Umgebungsvariablen eintragen, **persistenten Volume auf `/app/data`
mounten** (sonst gehen Demo-Sites und die "schon kontaktiert"-Historie bei jedem Redeploy
verloren).

## Konfiguration (`.env`)

- `SEARCH_CITIES`: Komma-Liste, Städtenamen müssen exakt dem OSM-Verwaltungsgrenzen-Namen
  entsprechen (mit Umlauten, z.B. `München` nicht `Muenchen`), sonst liefert die Suche für
  diese Stadt nichts.
- `SEARCH_CATEGORIES`: Komma-Liste aus `restaurant`, `hair_salon`, `bakery`, `cafe`, `bar`,
  `gym`, `florist`. Neue Kategorie hinzufügen → Eintrag in `CATEGORY_OSM_TAGS` in
  `app/sources/overpass.py` (Mapping auf den passenden OSM-Tag, siehe
  [OSM Map Features](https://wiki.openstreetmap.org/wiki/Map_features)).
- `MAX_LEADS_PER_RUN`: wie viele Treffer pro Stadt×Kategorie und Durchlauf maximal
  übernommen werden.
- `MAX_EMAILS_PER_DAY`: harter Versand-Deckel pro Kalendertag.
- `SENDER_IMPRESSUM`: erscheint unter jeder Mail — vollständiger Name/Anschrift/Kontakt.
- `PEXELS_API_KEY`: optional. Ohne Key entstehen Demo-Sites ohne Fotos (Templates fallen
  auf eine schlichte Farbfläche statt Hero-Bild zurück) — sieht ordentlich, aber deutlich
  weniger hochwertig aus. Für den in dieser Session gewünschten "sehr guten,
  einzigartigen" Eindruck ist der Key empfehlenswert.
- `POLL_INTERVAL_PIPELINE_SEC`: Mindestabstand zwischen Durchläufen. Bei der mitgelieferten
  Städteliste (~55 Städte × 7 Kategorien = ~385 Kombinationen) dauert ein voller Durchlauf
  deutlich länger als der Standardwert (60s) — APScheduler lässt keine Überlappung zu, der
  nächste Durchlauf startet also direkt nach Ende des vorherigen. Effekt: die Pipeline sucht
  praktisch durchgehend, nicht nur alle paar Stunden.

## Bekannte Einschränkungen

- Die strikte Filterung (nur OSM-eigene E-Mail-Tags, kein Scraping) ist bewusst konservativ
  gewählt — dadurch ist der qualifizierte Lead-Pool pro Kombination klein (in ersten Tests
  ca. 1% der gefundenen Betriebe). Ausgeglichen wird das über die große Städteliste und den
  durchgehenden Betrieb, nicht über Scraping fremder Websites.
- **Dauerbetrieb heißt Dauerlast auf einer kostenlosen, öffentlichen Infrastruktur**
  (Overpass API) — bei ~385 Kombinationen pro Durchlauf und sofortigem Neustart können das
  schnell mehrere zehntausend Anfragen pro Tag werden. Der eingebaute Backoff bei
  `429 Too Many Requests` (siehe `overpass.py`) verhindert einen Absturz, aber bei
  andauerndem Dauerbetrieb ist eine längere IP-Sperre durch den Betreiber der Overpass-
  Instanz realistisch. Falls das passiert: `POLL_INTERVAL_PIPELINE_SEC` deutlich erhöhen
  oder auf eine eigene Overpass-Instanz/einen bezahlten Dienst wechseln.
- OpenStreetMap liefert keine Bewertungen/Speisekarten/Fotos, und Adress-/Öffnungszeiten-
  Tags sind nicht bei jedem Eintrag gepflegt — die generierten Texte sind deshalb bewusst
  allgemein gehalten, um keine falschen Fakten zu erfinden.
- Kein Retry-Backoff wie im Krypto-Monitor-Projekt — ein Lead, der 3x fehlschlägt
  (`error_count`), wird stillschweigend aus den weiteren Läufen ausgeschlossen.
- Die Pexels-Fotos sind thematisch passende Stimmungsbilder, keine echten Fotos des
  jeweiligen Betriebs — deshalb steht auf jeder Demo-Site ein Bildnachweis mit genau
  diesem Hinweis im Footer, um niemanden in die Irre zu führen.
