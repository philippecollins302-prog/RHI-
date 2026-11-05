"""Les comptes InterFast : l'API REST d'abord, le MCP en repli, toujours bornés.

Le 05/11/2026, des comptes créés le jour même (ids vers 31 869) côtoyaient les
anciens (vers 23 722) : la relecture par le MCP balayait toute la plage entre
les deux, ~8 000 lectures en série, et le proxy coupait la requête sans un mot.
Faux serveurs, noms inventés, aucune lecture réelle."""
import asyncio
import io
import json
import logging
import os
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
CLE = "cle-de-banc-7f3a9c"
os.environ["INTERFAST_VIP"] = CLE
os.environ.pop("RHI_ENTREPRISE", None)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU"):
    os.environ.pop(k, None)

# Tout ce qui s'écrit au journal, httpx compris, pour y chercher la clé.
journal = io.StringIO()
gestion = logging.StreamHandler(journal)
gestion.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(gestion)
logging.getLogger().setLevel(logging.DEBUG)

from rhi import interfast  # noqa: E402
import app as appli  # noqa: E402

PRENOMS = ["Paul", "Jean", "Luc", "Zoe", "Marc", "Nina", "Theo", "Lea"]


def compte(i):
    return {"id": i, "firstName": PRENOMS[i % 8], "lastName": f"Essai{i}", "role": "technician",
            "archived": i % 50 == 0, "hourlyCost": 30 if i % 7 == 0 else 0}


messages = []          # tout texte rendu par RHI : exceptions, réponses de la route


def lancer(coro):
    try:
        return asyncio.run(coro)
    except interfast.InterFastIndisponible as e:
        messages.append(str(e))
        raise


class Faux:
    """Un InterFast joué : REST (GET /v1/users) et MCP (POST /mcp/http)."""

    def __init__(self, rest, existants, visibles, rest_ignore_page=False):
        self.rest, self.existants, self.visibles = rest, existants, visibles
        self.rest_ignore_page = rest_ignore_page
        self.rest_vus, self.mcp_vus, self.urls = [], [], []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.urls.append(str(req.url))
        if req.method == "GET" and req.url.path == "/v1/users":
            self.rest_vus.append(dict(req.url.params))
            verif(req.headers.get("X-API-KEY") == CLE, "REST : la clé part dans l'en-tête X-API-KEY")
            verif(CLE not in str(req.url), "REST : la clé n'est jamais dans l'adresse")
            if isinstance(self.rest, int):
                return httpx.Response(self.rest, json={"message": "refus"})
            if self.rest == "illisible":
                return httpx.Response(200, text="<html>Connexion</html>")
            page = 0 if self.rest_ignore_page else int(req.url.params["page"])
            taille = int(req.url.params["size"])
            ids = sorted(self.existants)[page * taille:(page + 1) * taille]
            return httpx.Response(200, json={"items": [compte(i) for i in ids]})
        corps = json.loads(req.content)
        args = corps["params"]["arguments"]
        verif(corps["params"]["name"] == "appeler_api" and args["methode"] == "GET", "MCP : lecture seulement")
        self.mcp_vus.append(args["chemin"])
        if args["chemin"] == "/v1/users":
            # Comme le vrai MCP : liste triée par nom, coupée vers 4 000 caractères.
            texte = "📥 **GET /v1/users**\n\n```json\n" + json.dumps(
                {"items": [compte(i) for i in self.visibles]}, indent=2) + "\n… (tronqué)\n```"
        else:
            uid = int(args["chemin"].rsplit("/", 1)[1])
            texte = ("📥 **GET**\n\n```json\n" + json.dumps(compte(uid), indent=2) + "\n```"
                     if uid in self.existants else
                     "L'API a renvoyé une erreur 404 : ```json {\"code\": 404, "
                     "\"message\": \"Le profil utilisateur n'existe pas\"}```")
        res = {"content": [{"type": "text", "text": texte}]}
        return httpx.Response(200, text="data: " + json.dumps({"result": res}) + "\n\n")

    def lectures_mcp(self):
        return [int(c.rsplit("/", 1)[1]) for c in self.mcp_vus if c != "/v1/users"]


