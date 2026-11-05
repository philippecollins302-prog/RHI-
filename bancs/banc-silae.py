"""Les personnes viennent de Silae, pas du planning (04/11/2026).

Silae (route RHI de mcp.vipplus.com) liste TOUS les salariés de l'entité :
il ne crée personne, il propose ; le bureau valide chaque rattachement d'un
nom du planning, ou le marque « ne pointe pas ». Un nom sans alias pointe
quand même (« jamais bloqué », décision du 05/11/2026) et attend dans « À
rattacher ». Une lecture ratée ne vide jamais la table. Sans RHI_SILAE_URL
(Alfa), l'import fait comme avant. Faux serveurs : aucun appel réseau réel."""
import datetime as dt
import os
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from bancs import fabrique
from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "RHI_PLANNINGS_URL"):
    os.environ.pop(k, None)
SECRET = "secret-silae-0123456789"
SILAE = "https://mcp.exemple.test/rhi/salaries?dossiers=VIPPLUS,MELMAR,REGA"
os.environ.update({"RHI_GRAPH_TENANT": "tenant-fictif", "RHI_GRAPH_CLIENT_ID": "client-fictif",
                   "RHI_GRAPH_SECRET": SECRET, "RHI_SILAE_URL": SILAE})

import app as appli  # noqa: E402
from rhi import base, entra  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 28, 7, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)
db = base.connexion(tmp / "rhi.db")


def sal(dossier, matricule, nom, prenom, emploi):
    return {"dossier": dossier, "matricule": matricule, "nom": nom, "prenom": prenom, "intitule_emploi": emploi,
            "etablissement": "SIEGE", "date_entree": "2020-01-06", "date_sortie": None}


# Salariés fictifs : deux « Jean » dans deux entités, un « PAUL » de nom.
SALARIES = [sal("VIPPLUS", "00101", "DURAND", "Paul", "Serrurier"),
            sal("VIPPLUS", "00102", "BERNARD", "Jean", "Soudeur"),
            sal("REGA", "00301", "MARTIN", "Jean", "Chef de chantier"),
            sal("MELMAR", "00201", "PAUL", "Martin", "Conducteur de travaux"),
            sal("VIPPLUS", "00103", "LEROY", "Hugo", "Plieur")]
silae = {"code": 200, "corps": SALARIES}
appels = []


def serveurs(req: httpx.Request) -> httpx.Response:
    appels.append((req.method, req.url.host, req.headers.get("authorization")))
    if req.url.host == "login.microsoftonline.com":
        return httpx.Response(200, json={"access_token": "jeton-silae-fictif", "expires_in": 3600})
    if req.url.host == "mcp.exemple.test":
        if req.headers.get("authorization") != "Bearer jeton-silae-fictif":
            return httpx.Response(401)
        return httpx.Response(silae["code"], json=silae["corps"])
    return httpx.Response(599)


entra.TRANSPORT = httpx.MockTransport(serveurs)


def nb_salaries():
    return db.execute("SELECT COUNT(*) FROM salaries").fetchone()[0]


def tablette():
    return {p["nom"] for p in c.get("/api/personnes").json()}


def importer_atelier(chemin):
    r = c.post("/api/plannings", files={"fichier": ("ate.xlsx", chemin.read_bytes())})
    verif(r.status_code == 200, f"import du planning : {r.text}")


# ── Lecture ──
r = c.post("/api/silae/relire")
verif(r.status_code == 200 and r.json() == {"salaries": 5, "nouveaux": 5, "partis": 0}, f"lecture : {r.text}")
verif(nb_salaries() == 5, "cinq salariés en base")
verif(("GET", "mcp.exemple.test", "Bearer jeton-silae-fictif") in appels, "lu en GET, avec le jeton du scope Silae")
verif(db.execute("SELECT COUNT(*) FROM personnes").fetchone()[0] == 0, "Silae ne crée AUCUNE personne")
s = c.get("/api/silae").json()
verif(s["actif"] and s["configure"] and s["lecture"]["statut"] == "lu : 5 salariés", f"le bureau voit la lecture : {s['lecture']}")

# ── Relecture inchangée ──
r = c.post("/api/silae/relire").json()
verif(r == {"salaries": 5, "nouveaux": 0, "partis": 0}, f"relecture inchangée : {r}")

