"""Les plannings SharePoint lus par Microsoft Graph (04/11/2026).

Un lien graph.microsoft.com part avec un jeton applicatif Entra ; Graph
redirige vers une adresse pré-signée, qui ne doit PAS recevoir le jeton. Les
refus de Graph sont dits en clair (401, 403 Sites.Selected, 404), un lien
Graph sans identifiants ne fait pas tomber les autres, et un lien ordinaire
part toujours sans authentification. Faux serveurs (httpx.MockTransport) :
aucun appel réseau réel."""
import os
import tempfile
from pathlib import Path

import httpx

from bancs import fabrique
from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "RHI_SILAE_URL"):
    os.environ.pop(k, None)
SECRET = "secret-graph-0123456789"
os.environ.update({"RHI_GRAPH_TENANT": "tenant-fictif", "RHI_GRAPH_CLIENT_ID": "client-fictif",
                   "RHI_GRAPH_SECRET": SECRET})
ATE = "https://graph.microsoft.com/v1.0/drives/b!lecteur/items/01ATE/content"
POSE = "https://graph.microsoft.com/v1.0/drives/b!lecteur/items/01POSE/content"
AUTRE = "https://partage.exemple.fr/pose.xlsx?download=1&token=jeton-de-partage"
os.environ["RHI_PLANNINGS_URL"] = f"{ATE}\n{POSE}"

from rhi import base, depot_auto, entra  # noqa: E402

db = base.connexion(tmp / "rhi.db")
fabrique.atelier(tmp / "ate.xlsx")
fabrique.pose(tmp / "pose.xlsx")
fichiers = {"01ATE": (tmp / "ate.xlsx").read_bytes(), "01POSE": (tmp / "pose.xlsx").read_bytes()}
reponse_graph = {}          # identifiant -> code forcé (401, 403, 404)
vus = []                    # (hôte, chemin, Authorization)
jetons = {"n": 0}


def serveurs(req: httpx.Request) -> httpx.Response:
    hote = req.url.host
    vus.append((hote, req.url.path, req.headers.get("authorization")))
    if hote == "login.microsoftonline.com":
        jetons["n"] += 1
        return httpx.Response(200, json={"access_token": f"jeton-graph-{jetons['n']}", "expires_in": 3600})
    if hote == "graph.microsoft.com":
        ident = req.url.path.split("/")[-2]
        if req.headers.get("authorization", "") != f"Bearer jeton-graph-{jetons['n']}":
            return httpx.Response(401)
        if ident in reponse_graph:
            return httpx.Response(reponse_graph[ident])
        if ident not in fichiers:
            return httpx.Response(404)
        # Comme Graph : 302 vers une adresse de téléchargement pré-signée.
        return httpx.Response(302, headers={"Location": f"https://telechargement.sharepoint.exemple/{ident}?sig=x"})
    if hote == "telechargement.sharepoint.exemple":
        return httpx.Response(200, content=fichiers[req.url.path.strip("/")])
    if hote == "partage.exemple.fr":
        return httpx.Response(200, content=fichiers["01POSE"])
    return httpx.Response(599)


entra.TRANSPORT = httpx.MockTransport(serveurs)
ate, pose, autre = (depot_auto.etiquette(u) for u in (ATE, POSE, AUTRE))


def passage():
    return {x["source"]: x for x in depot_auto.relever(db, "VIP")}


# ── 200 : les deux plannings importés, le jeton ne quitte pas Graph ──
r = passage()
verif(r[ate]["statut"].startswith("importé") and r[ate]["nature"] == "atelier", f"atelier par Graph : {r[ate]}")
verif(r[pose]["statut"].startswith("importé") and r[pose]["nature"] == "pose", f"pose par Graph : {r[pose]}")
verif(all(a == f"Bearer jeton-graph-{jetons['n']}" for h, _, a in vus if h == "graph.microsoft.com"),
      "Graph reçoit le jeton")
verif(all(a is None for h, _, a in vus if h == "telechargement.sharepoint.exemple"),
      "l'adresse pré-signée (autre hôte) ne reçoit PAS le jeton")
