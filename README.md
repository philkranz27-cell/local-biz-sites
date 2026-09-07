# Local Biz Sites

Findet automatisch lokale Betriebe (Restaurants, Friseure, Bäckereien, Cafés, Bars,
Fitnessstudios, Blumenläden) **ohne eigene Website, bei denen aber eine Kontakt-Mailadresse
öffentlich bekannt ist**, baut ihnen eine individuelle Demo-Website, veröffentlicht die
dauerhaft erreichbar und verschickt eine kurze Akquise-Mail mit Link dorthin. Alle anderen
Betriebe werden ignoriert — kein Scraping fremder Websites, keine Ansprache ohne bekannten
Kontakt. Läuft unbeaufsichtigt als Scheduler-Job.

Alles im Projekt ist bewusst kostenlos: OpenStreetMap für die Suche, Groq für die Texte,
Pexels für Fotos, Gmail für den Versand, GitHub Pages für das Hosting.

## Wichtiger rechtlicher Hinweis — bitte lesen

Automatisierte Werbe-E-Mails an Geschäfte, mit denen vorher **keine Geschäftsbeziehung**
bestand, fallen in Deutschland unter **§7 UWG** (unzumutbare Belästigung) — das gilt
grundsätzlich auch für B2B-Mails. In der Praxis wird das selten verfolgt, aber es ist ein
bekannter Abmahn-Hebel. Dieses Projekt automatisiert den Versand bewusst voll, enthält aber
ein paar Dinge, die das Risiko reduzieren:

- Jede Mail trägt eine vollständige Absenderkennzeichnung (`SENDER_IMPRESSUM`), den Hinweis,
  dass eine kurze Antwort reicht, damit sich niemand mehr meldet, und die Auskunft, woher
  die Daten stammen (Art. 14 DSGVO — die Adressaten sind oft Einzelunternehmer, ihre
  Kontaktdaten sind damit personenbezogene Daten).
- Eine **Sperrliste** (`blocklist`-Tabelle, Pflege im Dashboard) hält Widersprüche
  dauerhaft fest. Der Versand prüft sie vor jeder Mail. Ein Widerspruch muss nachweisbar
  beachtet werden — ihn nur im Postfach gelesen zu haben reicht nicht.
- Ein täglicher Deckel (`MAX_EMAILS_PER_DAY`) verhindert Massenversand. **Steht der Wert
  auf 0, geht gar nichts raus** — der sichere Ausgangszustand.
- Die Demo-Sites tragen im Footer sichtbar "unverbindlicher Demo-Entwurf, keine offizielle
  Website des Betriebs" und stehen auf `noindex`, tauchen also nicht bei Google neben der
  echten Seite des Betriebs auf.

Das eigentliche Risiko trägt der Betreiber. Diese Doku ist keine Rechtsberatung.

## Wie die Pipeline funktioniert

Ein Durchlauf (`app/pipeline.py:run_pipeline`) arbeitet in dieser Reihenfolge:

**1. Websites bauen** (`app/sitegen/`) — für Leads im Status `email_found`, 20 je Durchlauf.
Das Groq-Modell schreibt in zwei Durchgängen individuelle Texte (Tagline, Headline, About,
3 Highlights, 4–6 Leistungen, passender Call-to-Action) und einen englischen Bildsuchbegriff;
dazu kommen Fotos von Pexels. Layout und Akzentfarbe werden deterministisch aus der OSM-ID
abgeleitet — je Kategorie 2 passende aus 4 grundverschiedenen Vorlagen × 6 Farben, zwei
Betriebe sehen also so gut wie nie gleich aus. Öffnungszeiten werden aus der OSM-Rohsyntax
in lesbares Deutsch übersetzt (`app/sitegen/opening_hours.py`).

**2. Veröffentlichen** (`app/publisher.py`) — spiegelt die Seiten nach `docs/` und lädt sie
hoch, wenn ein `GITHUB_TOKEN` hinterlegt ist. Läuft **vor** dem Mailversand, damit nie eine
Mail mit einem Link auf eine noch nicht veröffentlichte Seite rausgeht.

**3. Mails entwerfen** (`app/llm.py`) — kurzer, persönlicher Text ohne Preisnennung, aber
mit dem Angebot, über Konditionen zu sprechen. Anrede, Grußformel, Impressum und
Widerspruchshinweis setzt `app/outreach/mailer.py` beim Versand dazu, nicht das Sprachmodell.

**4. Mails versenden** — bis zum Tagesdeckel.

