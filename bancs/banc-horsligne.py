"""Pointer sans réseau : les gestes gardés sur l'appareil, rejoués plus tard.

« Jamais bloqué » vaut aussi pour un chantier sans réseau : le téléphone
garde l'heure de chaque geste et l'envoie au retour du réseau."""
import datetime as dt
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 29, 17, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)


def rhi(nom):
    return c.get(f"/api/rhi?personne={nom}&semaine=2026-09-28").json()["releves"][0]


# ── Une journée de pose sans réseau, rejouée à 17 h ──
file = [
    ("/api/demarrer", {"personnes": ["LUC", "MARC"], "ch": "CH00901", "quand": "2026-09-29T07:30:00"}),
    ("/api/demarrer", {"personnes": ["LUC", "MARC"], "motif": "TRAJET", "quand": "2026-09-29T12:00:00"}),
    ("/api/demarrer", {"personnes": ["LUC", "MARC"], "ch": "CH00902", "quand": "2026-09-29T13:00:00"}),
    ("/api/arreter", {"personnes": ["LUC", "MARC"], "quand": "2026-09-29T16:30:00"}),
]
for chemin, corps in file:
    verif(c.post(chemin, json=corps).status_code == 200, f"rejeu {chemin}")
luc = rhi("LUC")
l = {x["ch"] or x["motif"]: x["total"] for x in luc["lignes"]}
verif(l == {"CH00901": 4.5, "CH00902": 3.5, "TRAJET": 1.0}, f"heures du geste, pas de l'envoi : {l}")
verif(all(any("hors ligne" in a for a in p["alertes"]) for p in luc["pointages"]),
      "chaque pointage rejoué est signalé au bureau")
verif(rhi("MARC")["total"] == 9.0, "le binôme aussi")

# ── Pointé ailleurs entre-temps : pas de chevauchement ──
# Paul pointe à 10 h sur la tablette de l'atelier (en ligne)…
heure["t"] = dt.datetime(2026, 9, 29, 10, 0)
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00902"})
# … puis son téléphone, resté hors ligne, rejoue à 11 h un départ de 8 h.
heure["t"] = dt.datetime(2026, 9, 29, 11, 0)
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00901", "quand": "2026-09-29T08:00:00"})
c.post("/api/arreter", json={"personnes": ["PAUL"], "quand": "2026-09-29T09:00:00"})
p = {x["ch"]: x for x in rhi("PAUL")["pointages"]}
verif(p["CH00901"]["fin"] == "2026-09-29T10:00:00",
      f"le geste rejoué s'arrête où le suivant commence : {p['CH00901']}")
verif(p["CH00902"]["fin"] is None, "le pointage en ligne, plus récent, n'est pas touché par l'arrêt rejoué")
verif(len(c.get("/api/en-cours?personne=PAUL").json()["pointages"]) == 1, "toujours un seul ouvert")

# ── Horloges d'appareil ──
heure["t"] = dt.datetime(2026, 9, 30, 8, 0)
r = c.post("/api/demarrer", json={"personnes": ["ZOE"], "ch": "CH00901", "quand": "2026-09-30T08:07:00"})
verif(r.status_code == 200, "horloge en avance acceptée")
verif(c.get("/api/en-cours?personne=ZOE").json()["pointages"][0]["debut"] == "2026-09-30T08:00:00",
      "… et ramenée à l'heure du serveur")
verif(not any("hors ligne" in a for a in rhi("ZOE")["pointages"][0]["alertes"]), "un geste en direct n'est pas « hors ligne »")
r = c.post("/api/demarrer", json={"personnes": ["ZOE"], "ch": "CH00901", "quand": "2026-09-26T08:00:00"})
verif(r.status_code == 422 and "72 h" in r.json()["detail"], "plus de 72 h : au bureau")
verif(c.post("/api/arreter", json={"personnes": ["ZOE"], "quand": "hier"}).status_code == 422, "heure illisible")
verif(c.post("/api/arreter", json={"personnes": ["ZOE"], "quand": "2026-09-30T09:00:00+02:00"}).status_code == 200,
      "heure avec fuseau acceptée")

fin("banc-horsligne")