verif(jetons["n"] == 1, "un seul jeton pour les deux fichiers (gardé en mémoire)")
cases = db.execute("SELECT COUNT(*) FROM planning").fetchone()[0]
verif(cases > 0, "le planning est en base")

# ── Inchangé ──
r = passage()
verif(r[ate]["statut"] == "inchangé" and r[pose]["statut"] == "inchangé", f"inchangés : rien à refaire : {r}")

# ── Modifié et importé ──
import openpyxl  # noqa: E402
wb = openpyxl.load_workbook(tmp / "ate.xlsx")
wb["planning FAB"].cell(7, 2, "LE PORT\nPORTAIL")
wb["planning FAB"].cell(9, 2, "CH00902")
wb.save(tmp / "ate2.xlsx")
fichiers["01ATE"] = (tmp / "ate2.xlsx").read_bytes()
r = passage()
verif(r[ate]["statut"].startswith("importé") and r[pose]["statut"] == "inchangé", f"modifié : réimporté : {r}")
verif(db.execute("SELECT 1 FROM planning WHERE ch='CH00902'").fetchone(), "la modification est arrivée")


def refus(code, attendu):
    reponse_graph["01ATE"] = code
    avant = db.execute("SELECT COUNT(*) FROM planning WHERE origine='atelier'").fetchone()[0]
    r = passage()
    verif(r[ate]["statut"] == attendu, f"{code} : « {attendu} » — lu : {r[ate]['statut']}")
    verif(db.execute("SELECT COUNT(*) FROM planning WHERE origine='atelier'").fetchone()[0] == avant,
          f"{code} : le planning en place n'est pas touché")
    verif(r[pose]["statut"] == "inchangé", f"{code} : l'autre fichier passe quand même")
    del reponse_graph["01ATE"]


refus(403, "Graph : pas de droit lecture sur ce site (Sites.Selected)")
refus(404, "Graph : fichier introuvable (identifiant changé ?)")
n = jetons["n"]
refus(401, "Graph : identifiants refusés")
verif(jetons["n"] == n + 1, "après un 401 de Graph, le jeton gardé est jeté : le fichier suivant en redemande un")

# ── Variables absentes : statut clair, sans planter les autres fichiers ──
os.environ["RHI_PLANNINGS_URL"] = f"{ATE}\n{AUTRE}"
os.environ.pop("RHI_GRAPH_SECRET")
entra.oublier()
vus.clear()
r = passage()
verif("variables RHI_GRAPH_TENANT, RHI_GRAPH_CLIENT_ID, RHI_GRAPH_SECRET absentes" in r[ate]["statut"],
      f"lien Graph sans identifiants : dit : {r[ate]}")
verif(r[autre]["statut"].startswith("importé"), f"le lien ordinaire passe quand même : {r[autre]}")
verif(not any(h == "graph.microsoft.com" for h, _, _ in vus), "sans identifiants, Graph n'est même pas appelé")

# ── Lien non-Graph : inchangé, sans authentification ──
os.environ["RHI_GRAPH_SECRET"] = SECRET
vus.clear()
r = passage()
verif(r[autre]["statut"] == "inchangé", f"lien ordinaire : comme avant : {r[autre]}")
verif([a for h, _, a in vus if h == "partage.exemple.fr"] == [None], "lien ordinaire : aucun jeton envoyé")

# ── Limite de 20 Mo gardée ──
fichiers["01ATE"] = b"0" * (depot_auto.TAILLE_MAX + 1)
r = passage()
verif(r[ate]["statut"].startswith("injoignable"), f"plus de 20 Mo : refusé : {r[ate]}")

# ── Ni jeton, ni secret, ni lien nulle part ──
tout = str([tuple(x) for x in db.execute("SELECT * FROM depots_auto")]) + str(depot_auto.etat(db))
for secret in (SECRET, "jeton-graph", "items/01ATE", "b!lecteur"):
    verif(secret not in tout, f"« {secret} » n'est écrit ni en base ni à l'écran")

fin("banc-depot-graph")
