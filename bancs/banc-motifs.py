"""Le hors affaire selon Alexis (30/09/2026) : quatre motifs, tous sur le CH
des frais généraux, « Autre » à valider, et le trajet dans le chantier.

Joué sur la base directement, horloge fixée : ce banc juge les règles, pas
l'écran (banc-ecran tient la copie des motifs de la tablette)."""
import datetime as dt
import os
import tempfile
from pathlib import Path

from bancs.outils import fin, verif

os.environ.pop("RHI_CH_FRAIS_GENERAUX", None)
os.environ["RHI_ENTREPRISE"] = "VIP"
from rhi import base  # noqa: E402

db = base.connexion(Path(tempfile.mkdtemp()) / "rhi.db")
lundi = dt.date(2026, 9, 28)
t = lambda h, m=0, j=28: dt.datetime(2026, 9, j, h, m)  # noqa: E731

verif(list(base.MOTIFS) == ["RANGEMENT", "ENTRETIEN", "FORMATION", "AUTRE"], "les quatre motifs, dans l'ordre d'Alexis")
verif(not {"TRAJET", "PANNE", "ATTENTE_MATIERE"} & set(base.MOTIFS), "trajet, panne, attente matière : plus proposés")
verif(base.ch_frais_generaux() == "CH00081", "VIP : le CH FG SER donné par Alexis")
os.environ["RHI_ENTREPRISE"] = "ALFA"
verif(base.ch_frais_generaux() == "", "Alfa : pas de CH FG connu, rien n'est inventé")
os.environ["RHI_CH_FRAIS_GENERAUX"] = " ch00123 "
verif(base.ch_frais_generaux() == "CH00123", "réglable par l'environnement")
os.environ.pop("RHI_CH_FRAIS_GENERAUX")
os.environ["RHI_ENTREPRISE"] = "VIP"

# ── Une journée : chantier, rangement, un « trajet » d'une vieille tablette ──
base.demarrer(db, ["PAUL"], t(7), ch="CH00901")
base.demarrer(db, ["PAUL"], t(11), motif="RANGEMENT")
base.demarrer(db, ["PAUL"], t(12), motif="TRAJET")          # tablette restée hors ligne
base.arreter(db, ["PAUL"], t(12, 30))
motifs = [r["motif"] for r in db.execute("SELECT motif FROM pointages WHERE ch IS NULL ORDER BY debut")]
verif(motifs == ["RANGEMENT", "AUTRE"], f"un motif retiré tombe sur « Autre », à valider : {motifs}")
verif(base.ajouter(db, "PAUL", "2026-09-29T08:00:00", "2026-09-29T09:00:00", motif="PANNE") and
      db.execute("SELECT motif FROM pointages WHERE debut LIKE '2026-09-29%'").fetchone()[0] == "AUTRE",
      "même règle pour une saisie au bureau")

# L'historique garde ses libellés : un RHI pointé avant le 30/09 reste lisible.
with db:
    db.execute("""INSERT INTO pointages(personne, ch, motif, libelle, debut, fin, appareil)
                  VALUES ('JEAN', NULL, 'ATTENTE_MATIERE', '', '2026-09-28T08:00:00', '2026-09-28T09:00:00', 'tab')""")
rj = base.rhi(db, "JEAN", lundi, t(18))
verif(rj["lignes"][0]["libelle"] == "Attente matière / plans", "un ancien motif garde son libellé")

r = base.rhi(db, "PAUL", lundi, t(18))
hors = [l for l in r["lignes"] if not l["ch"]]
verif(hors and all(l["ch_impute"] == "CH00081" for l in hors), "le hors affaire est imputé au CH des frais généraux")
verif(next(l for l in r["lignes"] if l["ch"] == "CH00901")["ch_impute"] == "CH00901", "une affaire reste sur son CH")
autre = [p for p in r["pointages"] if p["motif"] == "AUTRE"]
verif(autre and "Motif « autre » à valider" in autre[0]["alertes"], "« Autre » attend la validation du contrôleur")

# ── Vers InterFast : le hors affaire forme une case sur le CH FG ──
e = base.envois(db, lundi, t(18))
fg = [c for c in e["cases"] if c["ch"] == "CH00081"]
verif(len(fg) == 2 and {c["jour"] for c in fg} == {"2026-09-28", "2026-09-29"},
      f"une case CH00081 par jour de hors affaire : {[(c['ch'], c['jour']) for c in e['cases']]}")
lun = next(c for c in fg if c["jour"] == "2026-09-28")
verif(lun["heures"] == 2.5 and "Rangement (atelier)" in lun["description"]
      and {x["personne"] for x in lun["equipe"]} == {"PAUL", "JEAN"},
      f"Paul 1 h 30 (rangement, « autre ») + Jean 1 h d'ancien motif, lisibles dans la case : {lun['description']}")
os.environ["RHI_CH_FRAIS_GENERAUX"] = ""
verif(not [c for c in base.envois(db, lundi, t(18))["cases"] if not c["ch"] or c["ch"] == "CH00081"],
      "sans CH FG réglé, le hors affaire reste hors d'InterFast (comme avant)")
os.environ.pop("RHI_CH_FRAIS_GENERAUX")

fin("banc-motifs")
