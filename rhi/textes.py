"""Petits outils de lecture : codes d'affaire, noms, semaines, dates BET.

Les plannings sont tenus à la main dans Excel : un même chantier s'écrit
« LES CIGALES » ou « LES CIGLAES », une date d'étude « 14,15/09/2026 » ou
« 06/10/10/2026 ». Tout ce qui interprète du texte libre vit ici, et chaque
règle a son cas dans bancs/banc-textes.py.
"""
import datetime as dt
import re
import unicodedata

# Le numéro d'affaire InterFast. C'est la SEULE clé fiable entre les
# plannings : le nom du chantier varie d'un fichier à l'autre (ABCD/ACBD,
# LES CIGALES/LES CIGLAES), le CH, lui, est recopié.
MOTIF_CH = re.compile(r"CH\s*(\d{5})")


def codes_ch(texte) -> list:
    """Tous les CH d'une cellule, dans l'ordre, sans doublon : « CH00901/CH00902 »."""
    if texte is None:
        return []
    vus = []
    for n in MOTIF_CH.findall(str(texte).upper()):
        code = "CH" + n
        if code not in vus:
            vus.append(code)
    return vus


def sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normaliser(s) -> str:
    """Majuscules, sans accent ni ponctuation, espaces simples."""
    if s is None:
        return ""
    s = sans_accent(str(s)).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(s.split())


def lignes(cellule) -> list:
    """Une case de planning « CHANTIER\\nTRAVAUX » découpée en lignes non vides."""
    if cellule is None:
        return []
    return [l.strip() for l in str(cellule).splitlines() if l.strip()]


# ── Semaines du plan de charge : « S36 », « S49-50 », « S23-24-25-26-27 » ──

def semaines(texte) -> list:
    """Les numéros de semaine d'une case S-FAB, ou [] si rien de lisible."""
    if texte is None:
        return []
    t = str(texte).upper().replace(" ", "")
    if not t.startswith("S"):
        return []
    return [int(n) for n in re.findall(r"\d{1,2}", t) if 1 <= int(n) <= 53]


def lundi_iso(annee: int, semaine: int) -> dt.date:
    return dt.date.fromisocalendar(annee, semaine, 1)


# ── Dates du planning BET, saisies à la main ──

def periode_bet(valeur):
    """(début, fin) d'une case « Date planifiée » du BET, ou None.

    Formes rencontrées dans le vrai fichier (09/2026) :
      datetime · « 01 au 03/09/2026 » · « 04 et 07/09/26 » · « 14,15/09/2026 »
      « 02-05/10/2026 » · « 07/10//2026 » · « 06/10/10/2026 »
    Méthode : le dernier nombre est l'année, l'avant-dernier le mois, tous les
    autres des jours. Le cas « 06/10/10/2026 » donne donc 06→10/10 : une
    lecture défendable d'une saisie fautive, plutôt qu'un rejet silencieux.
    """
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, dt.datetime):
        return (valeur.date(), valeur.date())
    if isinstance(valeur, dt.date):
        return (valeur, valeur)
    nombres = [int(n) for n in re.findall(r"\d+", str(valeur))]
    if len(nombres) < 3:
        return None
    annee, mois, jours = nombres[-1], nombres[-2], nombres[:-2]
    if annee < 100:
        annee += 2000
    try:
        dates = [dt.date(annee, mois, j) for j in jours]
    except ValueError:
        return None
    return (min(dates), max(dates))