**5. Neue Leads suchen** (`app/sources/overpass.py`) — pro Durchlauf nur ein Ausschnitt der
Stadt/Kategorie-Liste (`FIND_COMBOS_PER_RUN`, Standard 12), die Position steht in
`data/find_cursor.txt` und überlebt Neustarts. **Warum nicht alles auf einmal:** Ein voller
Durchlauf über 56 Städte × 7 Kategorien sind 392 Abfragen und dauert rund 9 Stunden. Stünde
die Suche vorne, käme der Rest nie an die Reihe.

**Die Filterung** (`phase_find_leads`): Hat der Betrieb ein `website`-Tag → ausgeschlossen,
unabhängig von der Qualität dieser Website; es wird nie eine fremde Website besucht. Kein
`website`-Tag, aber auch kein `contact:email`/`email` in OSM → ebenfalls ausgeschlossen.
Nur die Schnittmenge geht weiter. In der Praxis sind das rund 1 % der gefundenen Betriebe.

Der Zustand jedes Leads steht in SQLite (`leads`-Tabelle). Nichts wird zweimal
angeschrieben, die OSM-ID (`place_id`, z.B. `node/12345`) ist eindeutig.

## Zwei Adressen, und warum

| Variable | Zeigt auf | Wofür |
|---|---|---|
| `BASE_URL` | GitHub Pages | Die Links in den Mails. Bleibt erreichbar, auch wenn der Rechner aus ist. |
| `API_BASE_URL` | Diese Anwendung (Tailscale Funnel) | Reservierungs-Formular und Dashboard. Läuft nur, solange der Rechner läuft. |

Die Demo-Seiten sind statisch und liegen auf GitHub Pages. Nur das Reservierungs-Popup
braucht einen laufenden Server und ruft deshalb `API_BASE_URL` auf — dafür ist in
`app/main.py` CORS eng auf diese beiden Adressen begrenzt. Schlägt der Aufruf fehl, sagt
das Formular das ehrlich und nennt die Telefonnummer des Betriebs, statt einen Erfolg
vorzutäuschen.

## Einrichten

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Dann `.env` ausfüllen. Die Zugänge:

