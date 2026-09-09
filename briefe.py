"""Erzeugt Anschreiben zum Ausdrucken - ein Brief je Betrieb, mit QR-Code zur Demo-Seite.

Warum Briefe: Werbe-E-Mails an Betriebe ohne vorherige Einwilligung fallen unter
§7 UWG und sind angreifbar (Abmahnung). Briefwerbung an Gewerbetreibende faellt nicht
darunter. Der Weg kostet Porto, ist dafuer rechtlich sauber - und unabhaengig von
Postfaechern, Spamfiltern und gesperrten Konten.

Ergebnis ist eine einzige HTML-Datei mit Seitenumbruch je Brief. Im Browser oeffnen,
Strg+P, "Als PDF speichern" - oder direkt drucken. Bewusst kein PDF-Erzeuger als
Abhaengigkeit: So kann man vor dem Druck noch alles durchsehen und einzelne Seiten
abwaehlen.

Aufruf:  .venv/Scripts/python.exe briefe.py [anzahl]
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
import pathlib
from pathlib import Path

import segno

from app import db
from app.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent
ZIEL = PROJECT_ROOT / "data" / "briefe.html"

# Vollstaendige deutsche Anschrift: Hausnummer vor dem Komma, fuenfstellige PLZ dahinter.
PLZ = re.compile(r"(?<!\d)\d{5}(?!\d)")
HAUSNUMMER = re.compile(r"\d+\s*[a-zA-Z]?\s*,")

MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember")


def _qr_svg(url: str) -> str:
    """QR-Code als eingebettetes SVG - kein externer Bilddienst, kein Netz beim Drucken."""
    import io

    # segno schreibt Bytes, auch bei SVG - deshalb BytesIO und danach dekodieren.
    puffer = io.BytesIO()
    segno.make(url, error="m").save(puffer, kind="svg", scale=1, xmldecl=False,
                                    svgns=True, omitsize=True, svgclass=None, lineclass=None)
    return puffer.getvalue().decode("utf-8")


def _absender() -> tuple[str, list[str]]:
    """Name und Anschrift aus SENDER_IMPRESSUM ziehen, damit sie nur an einer Stelle steht."""
    teile = [t.strip() for t in (settings.sender_impressum or "").split(",") if t.strip()]
    name = teile[0] if teile else ""
    return name, teile[1:]


def _anrede(lead) -> str:
    """Mit Namen ansprechen, wo OpenStreetMap den Inhaber nennt (bei rund jedem fuenften
    Betrieb). Bewusst ohne "Herr"/"Frau": das Geschlecht steht nirgends, und eine falsche
    Anrede ist schlimmer als eine neutrale."""
    extras = json.loads(lead["osm_extras_json"]) if _hat(lead, "osm_extras_json") else {}
    inhaber = extras.get("inhaber")
    return f"Guten Tag, {inhaber}," if inhaber else "Guten Tag,"


def _hat(lead, spalte: str) -> bool:
    return spalte in lead.keys() and lead[spalte]


def _brief(lead, absender_name: str, absender_zeilen: list[str], heute: str) -> str:
    demo_url = f"{settings.base_url}/sites/{lead['site_slug']}/"
    anschrift = [t.strip() for t in (lead["address"] or "").split(",") if t.strip()]
    anrede = _anrede(lead)

    return f"""
<article class="brief">
  <div class="absender-klein">{html.escape(absender_name)} · {html.escape(' · '.join(absender_zeilen))}</div>

  <div class="kopf">
    <address class="empfaenger">
      <strong>{html.escape(lead['name'])}</strong><br>
      {'<br>'.join(html.escape(z) for z in anschrift)}
    </address>
    <address class="absender">
      {html.escape(absender_name)}<br>
      {'<br>'.join(html.escape(z) for z in absender_zeilen)}
    </address>
  </div>

  <div class="datum">{html.escape(heute)}</div>
  <h1>Ein Website-Entwurf für {html.escape(lead['name'])} – unverbindlich</h1>

  <p>{html.escape(anrede)}</p>

  <p>
    ich habe für {html.escape(lead['name'])} eine vollständige Website entworfen und ins
    Netz gestellt – Sie können sie sich ansehen, ohne mir zu antworten und ohne dass
    Ihnen dadurch Kosten entstehen.
  </p>

  <div class="qr-block">
    <div class="qr">{_qr_svg(demo_url)}</div>
    <div class="qr-text">
      <strong>Mit dem Handy scannen</strong>
      <span class="url">{html.escape(demo_url)}</span>
    </div>
  </div>

  <p>
    Die Seite zeigt Ihr Angebot, Ihre Öffnungszeiten und ein Formular für Anfragen.
    Die Fotos darauf sind Platzhalter – Ihre eigenen Bilder, Texte und Farben setze ich
    ein, sobald Sie mir sagen, wie Sie es haben möchten.
  </p>

  <p>
    Wenn Ihnen der Entwurf gefällt, bringe ich die Seite unter Ihre Wunschadresse und
    kümmere mich um Technik und Erreichbarkeit. Über die Konditionen sprechen wir dann in
    Ruhe. Gefällt er Ihnen nicht, werfen Sie diesen Brief weg – damit ist die Sache erledigt.
  </p>

  <p>Mit freundlichen Grüßen<br><br>{html.escape(absender_name)}</p>

  <div class="fuss">
    {html.escape(absender_name)} · {html.escape(' · '.join(absender_zeilen))}<br>
    Ihre Anschrift stammt aus dem öffentlich einsehbaren OpenStreetMap-Eintrag Ihres
    Betriebs. Auf Wunsch lösche ich sie und Sie hören nichts mehr von mir.
  </div>
