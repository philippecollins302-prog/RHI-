"""La sauvegarde : une copie par jour, cohérente, gardée 30 jours ; et le
téléchargement au bureau, qui rend une base qu'on peut rouvrir."""
import datetime as dt
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402
from rhi import base  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 29, 8, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"

with TestClient(appli.app) as c:   # le « with » lance le veilleur, comme en production
    c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00901"})
    dossier = tmp / "sauvegardes"
    # Le veilleur tourne dans son fil : on lui laisse jusqu'à 5 s, sans
    # jamais faire la sauvegarde à sa place (le contrôle ne prouverait rien).
    for _ in range(50):
        if (dossier / "rhi-2026-09-29.db").exists():
            break
        time.sleep(0.1)
    verif((dossier / "rhi-2026-09-29.db").exists(), "sauvegarde du jour faite au démarrage, par le veilleur")
    verif(appli.sauvegarde_du_jour() is None, "une seule par jour")

    r = c.get("/api/sauvegarde")
    verif(r.status_code == 200 and r.headers["content-disposition"].startswith('attachment; filename="rhi-'),
          "téléchargement")
    (tmp / "telechargee.db").write_bytes(r.content)
    t = sqlite3.connect(tmp / "telechargee.db")
    verif(t.execute("SELECT personne, ch FROM pointages").fetchall() == [("PAUL", "CH00901")],
          "la copie téléchargée se rouvre et contient le pointage")
    t.close()

# Deux sauvegardes au même instant : une seule copie, aucune erreur.
db = base.connexion(tmp / "rhi.db")
rendus, erreurs = [], []


def sauver():
    try:
        rendus.append(base.sauvegarder(base.connexion(tmp / "rhi.db"), tmp / "course", dt.date(2026, 9, 30)))
    except Exception as e:  # noqa: BLE001
        erreurs.append(e)


fils = [threading.Thread(target=sauver) for _ in range(4)]
for f in fils:
    f.start()
for f in fils:
    f.join()
verif(not erreurs and sum(1 for x in rendus if x) == 1, f"une seule copie, les autres attendent : {rendus} {erreurs}")

# 35 jours plus tard : on garde 30 jours.
db = base.connexion(tmp / "rhi.db")
for i in range(1, 36):
    base.sauvegarder(db, dossier, dt.date(2026, 9, 29) + dt.timedelta(days=i))
restantes = sorted(p.name for p in dossier.glob("rhi-*.db"))
verif(len(restantes) == 31 and restantes[0] == "rhi-2026-10-04.db",
      f"30 jours gardés (+ le jour même) : {restantes[0]} … {len(restantes)}")
verif(not list(dossier.glob("*.tmp")), "aucun fichier provisoire oublié")

os.environ["RHI_CODE_BUREAU"] = "bureau"
os.environ["RHI_CODE_TERRAIN"] = "terrain"
with TestClient(appli.app) as c:
    verif(c.get("/api/sauvegarde", headers={"X-RHI-Code": "terrain"}).status_code == 401,
          "la base entière : bureau seulement")

with TestClient(appli.app) as c:
    s = c.get("/api/sante").json()
    verif(s["base"]["journal"] == "delete", "journal « delete » : le WAL ne marche pas sur le bucket réseau")
    verif(s["base"]["inscriptible"] and s["codes_acces"], "état lisible après déploiement")

fin("banc-sauvegarde")
