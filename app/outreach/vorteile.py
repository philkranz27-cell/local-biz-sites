"""Warum sich eine eigene Website lohnt - fuer Briefe und Mails.

Bisher stand in Brief und Mail nur: Der Entwurf ist fertig, schauen Sie ihn sich an.
Warum ein Betrieb ueberhaupt eine Website wollen sollte, stand nirgends. Genau das soll
ueberzeugen - also steht es jetzt drin, und zwar an einer Stelle fuer beide Kanaele.

Zwei Grenzen, bewusst gezogen:
- Keine Zahlen. "97 % suchen online" liest man oft; belegen laesst es sich hier nicht,
  und eine erfundene Statistik in einem Werbebrief ist irrefuehrende Werbung.
- Keine Versprechen, die niemand halten kann: nicht "mehr Umsatz", nicht "Platz 1 bei
  Google". Stattdessen, was eine Website tatsaechlich tut.

Und so konkret wie moeglich: Ein Friseur hat ein anderes Problem als ein Restaurant, und
wer schon auf Facebook ist, braucht einen anderen Satz als jemand, der nirgends ist.
"""

from __future__ import annotations

# Kategorie -> (mit Artikel fuer "nach ... sucht", der konkreteste Vorteil fuer genau
# diese Art Betrieb). Der erste Punkt ist immer der branchenspezifische: Er beschreibt
# ein Problem, das der Inhaber aus seinem Alltag kennt.
KATEGORIEN = {
    "restaurant": ("einem Restaurant",
                   "Tischreservierungen direkt über die Seite – auch am Ruhetag und spät "
                   "abends, wenn niemand ans Telefon geht."),
    "cafe": ("einem Café",
             "Tischanfragen direkt über die Seite – auch dann, wenn gerade niemand ans "
             "Telefon kann."),
    "bar": ("einer Bar",
            "Reservierungen für Gruppen und Feiern direkt über die Seite, rund um die Uhr."),
    "bakery": ("einer Bäckerei",
               "Vorbestellungen direkt online – ohne Anruf mitten im Morgengeschäft."),
    "hair_salon": ("einem Friseur",
                   "Terminanfragen direkt über die Seite – ohne dass während eines Schnitts "
                   "das Telefon klingelt."),
    "gym": ("einem Fitnessstudio",
            "Probetraining direkt online anfragen – genau in dem Moment, in dem jemand "
            "sich entscheidet."),
    "florist": ("einem Blumenladen",
                "Anfragen für Hochzeiten, Geburtstage und andere Anlässe direkt über die "
                "Seite."),
}

_STANDARD = ("einem Betrieb wie Ihrem",
             "Anfragen direkt über die Seite – rund um die Uhr, auch wenn Sie gerade "
             "keine Zeit für das Telefon haben.")


def vorteile(kategorie: str | None, stadt: str | None, extras: dict | None = None) -> list[str]:
    """Genau drei Vorteile, der branchenspezifische zuerst."""
    mit_artikel, konkret = KATEGORIEN.get(kategorie or "", _STANDARD)
    ort = f"in {stadt} " if stadt else ""
    auffindbar = (f"Auffindbar, wenn jemand {ort}online nach {mit_artikel} sucht – auch "
                  "für Leute, die Sie noch nicht kennen.")

    netze = list(((extras or {}).get("soziale_netze") or {}).keys())
    if netze:
        # Wer schon auf Facebook ist, denkt oft, er brauche keine Website. Der Satz
        # nimmt ihm genau diesen Einwand, statt ihn zu ignorieren.
        name = " und ".join(netze)
        dritter = (f"Ihr {name}-Auftritt bleibt – die Website verlinkt ihn und erreicht "
                   "auch alle, die dort kein Konto haben.")
    else:
        dritter = ("Öffnungszeiten, Angebot und Kontakt an einem Ort – aktuell und jederzeit "
                   "abrufbar, auch unterwegs am Handy.")

    return [konkret, auffindbar, dritter]