</article>"""


def main() -> int:
    # Optional eine Auswahl-Datei (JSON-Liste von site_slug) - fuer einen kleinen
    # Testlauf, statt gleich alle Briefe zu drucken. Ein Testlauf mit 20 Stueck kostet
    # 20 Euro und beantwortet dieselbe Frage wie 100 Stueck: traegt das Angebot?
    auswahl = None
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    for arg in sys.argv[1:]:
        if arg.startswith("--auswahl="):
            import json
            auswahl = set(json.loads(pathlib.Path(arg.split("=", 1)[1]).read_text(encoding="utf-8")))
    grenze = int(argumente[0]) if argumente else 0

    kandidaten = [l for l in db.get_all_leads(limit=1000)
                  if l["site_slug"] and l["status"] in ("ready_to_send", "site_generated")
                  and (auswahl is None or l["site_slug"] in auswahl)]

    # Nur vollstaendige Anschriften. Jeder Brief kostet Porto - eine Adresse ohne
    # Hausnummer oder ohne Ort kommt nicht an, das waere Geld zum Fenster raus.
    # OSM liefert oft Bruchstuecke, z.B. nur "68165" oder nur einen Strassennamen.
    leads, unvollstaendig = [], []
    for lead in kandidaten:
        adresse = (lead["address"] or "").strip()
        vollstaendig = bool(PLZ.search(adresse)) and bool(HAUSNUMMER.search(adresse))
        (leads if vollstaendig else unvollstaendig).append(lead)

    if grenze:
        leads = leads[:grenze]
    if not leads:
        print("Keine Betriebe mit vollstaendiger Postanschrift gefunden.")
        return 1

    absender_name, absender_zeilen = _absender()
    if not absender_name:
        print("SENDER_IMPRESSUM ist leer - ohne Absender kein Brief.")
        return 1

    heute = f"{date.today().day}. {MONATE[date.today().month - 1]} {date.today().year}"
    briefe = "\n".join(_brief(l, absender_name, absender_zeilen, heute) for l in leads)

    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    ZIEL.write_text(VORLAGE.replace("{{BRIEFE}}", briefe), encoding="utf-8")

    # Die Windows-Konsole laeuft je nach Umgebung auf cp1252 und wirft bei Zeichen wie
    # "->" als Pfeil eine UnicodeEncodeError. Deshalb hier bewusst nur ASCII ausgeben -
    # die Briefe selbst sind davon nicht betroffen, die Datei ist UTF-8.
    print(f"{len(leads)} Briefe geschrieben nach {ZIEL}")
    if unvollstaendig:
        print(f"{len(unvollstaendig)} Betriebe uebersprungen - unvollstaendige Anschrift "
              f"(fehlende Hausnummer oder Ort), Porto waere verloren:")
        for lead in unvollstaendig[:5]:
            print(f"    {lead['name']}: {lead['address'] or '(keine Adresse)'}")
        if len(unvollstaendig) > 5:
            print(f"    ... und {len(unvollstaendig) - 5} weitere")
    print("")
    print("So geht es weiter:")
    print(f"  1. Datei im Browser oeffnen: {ZIEL}")
    print('  2. Strg+P, Ziel "Als PDF speichern", Raender "Standard", speichern')
    print("  3. Ausdrucken, falten, in Fensterumschlaege (DIN lang) stecken")
    return 0


VORLAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Anschreiben</title>
<style>
  /* DIN 5008: Anschriftfeld so gesetzt, dass es im Fensterumschlag DIN lang sichtbar ist. */
  @page { size: A4; margin: 0; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Helvetica Neue", Arial, sans-serif; color: #111;
         font-size: 11pt; line-height: 1.55; background: #f4f4f5; }

  .brief { width: 210mm; min-height: 297mm; padding: 20mm 20mm 15mm 25mm;
           background: #fff; margin: 0 auto 10mm; position: relative; page-break-after: always; }
  .brief:last-child { page-break-after: auto; }

  .absender-klein { font-size: 7pt; color: #555; border-bottom: .3pt solid #999;
                    padding-bottom: 1mm; margin-top: 25mm; width: 85mm; }
  .kopf { display: flex; justify-content: space-between; align-items: flex-start; gap: 10mm; }
  .empfaenger { font-style: normal; margin-top: 4mm; width: 85mm; line-height: 1.45; }
  .absender { font-style: normal; font-size: 9pt; color: #444; text-align: right;
              margin-top: 4mm; white-space: nowrap; }

  .datum { text-align: right; margin: 12mm 0 8mm; font-size: 10pt; }
  h1 { font-size: 12.5pt; margin: 0 0 6mm; }
  p { margin: 0 0 4mm; }

  .qr-block { display: flex; align-items: center; gap: 6mm; margin: 6mm 0;
              padding: 4mm; border: .4pt solid #ccc; border-radius: 2mm; }
  .qr svg { width: 28mm; height: 28mm; display: block; shape-rendering: crispEdges; }
  .qr-text { font-size: 10pt; }
  .qr-text strong { display: block; margin-bottom: 1.5mm; }
  .url { font-size: 7.5pt; color: #555; word-break: break-all; }

  .fuss { position: absolute; bottom: 15mm; left: 25mm; right: 20mm;
          font-size: 7.5pt; color: #666; border-top: .3pt solid #ccc; padding-top: 2mm; }

  @media print {
    body { background: #fff; }
    .brief { margin: 0; box-shadow: none; }
  }
</style>
</head>
<body>
{{BRIEFE}}
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