# Deux lots de comptes, comme le 05/11/2026 : les anciens vers 23 7xx (avec un
# trou), les nouveaux vers 31 8xx. 100 + 6 comptes : deux pages REST.
ANCIENS = [i for i in range(23_700, 23_806) if i not in (23_740, 23_741, 23_760, 23_761, 23_762, 23_763)]
NOUVEAUX = [31_865, 31_866, 31_867, 31_869, 31_870, 31_871]
TOUS = set(ANCIENS) | set(NOUVEAUX)

# ── 1. REST paginée : tout est lu en deux pages, aucune lecture MCP ──
f = Faux(rest=None, existants=TOUS, visibles=[23_722, 31_869])
lus = lancer(interfast.utilisateurs(httpx.MockTransport(f)))
verif(len(TOUS) == 106 and [u["id"] for u in lus] == sorted(TOUS), f"tous les comptes lus : {len(lus)}")
verif([p["page"] for p in f.rest_vus] == ["0", "1"] and all(p["size"] == "100" for p in f.rest_vus),
      f"deux pages de 100, puis la page incomplète arrête : {f.rest_vus}")
verif(f.mcp_vus == [], "REST qui répond : aucune lecture par le MCP")
verif(lus[0] == interfast._fiche_utilisateur(compte(lus[0]["id"])) and set(lus[0]) ==
      {"id", "prenom", "nom", "role", "archive", "cout"}, "même fiche qu'avant (_fiche_utilisateur)")
verif(any(u["archive"] for u in lus) and any(u["cout"] == 30 for u in lus), "archivé et coût repris")

# Page pleine pile : la page suivante, vide, arrête.
f = Faux(rest=None, existants=set(range(500, 600)), visibles=[])
lus = lancer(interfast.utilisateurs(httpx.MockTransport(f)))
verif(len(lus) == 100 and len(f.rest_vus) == 2, f"100 comptes : une page pleine puis une vide ({len(f.rest_vus)})")

# Une API qui ignorerait `page` rendrait la même page vingt fois : on s'arrête.
f = Faux(rest=None, existants=TOUS, visibles=[], rest_ignore_page=True)
lus = lancer(interfast.utilisateurs(httpx.MockTransport(f)))
verif(len(f.rest_vus) == 2 and len(lus) == 100, f"page sans id nouveau : arrêt ({len(f.rest_vus)} pages)")

# Garde des 20 pages.
f = Faux(rest=None, existants=set(range(1, 2_502)), visibles=[])
try:
    lancer(interfast.utilisateurs(httpx.MockTransport(f)))
    verif(False, "plus de 20 pages : refus attendu")
except interfast.InterFastIndisponible as e:
    verif(len(f.rest_vus) == 20 and "20 pages" in str(e) and f.mcp_vus == [], f"20 pages au plus : {e}")

# ── 2. REST en 401 : repli MCP, graines éloignées, deux grappes, ≤ 300 lectures ──
verif(interfast.grappes([31_869, 23_722, 23_730], 12) == [[23_722, 23_730], [31_869]],
      "deux graines à plus de 2 × trou : deux grappes")
verif(interfast.grappes([100, 124, 149], 12) == [[100, 124], [149]], "24 = 2 × trou : même grappe ; 25 : non")
f = Faux(rest=401, existants=TOUS, visibles=[23_722, 31_869])
lus = lancer(interfast.utilisateurs(httpx.MockTransport(f)))
lectures = f.lectures_mcp()
verif(len(f.rest_vus) == 1, "REST refusée dès la première page : pas d'autre page")
verif(len(lectures) <= 300, f"au plus 300 lectures : {len(lectures)}")
verif(len(lectures) == len(set(lectures)), "aucun id lu deux fois")
verif(not any(23_900 < i < 31_800 for i in lectures), "rien n'est lu entre les deux grappes")
ids = {u["id"] for u in lus}
verif(set(NOUVEAUX) <= ids, f"la grappe des nouveaux est trouvée : {sorted(ids & set(NOUVEAUX))}")
# Autour de 23 722 : la grappe s'étend jusqu'à 12 absents d'affilée — le trou
# de 4 (23 760-23 763) est franchi, la fin du lot (23 805) atteinte.
verif(set(ANCIENS) <= ids, f"la grappe des anciens est trouvée en entier : {len(ids & set(ANCIENS))}/{len(ANCIENS)}")
verif(lus[0] == interfast._fiche_utilisateur(compte(lus[0]["id"])), "repli : même fiche")

