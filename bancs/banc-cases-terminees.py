"""Une case par groupe d'heures identiques, terminée dans InterFast dès sa pose.

Relevé du 05/11/2026 (intervention de test, sonde avec la clé API) : « Terminer »
dans InterFast, c'est PUT /v1/intervention/{id}/finished, corps vide, 200 — et
un second appel ne change rien. Aucune heure n'est saisie à la clôture : les
timesheets rendent, pour CHAQUE technicien, le créneau planifié de la case. Pour
que chacun ait SES heures dans InterFast, la case porte donc les heures d'un
groupe de personnes au temps identique, puis RHI la termine (décision de Serge).
Faux InterFast aux formes relevées ce jour-là ; noms inventés."""
import datetime as dt
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
CLE = "cle-de-banc-terminees"
os.environ["INTERFAST_VIP"] = CLE
os.environ["RHI_ECRITURE_ESSAI"] = "CH00901"
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "RHI_ENTREPRISE"):
    os.environ.pop(k, None)

from rhi import base, interfast  # noqa: E402
import app as appli  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
appli.app.state.chemin_base = tmp / "rhi.db"
heure = {"t": dt.datetime(2026, 11, 2, 9, 0)}
appli.app.state.horloge = lambda: heure["t"]
c = TestClient(appli.app)
b = base.connexion(appli.app.state.chemin_base)

GENS = {"PAUL": ("Paul Martin", 101), "JEAN": ("Jean Durand", 102), "ZOE": ("Zoe Aubert", 105)}
for nom, (complet, uid) in GENS.items():
    b.execute("INSERT INTO personnes(nom, equipe, interfast_user_id, nom_complet) VALUES (?, 'pose', ?, ?)",
              (nom, uid, complet))
base.importer_chantiers(b, [{"id": 777, "ch": "CH00901", "titre": "Résidence des Pins", "client": "BAILLEUR SUD",
                             "statut": "En cours"}])


def pointe(qui, jour, *plages):
    for d_, f_ in plages:
        b.execute("INSERT INTO pointages(personne, ch, debut, fin) VALUES (?, 'CH00901', ?, ?)",
                  (qui, f"{jour}T{d_}:00", f"{jour}T{f_}:00"))


# Mardi 27 : Paul et Jean 8 h (8-12, 13-17), Zoé 8 h 30 → deux groupes.
pointe("PAUL", "2026-10-27", ("08:00", "12:00"), ("13:00", "17:00"))
pointe("JEAN", "2026-10-27", ("08:15", "12:00"), ("13:00", "17:15"))
pointe("ZOE", "2026-10-27", ("08:00", "12:00"), ("13:00", "17:30"))
# Mercredi 28 : Paul et Jean 4 h → un seul groupe.
pointe("PAUL", "2026-10-28", ("08:00", "12:00"))
pointe("JEAN", "2026-10-28", ("08:00", "12:00"))
for qui in GENS:
    b.execute("INSERT INTO validations VALUES (?, '2026-10-26', 'Alexis', '2026-10-31')", (qui,))
b.commit()

SEMAINE = "2026-10-26"


def envois():
    return {x["id"]: x for x in c.get(f"/api/interfast/envois?semaine={SEMAINE}").json()["cases"]}


# ── 1. Le découpage : une case par CH, par jour et par groupe d'heures identiques ──
e = envois()
verif(set(e) == {"CH00901|2026-10-27|480", "CH00901|2026-10-27|510", "CH00901|2026-10-28|240"},
      f"trois cases : deux groupes le 27, un le 28 ({sorted(e)})")
a, z, m = e["CH00901|2026-10-27|480"], e["CH00901|2026-10-27|510"], e["CH00901|2026-10-28|240"]
verif(a["techniciens"] == ["Paul Martin", "Jean Durand"] and z["techniciens"] == ["Zoe Aubert"],
      f"chaque groupe porte ses techniciens : {a['techniciens']} / {z['techniciens']}")
verif((a["heure"], a["duree"], a["fin"], a["heures"]) == ("08:00", "8h", "16:00", 16.0),
      f"8 h chacun, depuis le premier début du groupe : {a['heure']} {a['duree']} {a['fin']} {a['heures']}")
verif((z["heure"], z["duree"], z["fin"], z["heures"]) == ("08:00", "8h30", "16:30", 8.5),
      f"Zoé, 30 min de plus : sa propre case : {z['heure']} {z['duree']} {z['fin']}")
verif(a["description"] == "RHI · CH00901 · pointage · JD PM" and z["description"] == "RHI · CH00901 · pointage · ZA",
      f"plusieurs groupes : les initiales au titre ({a['description']} / {z['description']})")
