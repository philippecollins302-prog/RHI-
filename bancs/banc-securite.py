"""Les correctifs de la revue de sécurité du 29/09/2026, un par un.

Avant d'ouvrir RHI sur Internet : les codes échouent FERMÉS (un seul code
posé ouvrait tout le bureau), on ne devine plus un code à la chaîne, un
CSV ne porte pas de formule, un fichier monstre ne couche pas le serveur,
une date illisible n'est plus une 500, et un geste rejoué ne rouvre pas une
semaine validée.
"""
import datetime as dt
import io
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "CC_APP_ID", "RHI_PRODUCTION"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402
from rhi import lecture  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 28, 7, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)


def codes(terrain=None, bureau=None, prod=False):
    for k, v in (("RHI_CODE_TERRAIN", terrain), ("RHI_CODE_BUREAU", bureau), ("RHI_PRODUCTION", prod and "1")):
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    appli.ECHECS.clear()


# ── Les codes échouent fermés ──
codes()
verif(c.get("/api/personnes").status_code == 200, "développement, aucun code : ouvert")
codes(prod=True)
r = c.get("/api/personnes")
verif(r.status_code == 503 and "aucun code" in r.json()["detail"], "production sans code : fermé")
codes(terrain="atelier")
r = c.get("/api/sauvegarde")
verif(r.status_code == 503 and "RHI_CODE_BUREAU" in r.json()["detail"],
      "un seul code posé : le bureau n'est plus ouvert à tous")
codes(bureau="bureau")
verif(c.get("/api/personnes").status_code == 503, "code terrain absent : fermé aussi")
codes(terrain="meme", bureau="meme")
verif(c.get("/api/rhi").status_code == 503, "codes identiques : le terrain serait bureau, refusé")
codes(terrain="atelier", bureau="court", prod=True)
r = c.get("/api/rhi", headers={"X-RHI-Code": "court"})
verif(r.status_code == 200, "production : un code bureau court ouvre le site (pas de longueur minimale)")
codes(terrain="meme", bureau="meme", prod=True)
s = c.get("/api/sante").json()
verif(s["codes"] == "à régler" and s["pret"] is False, "la santé publique dit que les codes sont à régler")
verif(set(s) == {"ok", "heure", "pret", "codes", "version"}, "et rien d'autre : ni clé, ni courrier, ni chemin")
os.environ["COMMIT_ID"] = "abc1234"
verif(c.get("/api/sante").json()["version"] == "abc1234", "la santé dit quel commit tourne (COMMIT_ID de Clever)")
os.environ.pop("COMMIT_ID")
verif(c.get("/api/sante").json()["version"] == "inconnue", "sans COMMIT_ID : « inconnue », jamais un commit inventé")

BUREAU = "un-code-bureau-long"
codes(terrain="atelier", bureau=BUREAU, prod=True)
verif(c.get("/api/sante").json()["codes"] == "ok", "codes bien réglés : ok")
verif(c.get("/api/sante/detail").status_code == 401, "le détail de santé : bureau seulement")
d = c.get("/api/sante/detail", headers={"X-RHI-Code": BUREAU}).json()
verif(d["codes_acces"] == "ok", "le détail, avec le code")

# ── On ne devine plus un code à la chaîne ──
for i in range(10):
    c.get("/api/rhi", headers={"X-RHI-Code": f"faux{i}", "X-Forwarded-For": "1.2.3.4, 9.9.9.9"})
r = c.get("/api/rhi", headers={"X-RHI-Code": BUREAU, "X-Forwarded-For": "5.5.5.5, 9.9.9.9"})
verif(r.status_code == 429, "dix codes faux en une minute : même le bon attend (adresse vue par le proxy)")
r = c.get("/api/rhi", headers={"X-RHI-Code": BUREAU, "X-Forwarded-For": "9.9.9.8"})
verif(r.status_code == 200, "une autre adresse n'est pas punie")
appli.ECHECS.clear()
verif(c.get("/api/rhi", headers={"X-RHI-Code": BUREAU, "X-Forwarded-For": "9.9.9.9"}).status_code == 200,
      "la minute passée, le bon code repasse")
