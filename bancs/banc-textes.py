"""Les lectures de texte libre : codes CH, semaines, dates du BET."""
import datetime as dt

from bancs.outils import fin, verif
from rhi.textes import codes_ch, normaliser, periode_bet, semaines

D = dt.date

verif(codes_ch("CH00901/CH00902") == ["CH00901", "CH00902"], "deux CH dans une case")
verif(codes_ch("A-25-07-VIPP-00000/CH00901") == ["CH00901"], "CH derrière un n° VIPP")
verif(codes_ch("N°CH00904") == ["CH00904"], "CH précédé de N°")
verif(codes_ch("ch00905 et CH00905") == ["CH00905"], "minuscules et doublon")
verif(codes_ch("CH0006") == [], "quatre chiffres : pas un CH")
verif(codes_ch(None) == [], "case vide")

verif(normaliser("Maison Médicale  DES ROSES\n") == "MAISON MEDICALE DES ROSES", "accents et blancs")

verif(semaines("S36") == [36], "une semaine")
verif(semaines("S49-50") == [49, 50], "deux semaines")
verif(semaines("S23-24-25-26-27") == [23, 24, 25, 26, 27], "cinq semaines")
verif(semaines("PLIAGE") == [], "pas une semaine")

verif(periode_bet(dt.datetime(2026, 9, 7)) == (D(2026, 9, 7), D(2026, 9, 7)), "datetime")
verif(periode_bet("01 au 03/09/2026") == (D(2026, 9, 1), D(2026, 9, 3)), "« au »")
verif(periode_bet("04 et 07/09/26") == (D(2026, 9, 4), D(2026, 9, 7)), "année sur deux chiffres")
verif(periode_bet("14,15/09/2026") == (D(2026, 9, 14), D(2026, 9, 15)), "virgule")
verif(periode_bet("02-05/10/2026") == (D(2026, 10, 2), D(2026, 10, 5)), "tiret")
verif(periode_bet("07/10//2026") == (D(2026, 10, 7), D(2026, 10, 7)), "double barre")
verif(periode_bet("31/02/2026") is None, "date impossible : None, pas d'exception")
verif(periode_bet("") is None, "vide")

from rhi.base import chantiers_de
verif(chantiers_de("LES PINS / GARDE-CORPS", ["CH00901"]) == {"CH00901": "LES PINS"}, "un chantier")
verif(chantiers_de("LES PINS / STRUCTURE BALCON / LE PORT / POSE PORTAIL", ["CH00901", "CH00903"])
      == {"CH00901": "LES PINS", "CH00903": "LE PORT"}, "deux chantiers dans une case : chacun le sien")
verif(chantiers_de("LE PORT / PORTAIL", ["CH00902", "CH00901"]) == {},
      "compte qui ne tombe pas juste : pas de nom plutôt qu'un faux")

from rhi.base import semaine_proche
L = dt.date(2026, 9, 28)
verif(semaine_proche(11, L)[0] == dt.date(2026, 3, 9), "S11 lue fin septembre : mars 2026, pas mars 2027")
verif(semaine_proche(49, L)[0] == dt.date(2025, 12, 1), "S49 : décembre 2025 (le haut du plan de charge)")
verif(semaine_proche(43, L)[0] == dt.date(2026, 10, 19), "S43 : dans trois semaines")
verif(semaine_proche(2, dt.date(2026, 12, 21))[0] == dt.date(2027, 1, 11), "S02 lue en décembre : janvier suivant")

fin("banc-textes")
