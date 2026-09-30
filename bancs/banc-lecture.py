"""Les lecteurs de plannings, sur des classeurs fictifs de la même forme."""
import datetime as dt
import tempfile
from pathlib import Path

from bancs import fabrique
from bancs.outils import fin, verif
from rhi import lecture

D = dt.date
tmp = Path(tempfile.mkdtemp())

# ── Atelier ──
fabrique.atelier(tmp / "ate.xlsx")
a = lecture.lire(tmp / "ate.xlsx")
verif(a["nature"] == "atelier", "reconnu comme planning atelier")
verif(a["personnes"] == ["JEAN", "PAUL"], f"opérateurs lus au samedi, sans le sous-traitant : {a['personnes']}")
paul = {x["jour"]: x for x in a["affectations"] if x["personne"] == "PAUL"}
verif(set(paul) == {D(2026, 9, 28), D(2026, 9, 29), D(2026, 9, 30), D(2026, 10, 1), D(2026, 10, 2)},
      "la case fusionnée sur trois jours compte trois jours (et la date fausse d'en-tête est corrigée)")
verif(paul[D(2026, 9, 30)]["codes"] == ["CH00901"], "CH lu dans la bande, sous le libellé")
verif(paul[D(2026, 10, 1)]["codes"] == ["CH00902"], "tâche suivante")
verif(paul[D(2026, 9, 28)]["libelle"] == "LES PINS / GARDE-CORPS (X4)", "libellé sur deux lignes")
jean = [x for x in a["affectations"] if x["personne"] == "JEAN"]
verif(all(x["jour"] != D(2026, 9, 28) for x in jean), "un CP n'est pas une affectation")
verif(jean[0]["codes"] == ["CH00902", "CH00901"], "deux CH dans une case")
verif(not any(x["jour"].weekday() >= 5 for x in a["affectations"]), "rien le week-end")

bk = a["affaires"]
verif(len(bk) == 4, f"quatre lignes de backlog, sans la ligne TOTAL : {len(bk)}")
verif(bk[0] == {"ch": "CH00901", "chantier": "LES PINS", "designation": "GARDE-CORPS (X4)",
                "conduc": "AA", "heures": 40.0, "semaines": [40], "commentaire": ""}, "ligne complète")
verif(bk[2]["semaines"] == [40, 41] and bk[2]["commentaire"] == "ATTENTE VALIDATION", "semaines et commentaire")
verif(bk[3]["ch"] is None, "ligne sans CH gardée, CH à None")

# ── Pose ──
fabrique.pose(tmp / "pose.xlsx")
p = lecture.lire(tmp / "pose.xlsx")
verif(p["nature"] == "pose", "reconnu comme planning pose")
verif(p["personnes"] == ["LUC", "MARC"], f"les deux membres de l'équipe, ni sous-traitant ni encadrant : {p['personnes']}")
jours = sorted({(x["personne"], x["jour"]) for x in p["affectations"]})
verif(jours == [("LUC", D(2026, 9, 28)), ("LUC", D(2026, 9, 29)),
                ("MARC", D(2026, 9, 28)), ("MARC", D(2026, 9, 29))],
      f"pose fusionnée sur deux jours, pour les deux, CP exclu : {jours}")
verif(all(x["codes"] == ["CH00901"] for x in p["affectations"]), "CH lu dans la ligne N° AFFAIRE fusionnée")

verif(lecture.personnes_equipe("EQUIPE LUC & MARC\n(Resp. MM)") == ["LUC", "MARC"], "équipe à deux")
verif(lecture.personnes_equipe("THEO & NINO\n(Resp. LC)") == ["THEO", "NINO"], "sans le mot EQUIPE")

# ── Ce qu'on refuse, en le disant ──
fabrique.bet(tmp / "bet.xlsx")
try:
    lecture.lire(tmp / "bet.xlsx")
    verif(False, "un BET sans ligne « N° Affaire » doit être refusé")
except lecture.FichierInattendu as e:
    verif("N° Affaire" in str(e), "BET illisible : refus expliqué")
(tmp / "faux.xlsx").write_text("pas un classeur")
try:
    lecture.lire(tmp / "faux.xlsx")
    verif(False, "un faux fichier doit être refusé")
except lecture.FichierInattendu:
    verif(True, "")

fin("banc-lecture")