verif(m["description"] == "RHI · CH00901 · pointage" and m["techniciens"] == ["Paul Martin", "Jean Durand"]
      and (m["heure"], m["duree"]) == ("08:00", "4h"), f"un seul groupe : le titre simple ({m['description']})")
verif(all(x["etat"] == "prête" for x in e.values()), f"toutes prêtes : {[x['etat'] for x in e.values()]}")


# ── Le faux InterFast : REST (clé en en-tête) et MCP ──
class Faux:
    def __init__(self):
        self.evenements, self.appels, self.prochain = [], [], [2099600, 500]
        self.cloture, self.ajoute = 200, True
        self.attente = None

    def evenement(self, id_, ref, titre, debut, minutes, techniciens, termine=False):
        self.evenements.append({"id": str(id_), "title": titre, "reference": f"IN{ref:05d}", "start": debut,
                                "minutes": minutes, "techniciens": techniciens, "finished": termine,
                                "worksite": {"id": 777, "title": "Résidence des Pins"}})

    def par_id(self, n):
        return next((x for x in self.evenements if int(x["id"]) == n), None)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        chemin = req.url.path
        if req.url.host == "app.inter-fast.fr" and chemin.startswith("/v1/"):
            verif(req.headers.get("X-API-KEY") == CLE and CLE not in str(req.url), "REST : clé en en-tête, jamais dans l'adresse")
            self.appels.append((req.method, chemin))
            if req.method == "GET" and chemin == "/v1/events":
                q = dict(req.url.params)
                its = [{k: v for k, v in x.items() if k not in ("minutes", "techniciens")} for x in self.evenements
                       if not q.get("worksites") or str(x["worksite"]["id"]) == q["worksites"]]
                n, page = int(q["count"]), int(q["page"])
                return httpx.Response(200, json={"count": len(its), "items": its[page * n:(page + 1) * n]})
            m = re.fullmatch(r"/v1/intervention/(\d+)/finished", chemin)
            if req.method == "PUT" and m:
                verif(req.content in (b"", b"{}"), f"PUT /finished : corps vide ({req.content!r})")
                if self.cloture != 200:
                    return httpx.Response(self.cloture, json={"message": "Erreur"})
                x = self.par_id(int(m.group(1)))
                if not x:
                    return httpx.Response(404, json={"message": "Intervention introuvable"})
                x["finished"] = True
                return httpx.Response(200)
            m = re.fullmatch(r"/v1/intervention/(\d+)", chemin)
            if req.method == "GET" and m:
                x = self.par_id(int(m.group(1)))
                return httpx.Response(200, json={"id": int(x["id"]), "reference": int(x["reference"][2:]),
                                                 "finished": x["finished"],
                                                 "lifecycleState": "completed" if x["finished"] else "created"})
            raise AssertionError(f"REST inattendu : {req.method} {chemin}")
        corps = json.loads(req.content)
        nom, args = corps["params"]["name"], corps["params"]["arguments"]
        self.appels.append(("MCP", nom, args))
        if nom == "planifier_intervention":
            self.attente = args
            texte = f'📋 Récapitulatif … confirmation=true et action_id="{"0" * 8}-0000-0000-0000-{"0" * 12}".'
        elif nom == "confirmer_action":
            p, (id_, ref) = self.attente, self.prochain
            self.prochain = [id_ + 1, ref + 1]
            h, mn = (int(x) for x in p["heure"].split(":"))
            debut = dt.datetime.fromisoformat(p["date"]).replace(hour=h, minute=mn, tzinfo=PARIS)
            dh = re.fullmatch(r"(\d+)h(\d*)", p["duree"])
            minutes = int(dh.group(1)) * 60 + int(dh.group(2) or 0)
            if self.ajoute:
                self.evenement(id_, ref, p["description"], debut.astimezone(dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"), minutes, p["techniciens"])
            texte = f"✅ **Intervention planifiée avec succès** **Référence:** {ref} **Description:** {p['description']}"
        elif nom == "appeler_api" and re.fullmatch(r"/v1/interventions/\d+/timesheets", args["chemin"]):
            # Relevé du 05/11/2026 : après la clôture, le créneau planifié pour CHAQUE technicien.
            x = self.par_id(int(args["chemin"].split("/")[3]))
            ts = []
            if x and x["finished"]:
                d0 = dt.datetime.fromisoformat(x["start"].replace("Z", "+00:00"))
                f0 = d0 + dt.timedelta(minutes=x["minutes"])
                ts = [{"date": x["start"], "startHour": x["start"], "endHour": f0.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                       "breakTime": 0, "totalWorkedTime": x["minutes"],
                       "user": str(next(u for n_, (cpl, u) in GENS.items() if cpl == t))} for t in x["techniciens"]]
            texte = "📥 **GET**\n```json\n" + json.dumps(ts) + "\n```"
        else:
            raise AssertionError(f"MCP inattendu : {nom} {args}")
        return httpx.Response(200, text="data: " + json.dumps({"result": {"content": [{"type": "text", "text": texte}]}}))

    def planifies(self):
        return [a[2] for a in self.appels if a[0] == "MCP" and a[1] == "planifier_intervention"]

    def clotures(self):
        return [a[1] for a in self.appels if a[0] == "PUT"]


f = Faux()
appli.app.state.transport_interfast = httpx.MockTransport(f)

# ── 2. Pose puis clôture : « terminée », chacun avec SES heures ──
r = c.post("/api/interfast/envois", json={"semaine": SEMAINE, "cases": ["CH00901|2026-10-27|480", "CH00901|2026-10-27|510"]})
verif(r.status_code == 200 and len(r.json()["posees"]) == 2 and not r.json()["echecs"], f"deux cases posées : {r.text}")
verif(all(p["terminee"] for p in r.json()["posees"]), f"et terminées dans InterFast : {r.json()['posees']}")
plan = f.planifies()
verif([(p["heure"], p["duree"], p["techniciens"], p["description"]) for p in plan] == [
    ("08:00", "8h", ["Paul Martin", "Jean Durand"], "RHI · CH00901 · pointage · JD PM"),
    ("08:00", "8h30", ["Zoe Aubert"], "RHI · CH00901 · pointage · ZA")], f"ce qui part, groupe par groupe : {plan}")
verif(f.clotures() == ["/v1/intervention/2099600/finished", "/v1/intervention/2099601/finished"],
      f"PUT /finished sur l'id de chaque case : {f.clotures()}")
e = envois()
verif(e["CH00901|2026-10-27|480"]["etat"] == "terminée" and e["CH00901|2026-10-27|510"]["etat"] == "terminée",
      f"les deux cases sont terminées : {[e[k]['etat'] for k in sorted(e)]}")
verif(e["CH00901|2026-10-27|480"]["ref"] == "IN00500" and e["CH00901|2026-10-27|510"]["ref"] == "IN00501", "références")
eq = {x["personne"]: x for k in ("CH00901|2026-10-27|480", "CH00901|2026-10-27|510") for x in e[k]["equipe"]}
verif({p: (x["interfast"], x["ecart"]) for p, x in eq.items()} == {"PAUL": (8.0, False), "JEAN": (8.0, False),
                                                                   "ZOE": (8.5, False)},
      f"InterFast a reçu les heures de chacun, sans écart : {[(p, x['interfast']) for p, x in eq.items()]}")
with base.connexion(appli.app.state.chemin_base) as b2:
    nums = dict(b2.execute("SELECT groupe, num FROM cases_interfast WHERE jour='2026-10-27'").fetchall())
verif(nums == {"480": 2099600, "510": 2099601}, f"l'id de chaque case est gardé : {nums}")

# La relecture (par id, comme avant) retrouve les heures de chacun.
r = c.post(f"/api/interfast/suivi?semaine={SEMAINE}")
verif(r.status_code == 200 and sorted(r.json()["terminees"]) == ["IN00500", "IN00501"] and not r.json()["ecarts"],
      f"relecture : terminées, sans écart ({r.text})")

# ── 3. Clôture en 500 : la case reste « posée », avec de quoi réessayer ──
f.cloture = 500
f.appels.clear()
r = c.post("/api/interfast/envois", json={"semaine": SEMAINE, "cases": ["CH00901|2026-10-28|240"]})
p = r.json()["posees"]
verif(len(p) == 1 and p[0]["terminee"] is False and "500" in p[0]["cloture"], f"posée, clôture en échec dite : {p}")
x = envois()["CH00901|2026-10-28|240"]
verif(x["etat"] == "posée" and x["a_terminer"] is True, f"« posée », bouton « Terminer dans InterFast » : {x['etat']}")
f.cloture = 200
r = c.post("/api/interfast/cases/terminer", json={"ch": "CH00901", "jour": "2026-10-28", "groupe": "240"})
verif(r.status_code == 200 and envois()["CH00901|2026-10-28|240"]["etat"] == "terminée", f"reprise : terminée ({r.text})")
verif(c.post("/api/interfast/cases/terminer", json={"ch": "CH00901", "jour": "2026-10-28", "groupe": "240"}).status_code
      == 409, "une case déjà terminée ne se termine pas deux fois")

# ── 4. Anti-doublon par groupe : le groupe déjà dans InterFast est repris, l'autre créé ──
pointe("PAUL", "2026-10-29", ("08:00", "12:00"))
pointe("ZOE", "2026-10-29", ("08:00", "11:00"))
b.commit()
f.evenement(2099700, 610, "RHI · CH00901 · pointage · PM", "2026-10-29T07:00:00.000Z", 240, ["Paul Martin"])
f.evenement(2099701, 611, "RHI · CH00901 · pointage · ZA", "2026-10-28T07:00:00.000Z", 180, ["Zoe Aubert"])  # autre jour
f.appels.clear()
r = c.post("/api/interfast/envois", json={"semaine": SEMAINE, "cases": ["CH00901|2026-10-29|240", "CH00901|2026-10-29|180"]})
verif(len(r.json()["posees"]) == 2, f"deux groupes traités : {r.text}")
verif([p["description"] for p in f.planifies()] == ["RHI · CH00901 · pointage · ZA"],
      f"seul le groupe absent d'InterFast est créé : {[p['description'] for p in f.planifies()]}")
x = envois()
verif(x["CH00901|2026-10-29|240"]["ref"] == "IN00610" and x["CH00901|2026-10-29|240"]["etat"] == "terminée",
      "le groupe déjà posé est repris (IN00610), puis terminé")
verif("/v1/intervention/2099700/finished" in f.clotures(), "reprise pas encore terminée : terminée de la même façon")
# Reprise d'une case déjà terminée dans InterFast : pas de second PUT.
pointe("JEAN", "2026-10-30", ("09:00", "10:00"))
b.commit()
f.evenement(2099800, 700, "RHI · CH00901 · pointage", "2026-10-30T08:00:00.000Z", 60, ["Jean Durand"], termine=True)
f.appels.clear()
r = c.post("/api/interfast/envois", json={"semaine": SEMAINE, "cases": ["CH00901|2026-10-30|60"]})
verif(r.json()["posees"] == [{"id": "CH00901|2026-10-30|60", "ref": "IN00700", "terminee": True}] and f.clotures() == []
      and f.planifies() == [], f"déjà terminée dans InterFast : reprise sans rien envoyer ({r.text}, {f.appels})")

# ── 5. Jamais de clôture sans id certain ──
pointe("ZOE", "2026-10-31", ("08:00", "09:00"))
b.commit()
f.ajoute = False            # créée, mais introuvable ensuite : pas d'id
f.appels.clear()
r = c.post("/api/interfast/envois", json={"semaine": SEMAINE, "cases": ["CH00901|2026-10-31|60"]})
verif(r.json()["posees"][0]["terminee"] is False and f.clotures() == [], f"sans id : aucune clôture ({f.appels})")
x = envois()["CH00901|2026-10-31|60"]
verif(x["etat"] == "posée" and x["a_terminer"] is False, f"sans id : posée, pas de bouton ({x['etat']}, {x['a_terminer']})")
r = c.post("/api/interfast/cases/terminer", json={"ch": "CH00901", "jour": "2026-10-31", "groupe": "60"})
verif(r.status_code == 409 and "id" in r.json()["detail"] and f.clotures() == [], f"terminer sans id : refusé ({r.text})")
try:
    import asyncio
    asyncio.run(interfast.terminer_intervention("CH00901", None, httpx.MockTransport(f)))
    verif(False, "terminer_intervention sans id : refus attendu")
except interfast.InterFastIndisponible:
    verif(f.clotures() == [], "au plus près d'InterFast aussi : pas d'id, pas de PUT")
# Hors essai : jamais de clôture non plus.
try:
    asyncio.run(interfast.terminer_intervention("CH00999", 2099600, httpx.MockTransport(f)))
    verif(False, "terminer hors essai : refus attendu")
except interfast.EcritureCoupee:
    verif(f.clotures() == [], "hors essai : pas de PUT")

# ── 6. Une base d'avant les groupes : ses cases posées gardent leur sens ──
vieille = tmp / "vieille.db"
v = sqlite3.connect(vieille)
v.executescript("""CREATE TABLE cases_interfast (ch TEXT NOT NULL, jour TEXT NOT NULL, ref TEXT NOT NULL,
                   posee_le TEXT NOT NULL, terminee INTEGER NOT NULL DEFAULT 0, relue_le TEXT, num INTEGER,
                   PRIMARY KEY (ch, jour));
                   INSERT INTO cases_interfast VALUES ('CH00066', '2026-10-27', 'IN00410', '2026-11-05', 0, NULL, 2097424);""")
v.commit()
v.close()
v = base.connexion(vieille)
verif([tuple(r) for r in v.execute("SELECT ch, jour, groupe, ref, num FROM cases_interfast")]
      == [("CH00066", "2026-10-27", "", "IN00410", 2097424)], "migration : la case posée garde tout, groupe vide")
v.execute("INSERT INTO cases_interfast(ch, jour, groupe, ref, posee_le) VALUES ('CH00066', '2026-10-27', '120', 'IN00411', 'x')")
verif(v.execute("SELECT COUNT(*) FROM cases_interfast").fetchone()[0] == 2, "deux groupes le même jour : la clé le permet")
v.close()

fin("banc-cases-terminees")
