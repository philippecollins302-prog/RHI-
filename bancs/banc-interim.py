"""Intérimaires ajoutés par les RH, et le CH DIVERS (Alexis, 30/09/2026).

Les intérimaires pointent sous leur nom sur les tablettes des permanents :
le bureau doit pouvoir les ajouter sans passer par un planning. Les
interventions sans numéro d'affaire tombent sur un CH DIVERS, dont les
heures se transfèrent ensuite vers le bon CH."""
import datetime as dt
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "RHI_CH_DIVERS"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 28, 7, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)

# ── Les RH ajoutent un intérimaire ──
r = c.post("/api/personnes", json={"nom": "  dupont   jean ", "equipe": "atelier"})
verif(r.status_code == 200 and r.json()["nom"] == "DUPONT JEAN" and r.json()["interim"] == 1,
      f"ajouté, nom remis au propre, marqué intérim : {r.text}")
verif("DUPONT JEAN" in [p["nom"] for p in c.get("/api/personnes?equipe=atelier").json()],
      "il apparaît aussitôt sur les tablettes de l'atelier")
verif(c.post("/api/personnes", json={"nom": "", "equipe": "atelier"}).status_code == 422, "sans nom : refusé")
verif(c.post("/api/personnes", json={"nom": "X" * 41, "equipe": "atelier"}).status_code == 422, "nom trop long : refusé")
verif(c.post("/api/personnes", json={"nom": "MARTIN", "equipe": "bureau"}).status_code == 422, "équipe inconnue : refusée")
c.patch("/api/personnes/DUPONT JEAN", json={"actif": 0})
verif("DUPONT JEAN" not in [p["nom"] for p in c.get("/api/personnes").json()], "fin de mission : désactivé")
r = c.post("/api/personnes", json={"nom": "Dupont Jean", "equipe": "pose"})
verif(r.json()["deja"] and [p["equipe"] for p in c.get("/api/personnes").json() if p["nom"] == "DUPONT JEAN"] == ["pose"],
      "le même revient : réactivé, pas doublé")
verif(len([p for p in c.get("/api/personnes/detail").json()["personnes"] if p["nom"] == "DUPONT JEAN"]) == 1, "une seule fiche")
verif(c.post("/api/pointages", json={"personne": "DUPONT JEAN", "ch": "CH00901",
                                     "debut": "2026-09-28T08:00:00", "fin": "2026-09-28T12:00:00"}).status_code == 200,
      "il pointe comme un permanent")

# ── CH DIVERS ──
verif(c.get("/api/menu?personne=DUPONT JEAN&jour=2026-09-28").json()["ch_divers"] == "",
      "pas de numéro réglé : la tablette ne propose pas de CH DIVERS (on n'invente pas un CH)")
os.environ["RHI_CH_DIVERS"] = "ch00999"
verif(c.get("/api/menu?personne=DUPONT JEAN&jour=2026-09-28").json()["ch_divers"] == "CH00999",
      "numéro réglé : proposé sur la tablette")
a = heure["t"] = dt.datetime(2026, 9, 29, 8, 0)
c.post("/api/demarrer", json={"personnes": ["DUPONT JEAN"], "ch": "CH00999"})
heure["t"] = dt.datetime(2026, 9, 29, 10, 0)
c.post("/api/arreter", json={"personnes": ["DUPONT JEAN"]})
rel = c.get("/api/rhi?personne=DUPONT JEAN&semaine=2026-09-28").json()["releves"][0]
p = next(x for x in rel["pointages"] if x["ch"] == "CH00999")
verif(any(x.startswith("CH DIVERS") for x in p["alertes"]), "le bureau voit qu'il reste à transférer")
verif(not any("saisi à la main" in x for x in p["alertes"]), "le CH DIVERS n'est pas « saisi à la main »")
heure["t"] = dt.datetime(2026, 10, 5, 9, 0)
v = c.post("/api/validations/toutes", json={"semaine": "2026-09-28", "qui": "bureau"}).json()
verif("DUPONT JEAN" in v["valides"], f"des heures sur CH DIVERS n'empêchent pas la validation : {v}")
c.delete("/api/validations?personne=DUPONT JEAN&semaine=2026-09-28")
r = c.patch(f"/api/pointages/{p['id']}", json={"ch": "CH00901", "qui": "bureau"})
verif(r.status_code == 200 and r.json()["ch"] == "CH00901", "transfert vers le bon CH, tracé")
rel = c.get("/api/rhi?personne=DUPONT JEAN&semaine=2026-09-28").json()["releves"][0]
verif([l["ch"] for l in rel["lignes"]] == ["CH00901"] and rel["total"] == 6.0,
      f"les heures ont suivi, rien de perdu : {[(l['ch'], l['total']) for l in rel['lignes']]}")
os.environ.pop("RHI_CH_DIVERS")

fin("banc-interim")
