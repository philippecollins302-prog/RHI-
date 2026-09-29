"""Personnes reliées à InterFast, coûts horaires, validation hebdomadaire.

InterFast joué par un faux serveur ; noms inventés."""
import datetime as dt
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
os.environ["INTERFAST_VIP"] = "cle-de-banc"
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "RHI_COUT_HORAIRE"):
    os.environ.pop(k, None)

# ── Une base d'avant les coûts reçoit ses colonnes sans rien perdre ──
ancienne = tmp / "ancienne.db"
v = sqlite3.connect(ancienne)
v.executescript("""CREATE TABLE personnes (nom TEXT PRIMARY KEY, equipe TEXT NOT NULL,
                   actif INTEGER NOT NULL DEFAULT 1, vu_le TEXT);
                   INSERT INTO personnes(nom, equipe) VALUES ('ANCIEN', 'atelier');""")
v.commit()
v.close()
from rhi import base  # noqa: E402
b = base.connexion(ancienne)
cols = {r[1] for r in b.execute("PRAGMA table_info(personnes)")}
verif({"cout_horaire", "interfast_user_id", "nom_complet"} <= cols, "colonnes ajoutées")
verif(b.execute("SELECT nom FROM personnes").fetchone()[0] == "ANCIEN", "rien de perdu")
# La course de deux requêtes simultanées : la colonne apparaît entre le
# PRAGMA et l'ALTER. Le second ajout doit passer sans erreur.
base.ajouter_colonne(b, "personnes", "cout_horaire", "REAL")
verif(True, "ajout d'une colonne déjà présente : toléré")
b.close()

import app as appli  # noqa: E402

# Des ids contigus avec un trou, comme dans le vrai compte.
UTILISATEURS = [
    {"id": 101, "firstName": "Paul", "lastName": "Martin", "role": "technician", "archived": False, "hourlyCost": 0},
    {"id": 102, "firstName": "Jean", "lastName": "Durand", "role": "technician", "archived": False, "hourlyCost": 38.5},
    {"id": 103, "firstName": "Jean", "lastName": "Petit", "role": "technician", "archived": True, "hourlyCost": 0},
    {"id": 104, "firstName": "Luc", "lastName": "Bernard", "role": "technician", "archived": False, "hourlyCost": 0},
    {"id": 105, "firstName": "Zoe", "lastName": "Aubert", "role": "technician", "archived": False, "hourlyCost": 0},
    {"id": 108, "firstName": "Luc", "lastName": "Moreau", "role": "trainee", "archived": False, "hourlyCost": 0},
]
PAR_ID = {u["id"]: u for u in UTILISATEURS}
vus = []


def repondre(req: httpx.Request) -> httpx.Response:
    corps = json.loads(req.content)
    args = corps["params"]["arguments"]
    vus.append(args["chemin"])
    verif(corps["params"]["name"] == "appeler_api" and args["methode"] == "GET", "lecture seulement")
    if args["chemin"] == "/v1/users":
        # Comme le vrai MCP : liste tronquée après le 2e utilisateur, paramètres ignorés.
        # Triée par nom comme la vraie : Zoe (105) arrive en dernier, après la coupure,
        # et Luc Moreau (108) passe avant elle — 105 est ENTRE deux ids visibles.
        par_nom = sorted(UTILISATEURS, key=lambda u: u["lastName"] != "Martin")
        visibles = [PAR_ID[101], PAR_ID[104], PAR_ID[108], PAR_ID[105]]
        texte = "📥 **GET /v1/users**\n\n```json\n" + json.dumps({"items": visibles}, indent=2)
        texte = texte[:texte.index('"id": 105')] + "\n… (tronqué)\n```"
        del par_nom
    else:
        uid = int(args["chemin"].rsplit("/", 1)[1])
        if uid in PAR_ID:
            texte = "📥 **GET**\n\n```json\n" + json.dumps(PAR_ID[uid], indent=2) + "\n```"
        else:
            texte = "L'API a renvoyé une erreur 404 : ```json {\"code\": 404, \"message\": \"Le profil utilisateur n'existe pas\"}```"
    res = {"content": [{"type": "text", "text": texte}]}
    return httpx.Response(200, text="data: " + json.dumps({"result": res}) + "\n\n")