for refus in (403, 404, "illisible"):
    f = Faux(rest=refus, existants=TOUS, visibles=[31_869])
    lus = lancer(interfast.utilisateurs(httpx.MockTransport(f)))
    verif(f.mcp_vus and {u["id"] for u in lus} == set(NOUVEAUX), f"REST {refus} : repli sur le MCP")

for panne in (429, 500, 502):
    f = Faux(rest=panne, existants=TOUS, visibles=[31_869])
    try:
        lancer(interfast.utilisateurs(httpx.MockTransport(f)))
        verif(False, f"REST {panne} : erreur attendue")
    except interfast.InterFastIndisponible as e:
        verif(f.mcp_vus == [] and str(panne) in str(e), f"REST {panne} : dit, sans repli de 30 s ({e})")

# ── 3. Le plafond borne TOUT le balayage, première boucle comprise ──
# Des graines tous les 20 ids : une seule grappe de 400 ids — l'ancien code
# la lisait en entier avant même de regarder son plafond.
semis = list(range(1_000, 1_401, 20))
f = Faux(rest=401, existants=set(semis), visibles=semis)
try:
    lancer(interfast.utilisateurs(httpx.MockTransport(f)))
    verif(False, "plage de 400 ids : plafond attendu")
except interfast.InterFastIndisponible as e:
    verif(len(f.lectures_mcp()) == 300, f"300 lectures, pas une de plus : {len(f.lectures_mcp())}")
    verif("Plafond de 300 lectures" in str(e) and "1000" in str(e) and "1400" in str(e), f"message clair : {e}")

# ── 4. La route : 90 s au plus, puis une erreur dite au bureau ──
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)
verif(appli.DELAI_UTILISATEURS == 90, "délai de la route : 90 s")
f = Faux(rest=None, existants=TOUS, visibles=[])
appli.app.state.transport_interfast = httpx.MockTransport(f)
r = c.post("/api/interfast/utilisateurs")
verif(r.status_code == 200 and len(c.get("/api/interfast/utilisateurs").json()) == 106,
      f"la route relit par la REST : {r.status_code}")


async def lent(req):
    await asyncio.sleep(2)
    return httpx.Response(200, json={"items": []})

appli.app.state.transport_interfast = httpx.MockTransport(lent)
appli.app.state.delai_utilisateurs = 0.2
r = c.post("/api/interfast/utilisateurs")
messages.append(r.text)
verif(r.status_code == 504 and "trop longue" in r.json()["detail"], f"délai dépassé : 504 dit ({r.text})")
del appli.app.state.delai_utilisateurs

f = Faux(rest=401, existants=set(semis), visibles=semis)
appli.app.state.transport_interfast = httpx.MockTransport(f)
r = c.post("/api/interfast/utilisateurs")
messages.append(r.text)
verif(r.status_code == 503 and "Plafond" in r.json()["detail"], f"plafond : 503 dit au bureau ({r.status_code})")

# ── 5. La clé : nulle part ──
trace = journal.getvalue()
verif("HTTP Request" in trace and "/mcp/http" in trace, "le journal de httpx a bien été capté (sinon rien n'est prouvé)")
verif(CLE not in trace, "la clé n'est dans aucun journal (l'adresse du MCP est masquée)")
verif(messages and not any(CLE in m for m in messages), "la clé n'est dans aucun message")

fin("banc-comptes-interfast")
