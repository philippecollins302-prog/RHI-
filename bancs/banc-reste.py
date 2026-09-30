"""Le reste à faire au point d'affaire (Alexis, 30/09/2026).

« Le chargé d'affaires estime le reste à faire ; engagé + reste face au
chiffrage = dérapage. » Le reste estimé fond à mesure qu'on pointe ; une
estimation toute consommée est dite dépassée ; chaque estimation est gardée."""
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
from rhi import base  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 28, 16, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)
db = base.connexion(tmp / "rhi.db")
t = lambda j, h: dt.datetime(2026, 9, j, h)  # noqa: E731
with db:
    db.execute("""INSERT INTO affaires(ch, chantier, conduc, heures_prevues, source, maj)
                  VALUES ('CH00901', 'LES PINS', 'AA', 20, 'planning', '')""")
    db.execute("INSERT INTO personnes(nom, equipe) VALUES ('PAUL', 'atelier')")
base.demarrer(db, ["PAUL"], t(28, 7), ch="CH00901")
base.arreter(db, ["PAUL"], t(28, 15))

raf = c.get("/api/affaires/CH00901").json()["reste_a_faire"]
verif(raf["engage"] == 8 and raf["reste"] is None and raf["niveau"] is None,
      f"sans estimation : l'engagé, rien d'inventé : {raf}")
verif(raf["reference"] == 20 and raf["reference_nature"] == "prévu fab", "à défaut de chiffrage : le prévu fab")

# ── Refus ──
verif(c.post("/api/affaires/CH00901/reste", json={"heures": 10, "qui": " "}).status_code == 409,
      "une estimation se signe")
verif(c.post("/api/affaires/CH00901/reste", json={"heures": -3, "qui": "AA"}).status_code == 409,
      "un reste négatif : refusé")
verif(c.post("/api/affaires/CH00901/reste", json={"heures": "beaucoup", "qui": "AA"}).status_code == 422,
      "un reste qui n'est pas un nombre : refusé")

# ── Première estimation ──
r = c.post("/api/affaires/CH00901/reste", json={"heures": 10, "qui": "AA", "note": "reste la pose"})
raf = r.json()
verif(r.status_code == 200 and raf["projete"] == 18 and raf["derive_pct"] == 90 and raf["niveau"] == "vert",
      f"8 h engagées + 10 h de reste = 18 h sur 20 : dans les clous : {raf}")

# ── Le reste fond quand on pointe ──
heure["t"] = t(29, 16)
base.demarrer(db, ["PAUL"], t(29, 7), ch="CH00901")
base.arreter(db, ["PAUL"], t(29, 13))
raf = c.get("/api/affaires/CH00901").json()["reste_a_faire"]
verif(raf["engage"] == 14 and raf["reste"] == 4 and raf["projete"] == 18 and raf["pointe_depuis"] == 6,
      f"6 h pointées depuis : il en reste 4, le projeté ne bouge pas : {raf}")
verif(not raf["depassee"], "estimation pas encore dépassée")

# Un arrêt oublié ne mange pas le reste (il est « en suspens » au point d'affaire).
base.demarrer(db, ["PAUL"], t(29, 14), ch="CH00901")
heure["t"] = t(30, 20)
raf = c.get("/api/affaires/CH00901").json()["reste_a_faire"]
verif(raf["engage"] == 14, f"arrêt oublié : pas compté dans l'engagé : {raf['engage']}")
with db:
    db.execute("UPDATE pointages SET fin=? WHERE fin IS NULL", (t(29, 20).isoformat(),))

# ── Estimation dépassée ──
raf = c.get("/api/affaires/CH00901").json()["reste_a_faire"]
verif(raf["engage"] == 20 and raf["depassee"] and raf["reste"] == 0 and raf["projete"] == 20,
      f"12 h pointées depuis une estimation de 10 : dépassée, le projeté suit l'engagé : {raf}")

# ── Nouvelle estimation, avec le chiffrage (la pose comprise) ──
raf = c.post("/api/affaires/CH00901/reste", json={"heures": 5, "qui": "AA", "chiffrees": 18}).json()
verif(raf["reference"] == 18 and raf["reference_nature"] == "chiffrage",
      "les heures chiffrées remplacent le prévu fab comme référence")
verif(raf["projete"] == 25 and raf["ecart"] == 7 and raf["derive_pct"] == 139 and raf["niveau"] == "rouge",
      f"25 h projetées sur 18 chiffrées : dérapage de 7 h, rouge : {raf}")
verif([e["heures"] for e in raf["historique"]] == [5, 10] and raf["historique"][1]["note"] == "reste la pose",
      "chaque estimation est gardée, la plus récente d'abord")

liste = {a["ch"]: a for a in c.get("/api/affaires").json()}
a = liste["CH00901"]
verif(a["projete"] == 25 and a["niveau"] == "rouge" and a["reste"] == 5 and a["estime_le"],
      f"la liste des affaires montre le projeté et le dérapage : {a}")

# ── Ambre : entre 100 et 110 % ──
raf = c.post("/api/affaires/CH00901/reste", json={"heures": 0, "qui": "AA", "chiffrees": 19}).json()
verif(raf["derive_pct"] == 105 and raf["niveau"] == "ambre", f"20 h sur 19 : ambre : {raf}")

# Une affaire jamais vue (tapée à la main) reçoit une estimation sans planter.
r = c.post("/api/affaires/CH00977/reste", json={"heures": 12, "qui": "BB", "chiffrees": 10})
verif(r.status_code == 200 and r.json()["niveau"] == "rouge", f"affaire inconnue : créée, estimée : {r.text}")
verif("CH00977" in {a["ch"] for a in c.get("/api/affaires").json()},
      "une affaire chiffrée apparaît dans la liste même sans heure pointée")

fin("banc-reste")