appli.app.state.transport_interfast = httpx.MockTransport(repondre)
appli.app.state.chemin_base = tmp / "rhi.db"
heure = {"t": dt.datetime(2026, 9, 28, 7, 0)}
appli.app.state.horloge = lambda: heure["t"]
c = TestClient(appli.app)

for n in ("PAUL", "JEAN", "LUC", "ZOE"):
    c.post("/api/demarrer", json={"personnes": [n], "ch": "CH00901"})
heure["t"] = dt.datetime(2026, 9, 28, 11, 0)
c.post("/api/arreter", json={"personnes": ["PAUL", "JEAN", "LUC", "ZOE"]})   # 4 h chacun

# ── Liaison ──
r = c.post("/api/interfast/utilisateurs").json()
lus = [int(x.rsplit("/", 1)[1]) for x in vus if x != "/v1/users"]
verif(sorted(r["liees"]) == ["JEAN", "PAUL", "ZOE"], f"liaisons uniques : {r}")
verif(r["ambigus"] == {"LUC": ["Luc Bernard", "Luc Moreau"]}, "deux Luc : au bureau de trancher")
verif(r["sans_correspondance"] == [], f"Zoé, cachée entre deux ids visibles, est trouvée : {r}")
verif(r["archives"] == {}, "aucun archivé seul")
# Le bureau tranche pour Luc : Luc Moreau (108).
verif(c.patch("/api/personnes/LUC", json={"interfast_user_id": 999}).status_code == 422, "compte inconnu refusé")
c.patch("/api/personnes/LUC", json={"interfast_user_id": 108})
r2 = c.post("/api/interfast/utilisateurs").json()
verif("LUC" in r2["deja_liees"] and "LUC" not in r2["ambigus"], "liaison manuelle respectée à la relecture")
verif(len(c.get("/api/interfast/utilisateurs").json()) == 6, "les comptes sont gardés pour le choix au bureau")
c.patch("/api/personnes/LUC", json={"delier": True})
r2 = c.post("/api/interfast/utilisateurs").json()
verif("LUC" in r2["ambigus"], "déliée : de nouveau ambiguë")
verif({101, 102, 103, 104, 105, 108} <= set(lus), "tous lus : 102, 103 et 105 étaient entre les ids visibles")
verif(max(lus) < 108 + 12 + 6 and min(lus) > 0, f"on s'arrête après 12 absents d'affilée : {sorted(lus)}")
det = {p["nom"]: p for p in c.get("/api/personnes/detail").json()["personnes"]}
verif(det["JEAN"]["nom_complet"] == "Jean Durand" and det["JEAN"]["interfast_user_id"] == 102,
      "Jean relié au compte actif, pas à l'archivé")

# ── Coûts : saisi > InterFast (> 0) > taux moyen ──
verif(det["JEAN"]["cout_retenu"] == 38.5, "coût InterFast repris")
verif(det["PAUL"]["cout_retenu"] is None, "coût InterFast à 0 : pas un coût")
pa = c.get("/api/affaires/CH00901").json()
verif(pa["cout_main_oeuvre"] == 4 * 38.5, f"seul Jean est chiffré : {pa['cout_main_oeuvre']}")
verif(pa["sans_cout"] == ["LUC", "PAUL", "ZOE"], "les non-chiffrés sont nommés, pas comptés à 0 en silence")
os.environ["RHI_COUT_HORAIRE"] = "35"
c.patch("/api/personnes/PAUL", json={"cout_horaire": 42})
pa = c.get("/api/affaires/CH00901").json()
verif(pa["cout_main_oeuvre"] == 4 * (42 + 38.5 + 35 + 35), f"saisi, InterFast, moyen : {pa['cout_main_oeuvre']}")
verif(pa["sans_cout"] == [], "tout le monde chiffré")
c.patch("/api/personnes/PAUL", json={"cout_horaire": 0})
verif(c.get("/api/personnes/detail").json()["personnes"][0] is not None, "")
det = {p["nom"]: p for p in c.get("/api/personnes/detail").json()["personnes"]}
verif(det["PAUL"]["cout_retenu"] == 35, "0 efface le coût saisi : retour au taux moyen")
verif(c.patch("/api/personnes/PAUL", json={"cout_horaire": -3}).status_code == 422, "coût négatif refusé")
liste = {a["ch"]: a for a in c.get("/api/affaires").json()}
verif(liste["CH00901"]["cout_main_oeuvre"] == 4 * (35 + 38.5 + 35 + 35), "coût dans la liste aussi")