# ── Échecs : la table n'est jamais vidée ──
for code, mot in ((502, "incomplète"), (403, "RHI.Salaries.Read"), (401, "jeton refusé"), (500, "500")):
    silae["code"] = code
    r = c.post("/api/silae/relire")
    verif(r.status_code == 503 and mot in r.json()["detail"], f"{code} : dit au bureau : {r.text}")
    verif(nb_salaries() == 5, f"{code} : la table est intacte")
silae["code"] = 200
for corps, quoi in (([], "liste vide"), ({"erreur": "x"}, "pas une liste"),
                    ([SALARIES[0] | {"mel": "x@exemple.fr"}], "un champ hors contrat"),
                    ([SALARIES[0] | {"dossier": "ALLTSION"}], "un dossier inconnu"),
                    ([SALARIES[0], SALARIES[0]], "un matricule en double")):
    silae["corps"] = corps
    r = c.post("/api/silae/relire")
    verif(r.status_code == 503 and nb_salaries() == 5, f"{quoi} : refusé, table intacte : {r.text}")
lec = c.get("/api/silae").json()["lecture"]
verif(lec["reussie_le"] and "Silae" in lec["statut"], f"la dernière réussite reste datée, l'échec est dit : {lec}")
silae["corps"] = SALARIES
c.post("/api/silae/relire")

# ── Import d'un planning : les noms sans alias pointent, et attendent ──
fabrique.atelier(tmp / "ate.xlsx")
importer_atelier(tmp / "ate.xlsx")
attente = {n["nom_planning"]: n for n in c.get("/api/silae").json()["a_rattacher"]}
verif({"PAUL", "JEAN"} <= set(attente), f"PAUL et JEAN sont à rattacher : {sorted(attente)}")
verif(attente["JEAN"]["genre"] == "atelier" and attente["JEAN"]["nb_cases"] > 0, f"genre et cases : {attente['JEAN']}")
verif({"PAUL", "JEAN"} <= tablette(), "jamais bloqué : un nom sans alias pointe quand même")
p = db.execute("SELECT dossier, matricule FROM personnes WHERE nom='JEAN'").fetchone()
verif(tuple(p) == (None, None), "un nom sans alias n'est rattaché à personne : ni dossier, ni matricule")

# ── Proposition automatique, intitulé d'emploi à côté ──
prop = attente["JEAN"]["proposition"]
verif(prop["prenom"] == "Jean" and prop["autres_candidats"] == 1 and prop["intitule_emploi"],
      f"JEAN : un Jean proposé, l'autre signalé, l'emploi montré : {prop}")
prop = attente["PAUL"]["proposition"]
verif(prop and (prop["prenom"] == "Paul" or prop["nom"] == "PAUL"), f"PAUL : même prénom ou même nom : {prop}")

# ── Import CSV d'alias ──
csv = ("nom_planning;dossier;matricule;ne_pointe_pas\n"
       "bernard ;VIPPLUS;00102;0\n"
       "LUC & MARC;;;1\n"
       "FANTOME;REGA;99999;0\n"
       "SANS DOSSIER;;;\n")
r = c.post("/api/alias/csv", json={"csv": csv}).json()
verif(r["appliques"] == 2 and [e["ligne"] for e in r["erreurs"]] == [4, 5], f"deux lignes appliquées, deux dites : {r}")
verif(db.execute("SELECT dossier, matricule FROM alias WHERE nom_planning='BERNARD'").fetchone()[:] == ("VIPPLUS", "00102"),
      "le nom est remis au propre, le matricule garde ses zéros")
verif(c.post("/api/alias/csv", json={"csv": "nom;dossier\nA;B"}).status_code == 422, "mauvais en-tête : refusé")
verif("BERNARD" not in tablette() and "LUC & MARC" not in tablette(),
      "un alias préparé d'avance n'ajoute personne aux tablettes : la fiche naît au planning")

# BERNARD Jean a maintenant un alias : pour JEAN, l'autre Jean (sans alias) passe devant.
prop = {n["nom_planning"]: n for n in c.get("/api/silae").json()["a_rattacher"]}["JEAN"]["proposition"]
verif((prop["dossier"], prop["matricule"]) == ("REGA", "00301") and prop["intitule_emploi"] == "Chef de chantier",
      f"un salarié sans alias est préféré, son emploi permet de voir l'homonyme d'une autre BU : {prop}")

