"""La menuiserie (Alfa) : ses deux plannings, et une instance par entreprise."""
import datetime as dt
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs import fabrique
from bancs.outils import fin, verif
from rhi import lecture

D = dt.date
tmp = Path(tempfile.mkdtemp())
fabrique.atelier_men(tmp / "ate-men.xlsx")
fabrique.pose_men(tmp / "pose-men.xlsx")
fabrique.atelier(tmp / "ate-ser.xlsx")

a = lecture.lire(tmp / "ate-men.xlsx", "ALFA")
verif(a["nature"] == "atelier", "atelier menuiserie reconnu")
verif(a["personnes"] == ["HUGO", "NINA"], f"opérateurs en colonne B, sans chargés d'affaires ni titre : {a['personnes']}")
hugo = sorted((x["jour"], x["codes"]) for x in a["affectations"] if x["personne"] == "HUGO")
verif(hugo == [(D(2026, 9, 28), ["CH00911"]), (D(2026, 9, 29), ["CH00911"])], f"fusion sur deux jours : {hugo}")
nina = [x for x in a["affectations"] if x["personne"] == "NINA"]
verif(len(nina) == 1 and nina[0]["codes"] == [] and nina[0]["libelle"] == "SANS NUMERO ENCORE",
      "une case sans CH reste une affectation ; le CP n'en est pas une")
verif(a["affaires"][0]["ch"] == "CH00911", "plan de charge : CH repéré dans la désignation")

p = lecture.lire(tmp / "pose-men.xlsx", "ALFA")
verif(p["personnes"] == ["OSCAR", "PAUL"], f"équipe séparée par un retour à la ligne, sans sous-traitant : {p['personnes']}")
jours = sorted({(x["jour"], x["libelle"], tuple(x["codes"])) for x in p["affectations"]})
verif(jours == [(D(2026, 9, 28), "ECOLE DES OLIVIERS / MENUISERIES", ("CH00911",)),
                (D(2026, 9, 30), "SAV DIVERS", ())],
      f"dates (mois en ligne 1, « L28 » en ligne 3), CP exclu, 2e ligne lue : {jours}")

# ── Une instance par entreprise ──
for croise, entreprise in (("ate-ser.xlsx", "ALFA"), ("ate-men.xlsx", "VIP")):
    try:
        lecture.lire(tmp / croise, entreprise)
        verif(False, f"{croise} ne doit pas passer sur l'instance {entreprise}")
    except lecture.FichierInattendu as e:
        verif("se dépose sur le RHI" in str(e), f"refus expliqué : {e}")

os.environ["RHI_DONNEES"] = str(tmp)
os.environ["RHI_ENTREPRISE"] = "ALFA"
os.environ["INTERFAST_VIP"] = "cle-vip"
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_ALFA"):
    os.environ.pop(k, None)
import app as appli  # noqa: E402
appli.app.state.chemin_base = tmp / "alfa.db"
c = TestClient(appli.app)
verif(c.get("/api/config").json() == {"entreprise": "ALFA", "nom": "Alfa (menuiserie)"}, "instance Alfa")
r = c.post("/api/plannings", files={"fichier": ("p.xlsx", (tmp / "pose-men.xlsx").read_bytes())})
verif(r.status_code == 200 and r.json()["personnes"] == 2, f"import pose menuiserie : {r.text}")
r = c.post("/api/plannings", files={"fichier": ("s.xlsx", (tmp / "ate-ser.xlsx").read_bytes())})
verif(r.status_code == 422 and "VIP Plus" in r.json()["detail"], "le planning de VIP refusé sur l'instance Alfa")
s = c.get("/api/sante").json()
verif(s["entreprise"] == "ALFA" and s["cle_interfast"] is False,
      "la clé de VIP ne sert pas à Alfa : INTERFAST_ALFA attendue")
r = c.post("/api/interfast/chantiers")
verif(r.status_code == 503 and "INTERFAST_ALFA" in r.json()["detail"], "et InterFast le dit")
verif(c.get("/api/menu?personne=OSCAR&jour=2026-09-28").json()["planning"][0]["ch"] == "CH00911",
      "le poseur d'Alfa voit son chantier du jour")

fin("banc-men")
