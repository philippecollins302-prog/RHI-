"""La validation en deux étages (Alexis, 30/09/2026).

Chaque chargé d'affaires contrôle SES chantiers — heures de chacun, jour par
jour, face au planning ; le responsable de BU valide ensuite les RHI. Le
contrôle tombe si les heures bougent dessous, et ne se retire pas sous un
RHI déjà validé."""
import datetime as dt
import tempfile
from pathlib import Path

from bancs.outils import fin, verif
from rhi import base

db = base.connexion(Path(tempfile.mkdtemp()) / "rhi.db")
lundi = dt.date(2026, 9, 28)
t = lambda j, h, m=0: dt.datetime(2026, 9, j, h, m)  # noqa: E731
with db:
    for ch, nom, conduc in (("CH00901", "LES PINS", "AA"), ("CH00902", "LE PORT", "BB"), ("CH00903", "SANS CHARGÉ", "")):
        db.execute("INSERT INTO affaires(ch, chantier, conduc, source, maj) VALUES (?,?,?,'plan', '')", (ch, nom, conduc))
    for p, j, ch in (("PAUL", "2026-09-28", "CH00901"), ("PAUL", "2026-09-29", "CH00901"), ("JEAN", "2026-09-28", "CH00902")):
        db.execute("INSERT INTO planning(personne, jour, ch, libelle, origine) VALUES (?,?,?,'','atelier')", (p, j, ch))
        db.execute("INSERT OR IGNORE INTO personnes(nom, equipe) VALUES (?, 'atelier')", (p,))

base.demarrer(db, ["PAUL"], t(28, 7), ch="CH00901")
base.demarrer(db, ["PAUL"], t(28, 12), ch="CH00902")            # pas prévu sur CH00902
base.arreter(db, ["PAUL"], t(28, 16))
base.demarrer(db, ["PAUL"], t(29, 7), ch="CH00903")            # mardi : ailleurs que prévu
base.arreter(db, ["PAUL"], t(29, 8))
base.demarrer(db, ["JEAN"], t(28, 7), ch="CH00902")
base.arreter(db, ["JEAN"], t(28, 15))
base.demarrer(db, ["JEAN"], t(29, 7), ch="CH00903")
base.arreter(db, ["JEAN"], t(29, 9))
a = t(30, 18)

s = base.chantiers_semaine(db, lundi, a)
verif(s["conducs"] == ["AA", "BB"], f"les chargés d'affaires de la semaine : {s['conducs']}")
aa = base.chantiers_semaine(db, lundi, a, "AA")["chantiers"]
verif([c["ch"] for c in aa] == ["CH00901"], "chacun ne voit que ses chantiers")
c901 = aa[0]
verif(c901["gens"] == [{"personne": "PAUL", "jours": [5.0, 0, 0, 0, 0, 0, 0], "total": 5.0}],
      f"heures de chacun, jour par jour : {c901['gens']}")
verif(c901["prevu_non_pointe"] == [{"personne": "PAUL", "jour": "2026-09-29"}],
      "prévu au planning mardi, rien pointé sur ce chantier : dit")
c902 = next(c for c in s["chantiers"] if c["ch"] == "CH00902")
verif(c902["hors_planning"] == [{"personne": "PAUL", "jour": "2026-09-28"}] and c902["total"] == 12.0,
      "pointé sans être prévu (le planning a du retard) : dit, pas refusé")

# ── Premier étage ──
base.demarrer(db, ["JEAN"], t(30, 7), ch="CH00902")
try:
    base.controler_ch(db, "CH00902", lundi, "BB", a)
    verif(False, "contrôle accepté avec un pointage ouvert")
except ValueError as e:
    verif("ouvert" in str(e), "pas de contrôle tant qu'une durée n'est pas connue")
base.arreter(db, ["JEAN"], t(30, 8))
try:
    base.controler_ch(db, "CH00902", lundi, "  ", a)
    verif(False, "contrôle anonyme accepté")
except ValueError:
    verif(True, "un contrôle se signe")
verif(base.controler_ch(db, "CH00902", lundi, "BB", a)["par"] == "BB", "BB contrôle CH00902")

# ── Second étage : la validation de masse attend les contrôles ──
v = base.valider_tout(db, lundi, "BU", a)
raisons = {e["personne"]: e["raisons"] for e in v["ecartes"]}
verif("JEAN" in v["valides"], f"Jean : CH00902 contrôlé, CH00903 sans chargé connu → validé : {v}")
verif(raisons.get("PAUL") == ["CH00901 pas encore contrôlé par AA"], f"Paul attend AA : {raisons}")
base.controler_ch(db, "CH00901", lundi, "AA", a)
verif("PAUL" in base.valider_tout(db, lundi, "BU", a)["valides"], "AA a contrôlé : Paul passe")
r = base.rhi(db, "PAUL", lundi, a)
verif(all(l["controle"] for l in r["lignes"] if l["conduc"]) and any(l["ch"] == "CH00903" and not l["controle"] for l in r["lignes"]),
      "le RHI montre chaque chantier contrôlé ; un chantier sans chargé connu reste au BU")

# ── Un contrôle ne se retire pas sous un RHI validé ──
try:
    base.decontroler_ch(db, "CH00901", lundi)
    verif(False, "contrôle retiré sous un RHI validé")
except ValueError as e:
    verif("PAUL" in str(e), "on dévalide d'abord le RHI, l'étage du dessus")
base.devalider(db, "PAUL", lundi)
base.decontroler_ch(db, "CH00901", lundi)
verif(base.controle(db, "CH00901", lundi) is None, "puis le contrôle se retire")

# ── Les heures bougent : le contrôle tombe ──
base.controler_ch(db, "CH00901", lundi, "AA", a)
pid = db.execute("SELECT id FROM pointages WHERE personne='PAUL' AND ch='CH00902'").fetchone()[0]
base.corriger(db, pid, "bureau", ch="CH00901")
verif(base.controle(db, "CH00901", lundi) is None and base.controle(db, "CH00902", lundi) is None,
      "heures transférées de CH00902 à CH00901 : les deux contrôles tombent, à refaire sur ce qui est là")
base.controler_ch(db, "CH00901", lundi, "AA", a)
base.ajouter(db, "PAUL", "2026-09-29T08:00:00", "2026-09-29T10:00:00", ch="CH00901")
verif(base.controle(db, "CH00901", lundi) is None, "une saisie au bureau sur un chantier contrôlé le rouvre aussi")
base.controler_ch(db, "CH00901", lundi, "AA", a)
base.demarrer(db, ["PAUL"], t(30, 9), ch="CH00901")
verif(base.controle(db, "CH00901", lundi) is None, "un nouveau pointage sur la tablette aussi")

fin("banc-controles")