# ── Rattachement manuel ──
r = c.post("/api/alias", json={"nom": "JEAN", "dossier": "VIPPLUS", "matricule": "00102"})
verif(r.status_code == 200 and r.json()["salarie"] == "Jean BERNARD", f"JEAN rattaché à la main : {r.text}")
verif(tuple(db.execute("SELECT dossier, matricule FROM personnes WHERE nom='JEAN'").fetchone()) == ("VIPPLUS", "00102"),
      "la personne porte son dossier et son matricule")
verif("JEAN" not in {n["nom_planning"] for n in c.get("/api/silae").json()["a_rattacher"]}, "JEAN sort de la liste")
verif(c.post("/api/alias", json={"nom": "PAUL", "dossier": "VIPPLUS", "matricule": "77777"}).status_code == 422,
      "un matricule inconnu de Silae : refusé")

# ── « Ne pointe pas » ──
r = c.post("/api/alias", json={"nom": "PAUL", "ne_pointe_pas": True})
verif(r.status_code == 200 and "PAUL" not in {n["nom_planning"] for n in c.get("/api/silae").json()["a_rattacher"]},
      "PAUL ne pointe pas : sorti de la liste")
verif("PAUL" not in tablette(), "et retiré des tablettes")
verif(db.execute("SELECT COUNT(*) FROM personnes WHERE nom='PAUL'").fetchone()[0] == 1, "sa fiche reste (désactivée)")

# Le planning est réimporté : rien ne revient, les cases suivent l'alias.
fabrique.atelier(tmp / "ate2.xlsx")
importer_atelier(tmp / "ate2.xlsx")
attente = {n["nom_planning"] for n in c.get("/api/silae").json()["a_rattacher"]}
verif("PAUL" not in attente and "JEAN" not in attente, f"réimport : PAUL et JEAN ne reviennent pas : {attente}")
verif("PAUL" not in tablette(), "réimport : PAUL n'est pas réactivé")
verif(db.execute("SELECT COUNT(*) FROM planning WHERE personne='JEAN'").fetchone()[0] > 0,
      "les cases de JEAN, nom brut, sont celles de la personne rattachée")
verif(tuple(db.execute("SELECT dossier, matricule FROM personnes WHERE nom='JEAN'").fetchone()) == ("VIPPLUS", "00102"),
      "réimport : le rattachement tient")

# ── L'intérimaire garde le chemin actuel ──
r = c.post("/api/personnes", json={"nom": "Dupont Alex", "equipe": "pose"}).json()
verif(r["interim"] == 1 and r["dossier"] == "INTERIM" and r["matricule"] is None, f"intérimaire : INTERIM, sans matricule : {r}")
verif("DUPONT ALEX" in tablette(), "il est aussitôt sur les tablettes")

# ── Santé : oui/non et des comptes, rien de sensible ──
d = c.get("/api/sante/detail").json()
verif(d["silae"] == {"configure": True, "jeton_ok": True, "salaries": 5,
                     "a_rattacher": len(c.get("/api/silae").json()["a_rattacher"])}, f"santé Silae : {d['silae']}")
verif(d["graph_plannings"] == {"configure": False, "jeton_ok": False}, f"aucun lien Graph posé : {d['graph_plannings']}")
for secret in (SECRET, "jeton-silae", "mcp.exemple.test", "client-fictif", "tenant-fictif"):
    verif(secret not in str(d) + str(c.get("/api/silae").json()), f"« {secret} » n'apparaît pas")

# ── Rien n'est écrit dans Silae ──
verif({m for m, h, _ in appels if h == "mcp.exemple.test"} == {"GET"}, "Silae n'est jamais appelé qu'en lecture")

# ── Sans RHI_SILAE_URL (Alfa) : l'import fait comme avant ──
os.environ.pop("RHI_SILAE_URL")
db.execute("DELETE FROM personnes WHERE nom='HUGO'")
db.execute("DELETE FROM noms_a_rattacher")
db.commit()
importer_atelier(tmp / "ate2.xlsx")
verif(c.get("/api/silae").json()["a_rattacher"] == [], "sans Silae, rien ne va dans « À rattacher »")
verif(not c.get("/api/silae").json()["actif"], "et le bureau ne montre pas la section")
verif("JEAN" in tablette(), "les noms du planning pointent comme avant")
verif(c.post("/api/silae/relire").status_code == 503, "relire Silae sans URL : dit, pas de plantage")

fin("banc-silae")