# ── Validation ──
heure["t"] = dt.datetime(2026, 9, 29, 7, 0)
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00902"})
r = c.post("/api/validations", json={"personne": "PAUL", "semaine": "2026-09-30", "qui": "Alexis"})
verif(r.status_code == 409 and "ouvert" in r.json()["detail"], "pas de validation avec un pointage ouvert")
heure["t"] = dt.datetime(2026, 9, 29, 9, 0)
c.post("/api/arreter", json={"personnes": ["PAUL"]})
r = c.post("/api/validations", json={"personne": "PAUL", "semaine": "2026-09-30", "qui": "Alexis"})
verif(r.status_code == 200 and r.json()["par"] == "Alexis", "validée")
rhi = c.get("/api/rhi?personne=PAUL&semaine=2026-09-28").json()["releves"][0]
verif(rhi["validee"]["par"] == "Alexis", "le RHI dit qu'il est validé")
pid = rhi["pointages"][0]["id"]
r = c.patch(f"/api/pointages/{pid}", json={"fin": "2026-09-28T12:00"})
verif(r.status_code == 409 and "dévalider" in r.json()["detail"], "semaine validée : correction refusée")
r = c.post("/api/pointages", json={"personne": "PAUL", "ch": "CH00901",
                                   "debut": "2026-09-30T07:00", "fin": "2026-09-30T08:00"})
verif(r.status_code == 409, "ajout dans une semaine validée refusé aussi")
# Déplacer un pointage d'une semaine ouverte VERS la semaine validée : refusé.
autre = c.post("/api/pointages", json={"personne": "PAUL", "ch": "CH00901",
                                       "debut": "2026-10-05T07:00", "fin": "2026-10-05T08:00"}).json()["id"]
verif(c.patch(f"/api/pointages/{autre}", json={"debut": "2026-09-30T07:00"}).status_code == 409,
      "on ne glisse pas un pointage dans une semaine validée")
verif(c.post("/api/pointages", json={"personne": "JEAN", "ch": "CH00901", "debut": "2026-09-30T07:00",
                                     "fin": "2026-09-30T08:00"}).status_code == 200,
      "la validation est par personne : Jean reste corrigeable")
# Le terrain, lui, n'est jamais bloqué.
heure["t"] = dt.datetime(2026, 9, 30, 7, 0)
verif(c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00901"}).status_code == 200,
      "pointer à la tablette dans une semaine validée : accepté (jamais bloqué)")
c.post("/api/arreter", json={"personnes": ["PAUL"]})
t = c.get("/api/rhi.csv?semaine=2026-09-28").text
verif("Validé par" in t and "Alexis le 2026-09-29" in t, "le CSV dit qui a validé")
c.delete("/api/validations?personne=PAUL&semaine=2026-09-28")
verif(c.patch(f"/api/pointages/{pid}", json={"fin": "2026-09-28T12:00"}).status_code == 200,
      "dévalidée : corrigeable de nouveau")

# ── Vers InterFast : une case par CH et par jour, toute l'équipe dessus ──
c.post("/api/validations", json={"personne": "PAUL", "semaine": "2026-09-28", "qui": "Alexis"})
e = c.get("/api/interfast/envois?semaine=2026-09-28").json()
verif(e["ecriture"] is False and e["personnes_validees"] == ["PAUL"], "à blanc")
cases = {x["id"]: x for x in e["cases"]}
c28 = cases["CH00901|2026-09-28"]
verif([g["personne"] for g in c28["equipe"]] == ["PAUL", "JEAN", "LUC", "ZOE"],
      f"une seule case pour les quatre qui ont pointé CH00901 le 28 : {c28['equipe']}")
verif(c28["etat"] == "en attente" and c28["en_attente"] == ["JEAN", "LUC", "ZOE"],
      "la case attend que toute l'équipe soit validée : une case partie incomplète se rattrape à la main")