codes()

# ── Dates illisibles : 422, pas 500 ──
for url in ("/api/rhi?semaine=demain", "/api/menu?personne=A&jour=2026-13-45", "/api/ecran?jour=x"):
    verif(c.get(url).status_code == 422, f"date illisible → 422 : {url}")

# ── Bornes des gestes ──
r = c.post("/api/demarrer", json={"personnes": ["X" * 61], "motif": "RANGEMENT"})
verif(r.status_code == 422, "un nom de 61 caractères : refusé")
r = c.post("/api/demarrer", json={"personnes": [f"P{i}" for i in range(7)], "motif": "RANGEMENT"})
verif(r.status_code == 422, "sept personnes d'un geste : refusé (chef + binôme, pas une foule)")

# ── Le CSV ne porte pas de formule ──
r = c.post("/api/demarrer", json={"personnes": ["=HYPERLINK(1)"], "motif": "AUTRE", "libelle": "@SOMME(A1)"})
verif(r.status_code == 200, "le nom passe (la tablette ne juge pas)")
heure["t"] = dt.datetime(2026, 9, 28, 9, 0)
c.post("/api/arreter", json={"personnes": ["=HYPERLINK(1)"]})
texte = c.get("/api/rhi.csv?semaine=2026-09-28").text
verif("'=HYPERLINK(1)" in texte and "\n=HYPERLINK" not in texte, "une formule sort désamorcée dans le CSV")

# ── Fichiers monstres ──
r = c.post("/api/plannings", files={"fichier": ("gros.xlsx", b"0" * (appli.TAILLE_MAX + 1))})
verif(r.status_code == 413, "plus de 20 Mo : 413")
bombe = io.BytesIO()
with zipfile.ZipFile(bombe, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("xl/worksheets/sheet1.xml", b"\0" * (lecture.DEPLIE_MAX + 1))
r = c.post("/api/plannings", files={"fichier": ("bombe.xlsx", bombe.getvalue())})
verif(r.status_code == 422 and "anormalement gros" in r.json()["detail"],
      f"un zip qui se déplie en plus de 200 Mo : refusé avant d'être ouvert ({len(bombe.getvalue())} octets envoyés)")
verif(c.post("/api/plannings", files={"fichier": ("v.xls", b"pas un zip")}).status_code == 422,
      "un fichier qui n'est pas un zip : 422")

# ── Un geste rejoué ne rouvre pas une semaine validée ──
heure["t"] = dt.datetime(2026, 9, 28, 16, 0)
c.post("/api/demarrer", json={"personnes": ["ZOE"], "motif": "RANGEMENT"})
heure["t"] = dt.datetime(2026, 9, 28, 17, 0)
c.post("/api/arreter", json={"personnes": ["ZOE"]})
r = c.post("/api/validations", json={"personne": "ZOE", "semaine": "2026-09-28", "qui": "bureau"})
verif(r.status_code == 200, "semaine de ZOE validée")
heure["t"] = dt.datetime(2026, 10, 5, 8, 0)
r = c.post("/api/demarrer", json={"personnes": ["ZOE"], "motif": "RANGEMENT", "quand": "2026-10-03T10:00:00"})
verif(r.status_code == 409 and "validée" in r.json()["detail"],
      "un geste hors ligne du samedi, rejoué lundi : refusé, la semaine est relue")
r = c.post("/api/demarrer", json={"personnes": ["ZOE"], "motif": "RANGEMENT"})
verif(r.status_code == 200, "le geste de la semaine en cours, lui, passe")
heure["t"] = dt.datetime(2026, 9, 30, 8, 0)   # retour dans la semaine validée, en direct
r = c.post("/api/demarrer", json={"personnes": ["ZOE"], "motif": "RANGEMENT"})
verif(r.status_code == 200, "en direct dans la semaine validée : jamais bloqué (le terrain ne l'est jamais)")

fin("banc-securite")