| Dienst | Kostenlos? | Wo |
|---|---|---|
| Groq (Texte) | ja, dauerhaft | [console.groq.com/keys](https://console.groq.com/keys) |
| Pexels (Fotos, optional) | ja, dauerhaft | [pexels.com/api](https://www.pexels.com/api/) |
| Gmail-App-Passwort (Versand + Posteingang) | ja | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| Stripe (Zahlungslinks, optional) | ja | [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) |
| GitHub-Token (automatisches Veröffentlichen, optional) | ja | [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens), Contents: Read and write |

**Beim Mailversand muss die Absenderdomain zum Versandserver passen.** Eine
gmail.com-Adresse über einen fremden Dienst wie Brevo zu verschicken funktioniert technisch,
sieht für den Empfänger aber aus wie eine gefälschte Absenderadresse — gmail.com erlaubt per
SPF nur Googles eigene Server. Die Mails landen dann zuverlässig im Spam. Deshalb:
`smtp.gmail.com` mit App-Passwort, solange der Absender eine Gmail-Adresse ist. Mit eigener
Domain ist ein Dienst wie Brevo die bessere Wahl (dort SPF und DKIM für die Domain
eintragen). Prüfen lässt sich das kostenlos über [mail-tester.com](https://www.mail-tester.com).

## Starten

```bash
start-dashboard.bat
```

Startet den Server auf `127.0.0.1:8123` in einer Neustart-Schleife und schreibt nach
`data/server.log`. Für den Autostart bei der Anmeldung liegt `start-dashboard-hidden.vbs`
im Autostart-Ordner von Windows (`shell:startup`) und startet dasselbe ohne Fenster.

Das Dashboard ist durch HTTP-Basic-Auth geschützt (`DASHBOARD_USER`, `DASHBOARD_PASSWORD`).
**Ohne gesetztes Passwort ist es komplett gesperrt** — bewusst so, weil die Anwendung per
Tunnel öffentlich erreichbar ist und sonst jeder mit der Adresse die Firmenkontakte,
Mail-Entwürfe und den Posteingang abrufen könnte. Öffentlich bleiben nur `/sites/`,
`/api/reservation/` und `/healthz`.

**Öffentlich erreichbar** wird das Ganze über Tailscale Funnel:

```bash
tailscale funnel --bg 8123
```

## Dashboard

Eine Mindmap mit drei Bereichen: **Neue Betriebe** (alle Leads mit Status und Link zur
Demo), **E-Mails** (Entwürfe und der Posteingang per IMAP, beides je Mail aufklappbar) und
**Zahlungen** (Verhandlungsstand je Lead, Stripe-Zahlungslink erzeugen).

Über der Mindmap stehen zwei Statuszeilen: ob die Lead-Suche läuft und ob die
Veröffentlichung durchkommt. Beide gab es anfangs nicht — und genau deshalb blieb einmal
ein stundenlanger Ausfall der Datenquelle unbemerkt. Ein Ausfall, der nur im Log steht, ist
ein Ausfall, den niemand bemerkt.

## Veröffentlichen ohne Token

Ist kein `GITHUB_TOKEN` hinterlegt, passiert Schritt 2 der Pipeline nicht. Dann von Hand:

```bash
.venv\Scripts\python.exe publish.py
git add docs && git commit -m "Demo-Seiten aktualisiert" && git push
```

GitHub Pages muss einmalig eingeschaltet werden: Repository → Settings → Pages → Source
"Deploy from a branch", Branch `main`, Ordner `/docs`.

## Konfiguration (`.env`)

- `SEARCH_CITIES` — Städtenamen müssen **exakt** dem OSM-Verwaltungsgrenzen-Namen
  entsprechen, mit Umlauten (`München`, nicht `Muenchen`), sonst liefert die Suche nichts.
- `SEARCH_CATEGORIES` — `restaurant`, `hair_salon`, `bakery`, `cafe`, `bar`, `gym`,
  `florist`. Neue Kategorie → Eintrag in `CATEGORY_OSM_TAGS` in `app/sources/overpass.py`.
- `MAX_LEADS_PER_RUN` (200) — Treffer je Abfrage. Overpass kennt keinen Offset und liefert
  immer dieselben ersten N Treffer; mit einem kleinen Wert ist die Quelle nach einem
  Durchlauf durch alle Städte erschöpft. 200 kostet kaum mehr Zeit als 20, 1000 läuft in
  den Timeout.
- `MAX_EMAILS_PER_DAY` — harter Deckel pro Kalendertag. 0 = kein Versand.
- `SENDER_IMPRESSUM` — erscheint unter jeder Mail; daraus wird auch der Name für die
  Grußformel gezogen.
- `PEXELS_API_KEY` — optional, ohne Key entstehen Seiten ohne Fotos.
- `POLL_INTERVAL_PIPELINE_SEC` (60) — Mindestabstand zwischen Durchläufen. APScheduler
  lässt keine Überlappung zu, der nächste startet also direkt nach dem vorherigen.
- `PUBLISH_MIN_INTERVAL_MIN` (60) — frühestens so oft wird hochgeladen, sonst entstünde
  alle paar Minuten ein Commit.

## Bekannte Einschränkungen

- **Der Rechner läuft nicht durchgehend.** Schläft der Laptop, arbeitet die Pipeline nicht.
  Der Autostart fängt Neustarts ab, den Ruhezustand nicht — das ist eine Einstellung im
  Betriebssystem, keine im Programm.
- **Groq deckelt das Tageskontingent** auf 200.000 Token, das reicht für ungefähr 60–70
  neue Websites pro Tag. Danach schlagen die Versuche mit `429` fehl, die Leads bleiben in
  der Warteschlange und kommen am Folgetag dran.
- **Overpass ist wechselhaft.** Die Suche kennt drei Server und wechselt bei Ausfall
  (`OVERPASS_ENDPOINTS`), trotzdem scheitert unter Last rund die Hälfte der Abfragen.
  `overpass.osm.ch` ist bewusst **nicht** in der Liste: ein reiner Schweiz-Auszug, der für
  deutsche Städte stillschweigend 0 Treffer liefert — schlimmer als ein ehrlicher Ausfall.
- **Die strikte Filterung ist konservativ** und lässt nur ~1 % durch. Ausgeglichen wird das
  über die große Städteliste und den Dauerbetrieb, nicht über Scraping fremder Seiten.
- OSM liefert keine Bewertungen, Speisekarten oder echten Fotos. Die Texte sind deshalb
  bewusst allgemein gehalten, und die Pexels-Bilder sind als Symbolbilder gekennzeichnet.
- Ein Lead, dessen Verarbeitung wiederholt fehlschlägt, zählt `error_count` hoch, bleibt
  aber im Status stehen und wird weiter versucht.