verif("CH inconnu d'InterFast" in c28["blocages"], "et on dit déjà ce qui la bloquerait")
c30 = cases["CH00901|2026-09-30"]
verif(any("plus de 12 h" in b and "PAUL" in b for b in c30["blocages"]),
      f"un pointage de plusieurs jours ne part pas dans une case : {c30['blocages']}")
base.importer_chantiers(base.connexion(appli.app.state.chemin_base),
                        [{"id": 777, "ch": "CH00901", "titre": "Résidence des Pins", "client": "BAILLEUR SUD",
                          "statut": "En cours"}])
for qui in ("JEAN", "LUC", "ZOE"):
    c.post("/api/validations", json={"personne": qui, "semaine": "2026-09-28", "qui": "Alexis"})
e = c.get("/api/interfast/envois?semaine=2026-09-28").json()
c28 = {x["id"]: x for x in e["cases"]}["CH00901|2026-09-28"]
verif(c28["etat"] == "prête" and c28["client"] == "BAILLEUR SUD" and c28["chantier"] == "Résidence des Pins",
      f"toute l'équipe validée, CH connu : prête — {c28['etat']} {c28['blocages']}")
verif((c28["heure"], c28["fin"], c28["duree"], c28["heures"]) == ("07:00", "12:00", "5h", 17.0),
      f"la case couvre l'équipe de 7 h à 12 h ; 17 h de travail : {c28['heure']} {c28['fin']} {c28['duree']}")
verif(c28["techniciens"] == ["Paul Martin", "Jean Durand", "Zoe Aubert"] and c28["sans_compte"] == ["LUC"],
      "techniciens InterFast par leur nom complet ; celui sans compte est nommé, pas oublié")
verif(e["pretes"] == 1 and e["heures_pretes"] == 17.0, "le total prêt est compté")
verif(c.post("/api/interfast/envois", json={"semaine": "2026-09-28"}).status_code == 403,
      "écriture coupée : l'envoi est refusé, rien n'est tenté")

# La pause : le temps passé ailleurs entre deux morceaux du même CH.
for d_, f_, ch_ in (("07:00", "09:00", "CH00901"), ("09:00", "10:00", "CH00902"), ("10:00", "12:30", "CH00901")):
    c.post("/api/pointages", json={"personne": "JEAN", "ch": ch_, "debut": f"2026-10-06T{d_}", "fin": f"2026-10-06T{f_}"})
c.post("/api/validations", json={"personne": "JEAN", "semaine": "2026-10-05", "qui": "Alexis"})
e = c.get("/api/interfast/envois?semaine=2026-10-05").json()
jean = {x["id"]: x for x in e["cases"]}["CH00901|2026-10-06"]["equipe"][0]
verif((jean["debut"], jean["fin"], jean["pause"], jean["heures"]) == ("07:00", "12:30", "1h", 4.5),
      f"ce qu'il faudra saisir en terminant la case : 7:00 → 12:30, pause 1h, 4h30 : {jean}")
verif(base.duree_texte(4.5) == "4h30" and base.duree_texte(2) == "2h" and base.duree_texte(0.25) == "0h15",
      "durées au format d'InterFast")

# ── Écriture branchée, sur un faux InterFast ──
from rhi import interfast  # noqa: E402
ecrits = []
terminee = {"oui": False}


def entree(num, debut, fin_, minutes):
    """Une entrée de /v1/users/…/timesheets/…/interventions, forme du 29/09/2026."""
    return ('{"id": "0ee5f4cc-f830-4a41-a66f-%012d", "date": "2026-09-27T22:00:00.000Z", '
            '"startHour": "%s", "endHour": "%s", "totalWorkedTime": %d, "breakTime": 0, "cost": 0, '
            '"user": "101", "interventionId": "%d", "intervention": {"id": %d, "finished": true, '
            '"reference": 7, "title": "x", "client": {"id": 1, "reference": 1797}}}'
            % (num, debut, fin_, minutes, num, num))


def lecture(chemin):
    if "/timesheets/2026/" in chemin:
        if not terminee["oui"]:
            return "📥 **GET**\n```json\n[]\n```"
        # Deux interventions ce jour-là, la nôtre en second, coupée comme le fait le MCP.
        corps = "[" + entree(999001, "2026-09-28T04:00:00.000Z", "2026-09-28T05:00:00.000Z", 60) + ", " + \
            entree(555001, "2026-09-28T05:00:00.000Z", "2026-09-28T10:00:00.000Z", 300)[:260]
        return "📥 **GET**\n```json\n" + corps + "\n… (tronqué)\n```"
    if chemin.startswith("/v1/intervention/"):
        n = int(chemin.rsplit("/", 1)[1])
        ref = {999001: 99, 555001: 321}.get(n, 7)
        return ('📥 **GET**\n```json\n{"id": %d, "archived": false, "finished": true, "reference": %d, '
                '"client": {"id": 5, "reference": 1797}}\n```' % (n, ref))
    if chemin == "/v1/interventions/555001/timesheets":
        ts = [{"startHour": "2026-09-28T05:00:00.000Z", "endHour": "2026-09-28T10:00:00.000Z",
               "breakTime": 0, "totalWorkedTime": 300, "user": "101"},
              {"startHour": "2026-09-28T05:00:00.000Z", "endHour": "2026-09-28T09:00:00.000Z",
               "breakTime": 0, "totalWorkedTime": 240, "user": "102"},
              {"startHour": "2026-09-28T05:00:00.000Z", "endHour": "2026-09-28T08:00:00.000Z",
               "breakTime": 0, "totalWorkedTime": 180, "user": "105"}]
        return "📥 **GET**\n```json\n" + json.dumps(ts) + "\n```"
    raise AssertionError(f"lecture inattendue : {chemin}")


reponses = {"planifier_intervention": "📋 Récapitulatif … Confirmez avec confirmer_action.",
            "confirmer_action": "✅ Intervention IN00321 planifiée le 28/09/2026."}


def mcp_ecriture(req: httpx.Request) -> httpx.Response:
    corps = json.loads(req.content)
    nom, args = corps["params"]["name"], corps["params"]["arguments"]
    ecrits.append((nom, args))
    if nom == "appeler_api":
        texte = lecture(args["chemin"])
    else:
        texte = reponses[nom]
    return httpx.Response(200, text="data: " + json.dumps({"result": {"content": [{"type": "text", "text": texte}]}}))


appli.app.state.transport_interfast = httpx.MockTransport(mcp_ecriture)
interfast.ECRITURE = True
try:
    r = c.post("/api/interfast/envois", json={"semaine": "2026-09-28"})
    verif(r.status_code == 200 and r.json()["posees"] == [{"id": "CH00901|2026-09-28", "ref": "IN00321"}],
          f"la case prête est posée et sa référence rendue : {r.text}")
    verif([n for n, _ in ecrits] == ["planifier_intervention", "confirmer_action"], f"deux temps : {ecrits}")
    plan = ecrits[0][1]
    verif(plan == {"client": "BAILLEUR SUD", "chantier": "Résidence des Pins", "date": "2026-09-28",
                   "heure": "07:00", "duree": "5h", "techniciens": ["Paul Martin", "Jean Durand", "Zoe Aubert"],
                   "description": "RHI · CH00901 · pointage"}, f"ce qui part : {plan}")
    verif(ecrits[1][1] == {"confirmation": True}, "confirmation explicite")
    e = c.get("/api/interfast/envois?semaine=2026-09-28").json()
    c28 = {x["id"]: x for x in e["cases"]}["CH00901|2026-09-28"]
    verif(c28["etat"] == "posée" and c28["ref"] == "IN00321", "la case est posée, avec sa référence")
    ecrits.clear()
    r = c.post("/api/interfast/envois", json={"semaine": "2026-09-28"})
    verif(r.json()["posees"] == [] and ecrits == [], "jamais deux fois la même case")
    r = c.delete("/api/validations?personne=ZOE&semaine=2026-09-28")
    verif(r.status_code == 409 and "IN00321" in r.json()["detail"],
          "on ne dévalide pas une semaine déjà posée : la correction n'arriverait jamais dans InterFast")
    # La relecture : tant que la case n'est pas terminée, InterFast n'a aucune heure.
    r = c.post("/api/interfast/suivi?semaine=2026-09-28")
    verif(r.status_code == 200 and r.json()["a_terminer"] == ["IN00321"], f"pas encore terminée : {r.text}")
    # Terminée dans InterFast : Paul 5 h et Jean 4 h comme au RHI, Zoé 3 h au lieu de 4.
    terminee["oui"] = True
    ecrits.clear()
    r = c.post("/api/interfast/suivi?semaine=2026-09-28")
    verif(r.json()["terminees"] == ["IN00321"] and r.json()["ecarts"] == ["IN00321"], f"relue : {r.text}")
    chemins = [a["chemin"] for n, a in ecrits if n == "appeler_api"]
    verif("/v1/intervention/999001" in chemins and "/v1/intervention/555001" in chemins,
          "la case se retrouve par l'id interne, malgré la coupure du MCP sur la seconde entrée")
    verif(all("/v1/users/103" not in x and "/v1/users/None" not in x for x in chemins),
          "on ne lit que les comptes de ceux qui portent la case")
    c28 = {x["id"]: x for x in c.get("/api/interfast/envois?semaine=2026-09-28").json()["cases"]}["CH00901|2026-09-28"]
    eq = {e["personne"]: e for e in c28["equipe"]}
    verif(c28["etat"] == "écart", f"l'onglet montre l'écart : {c28['etat']}")
    verif((eq["PAUL"]["interfast"], eq["PAUL"]["ecart"], eq["ZOE"]["interfast"], eq["ZOE"]["ecart"])
          == (5.0, False, 3.0, True), f"Zoé : 3 h reçues pour 4 h pointées : {eq['ZOE']}")
    verif(eq["LUC"]["ecart"] is False, "celui qui n'a pas de compte n'est pas un écart (il est déjà nommé)")
    ecrits.clear()
    c.post("/api/interfast/suivi?semaine=2026-09-28")
    verif([a["chemin"] for n, a in ecrits] == ["/v1/interventions/555001/timesheets"],
          f"l'id gardé : la relecture suivante va droit aux heures : {ecrits}")
    verif(interfast.lire_journee('"id": "x"') == [], "rien de lisible : rien d'inventé")
    # Notre case au-delà de la coupure : illisible, pas « à terminer ».
    with base.connexion(appli.app.state.chemin_base) as b2:
        b2.execute("UPDATE cases_interfast SET num=NULL, terminee=0")
    vraie = lecture
    lecture = lambda ch: vraie(ch).replace("555001", "555999") if "/timesheets/2026/" in ch else vraie(ch)  # noqa: E731
    r = c.post("/api/interfast/suivi?semaine=2026-09-28").json()
    verif(r["illisibles"] == ["IN00321"] and r["a_terminer"] == [], f"coupée : on ne conclut pas : {r}")
    lecture = vraie
    c.post("/api/interfast/suivi?semaine=2026-09-28")
    verif(interfast._json_de('📥 **GET**\n```json\n[{"a": 1}]\n```') == [{"a": 1}], "une liste se lit en liste")
    # Un refus d'InterFast s'arrête au premier temps, sans confirmer.
    reponses["planifier_intervention"] = "❌ Chantier introuvable pour ce client."
    base.importer_chantiers(base.connexion(appli.app.state.chemin_base),
                            [{"id": 778, "ch": "CH00902", "titre": "Port", "client": "COMMUNE DU PORT",
                              "statut": "En cours"}])
    ecrits.clear()
    r = c.post("/api/interfast/envois", json={"semaine": "2026-09-28", "cases": ["CH00902|2026-09-29"]})
    verif(r.json()["posees"] == [] and "introuvable" in r.json()["echecs"][0]["erreur"], f"refus rapporté : {r.text}")
    verif([n for n, _ in ecrits] == ["planifier_intervention"], "pas de confirmation après un refus")
    # Confirmée sans référence : marquée À VÉRIFIER, jamais renvoyée.
    reponses["planifier_intervention"] = "Récapitulatif"
    reponses["confirmer_action"] = "C'est fait."
    r = c.post("/api/interfast/envois", json={"semaine": "2026-09-28", "cases": ["CH00902|2026-09-29"]})
    verif(r.json()["echecs"] and "sans référence" in r.json()["echecs"][0]["erreur"], "sans référence : dit")
    ecrits.clear()
    c.post("/api/interfast/envois", json={"semaine": "2026-09-28", "cases": ["CH00902|2026-09-29"]})
    verif(ecrits == [], "une case peut-être créée n'est pas renvoyée (pas de doublon)")
finally:
    interfast.ECRITURE = False

fin("banc-couts")
