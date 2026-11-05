"""Poser une case : la référence « 410 » se lit, et jamais deux fois la même case.

Le 05/11/2026, essai CH00066 en production : la confirmation réussit, mais le
MCP rend la référence comme un simple numéro (« **Référence:** 410 »). RHI n'y
voyait pas d'IN…, marquait la case « à vérifier », le bureau l'a renvoyée :
deux interventions identiques (409 et 410). Avant toute création, RHI cherche
donc la case dans le planning InterFast, et échoue fermé s'il ne peut pas.
Faux MCP aux formes relevées ce jour-là ; noms inventés."""
import asyncio
import io
import json
import logging
import os

import httpx

from bancs.outils import fin, verif

os.environ["INTERFAST_VIP"] = "cle-de-banc-doublon"
os.environ.pop("RHI_ENTREPRISE", None)
os.environ["RHI_ECRITURE_ESSAI"] = "CH00066"

journal = io.StringIO()
gestion = logging.StreamHandler(journal)
gestion.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
logging.getLogger("rhi").addHandler(gestion)
logging.getLogger("rhi").setLevel(logging.DEBUG)

from rhi import interfast  # noqa: E402

ACTION = "54ce6167-6dce-4cfd-bfb2-ce0bfadb1922"
RECAP = ("📋 Récapitulatif … appelez **confirmer_action** avec confirmation=true et "
         f'action_id="{ACTION}". _Cette action expire dans 10 minutes._')
# La réponse réelle du 05/11/2026 (noms changés).
CONFIRMEE = ("✅ **Intervention planifiée avec succès** **Référence:** 410 **Client:** BAILLEUR FICTIF "
             "**Chantier:** Escalier Essai **Date:** 27/10/2026 **Techniciens:** Fabien Fictif, "
             "Lucien Inventé **Description:** RHI · CH00066 · pointage")
DESCRIPTION = "RHI · CH00066 · pointage"
CASE = {"ch": "CH00066", "jour": "2026-10-27", "client": "BAILLEUR FICTIF", "chantier": "Escalier Essai", "chantier_id": 109482,
        "heure": "08:00", "duree": "2h", "techniciens": ["Fabien Fictif", "Lucien Inventé"],
        "description": DESCRIPTION}
REFERENCES = {2097420: 409, 2097424: 410, 2097430: 411}
VIDE = "📅 **Planning du 26 octobre au 1 novembre 2026** - Fabien Fictif\n\nAucun événement planifié sur cette période."


def evenement(id_, start, title=DESCRIPTION):
    """Un élément de consulter_planning, forme relevée le 05/11/2026."""
    return {"id": str(id_), "title": title, "category": "intervention", "type": "Intervention",
            "start": start, "end": start.replace("T07", "T09"), "clientId": 1, "clientName": "BAILLEUR FICTIF",
            "worksiteId": 109482, "worksiteTitle": "Escalier Essai", "address": "1 rue Fictive", "finished": False}


def planning(*items):
    return json.dumps({"kind": "planning_events", "items": list(items)}, ensure_ascii=False, separators=(",", ":"))


def evt_rest(id_, ref, start, chantier=109482, title=DESCRIPTION):
    """Un élément de GET /v1/events, forme relevée le 05/11/2026."""
    return {"id": str(id_), "category": "intervention", "title": title, "reference": ref, "start": start,
            "worksite": {"id": chantier, "title": "Escalier Essai"} if chantier else None, "users": []}


class FauxMCP:
    """MCP (POST /mcp/http) et REST (GET /v1/events). `rest` : une liste
    d'événements servie page par page, ou un statut HTTP, ou « illisible ».
    Par défaut 404 : l'anti-doublon passe alors par consulter_planning."""

    def __init__(self, planning_=VIDE, confirmee=CONFIRMEE, intervention_ok=True, rest=404):
        self.planning, self.confirmee, self.intervention_ok = planning_, confirmee, intervention_ok
        self.rest, self.rest_vus, self.appels = rest, [], []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v1/events":
            q = dict(req.url.params)
            self.rest_vus.append(q)
            verif(req.headers.get("X-API-KEY") == os.environ["INTERFAST_VIP"], "REST : clé dans l'en-tête X-API-KEY")
            verif(os.environ["INTERFAST_VIP"] not in str(req.url), "REST : la clé n'est jamais dans l'adresse")
            if isinstance(self.rest, int):
                return httpx.Response(self.rest, json={"message": "refus"})
            if self.rest == "illisible":
                return httpx.Response(200, text="<html>Connexion</html>")
            its = [e for e in self.rest if (not q.get("name") or q["name"] == e["reference"])
                   and (not q.get("worksites") or e["worksite"] and str(e["worksite"]["id"]) == q["worksites"])]
            n, page = int(q["count"]), int(q["page"])
            return httpx.Response(200, json={"count": len(its), "items": its[page * n:(page + 1) * n],
                                             "pageable": {"page": page, "itemsPerPage": n}})
        corps = json.loads(req.content)
        nom, args = corps["params"]["name"], corps["params"]["arguments"]
        self.appels.append((nom, args))
        if nom == "consulter_planning":
            if isinstance(self.planning, Exception):
                raise self.planning
            if self.planning == "erreur":
                return httpx.Response(200, text="data: " + json.dumps({"error": {"code": -32000, "message": "Panne"}}))
            texte = self.planning
        elif nom == "planifier_intervention":
            texte = RECAP
        elif nom == "confirmer_action":
            verif(args == {"confirmation": True, "action_id": ACTION}, "confirmation avec l'action_id")
            texte = self.confirmee
            if isinstance(self.rest, list):   # créée : elle apparaît dans InterFast
                self.rest.append(evt_rest(2097424, "IN00410", "2026-10-27T07:00:00.000Z"))
        elif nom == "appeler_api" and args["chemin"].startswith("/v1/intervention/"):
            n = int(args["chemin"].rsplit("/", 1)[1])
            if not self.intervention_ok:
                return httpx.Response(200, text="data: " + json.dumps({"error": {"code": -32000, "message": "Panne"}}))
            texte = ('📥 **GET**\n```json\n{"id": %d, "archived": false, "reference": %d, '
                     '"client": {"id": 5, "reference": 1797}}\n```' % (n, REFERENCES[n]))
        else:
            raise AssertionError(f"appel inattendu : {nom} {args}")
        return httpx.Response(200, text="data: " + json.dumps({"result": {"content": [{"type": "text", "text": texte}]}}))

    def noms(self):
        return [n for n, _ in self.appels]


def poser(faux):
    return asyncio.run(interfast.poser_case(dict(CASE), httpx.MockTransport(faux)))


def echoue(faux, attendue):
    try:
        r = poser(faux)
        verif(False, f"{attendue.__name__} attendue, case posée : {r}")
    except attendue as e:
        return e
    except Exception as e:  # noqa: BLE001 — le banc dit ce qui est arrivé à la place
        verif(False, f"{attendue.__name__} attendue, reçu {type(e).__name__} : {e}")


# REST refusée : recherche par consulter_planning, création, puis l'id
# interne cherché de nouveau (par consulter_planning aussi).
CREER = ["consulter_planning", "planifier_intervention", "confirmer_action", "consulter_planning"]

# ── 1. Aucune case existante : création, référence « 410 » → IN00410 ──
f = FauxMCP()
verif(poser(f) == "IN00410", "« **Référence:** 410 » se lit IN00410")
verif(f.noms() == CREER, f"recherche, puis création : {f.noms()}")
verif(f.appels[0][1] == {"semaine": "2026-10-27", "technicien": "Fabien Fictif"},
      f"on cherche la semaine du jour de la case, pour le premier technicien : {f.appels[0][1]}")
for texte in ("✅ Référence : 410", "✅ **Référence :** 410 créée", "✅ Référence:**410**", "✅ référence: 410",
              "✅ Intervention IN00410 planifiée", "✅ **Référence:** IN00410", "✅ Référence: IN410"):
    verif(poser(FauxMCP(confirmee=texte)) == "IN00410", f"« {texte} » → IN00410")
verif(poser(FauxMCP(confirmee="✅ Référence: 7")) == "IN00007", "même format que reference_de() : IN00007")
for texte in ("✅ **Intervention planifiée avec succès** **Client:** BAILLEUR FICTIF",
              "✅ Référence client: 1797 et rien d'autre"):
    e = echoue(FauxMCP(confirmee=texte), interfast.CaseSansReference)
    verif(e and "sans référence" in str(e), f"sans numéro de référence : à vérifier ({texte})")

# ── 2. La case est déjà dans InterFast une fois : reprise, rien n'est créé ──
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z")))
verif(poser(f) == "IN00410", "la case existante est reprise, avec sa référence")
verif("planifier_intervention" not in f.noms() and "confirmer_action" not in f.noms(),
      f"aucune création : {f.noms()}")
verif("case existante reprise" in journal.getvalue(), "journal : « case existante reprise »")

# ── 3. Deux fois : à vérifier, avec les deux références ──
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z"), evenement(2097420, "2026-10-27T07:00:00.000Z")))
e = echoue(f, interfast.CaseSansReference)
verif(e and "IN00409" in str(e) and "IN00410" in str(e), f"à vérifier, avec IN00409 et IN00410 : {e}")
verif("planifier_intervention" not in f.noms(), "doublons : rien n'est créé")

# ── 4. Seules comptent nos cases, du jour de la case, en heure de Paris ──
autres = planning(
    evenement(2097430, "2026-10-28T07:00:00.000Z"),                           # le lendemain
    evenement(2097430, "2026-10-27T07:00:00.000Z", "RHI · CH00067 · pointage"),  # un autre CH
    evenement(2097430, "2026-10-27T07:00:00.000Z", "Dépannage porte"),         # pas une case RHI
    evenement(2097430, "2026-10-27T23:30:00.000Z"))                           # 28/10 à 00:30 à Paris
f = FauxMCP(autres)
verif(poser(f) == "IN00410" and f.noms() == CREER, f"aucune n'est la nôtre : création ({f.noms()})")
f = FauxMCP(planning(evenement(2097424, "2026-10-26T23:30:00.000Z")))         # 27/10 à 00:30 à Paris
verif(poser(f) == "IN00410" and "planifier_intervention" not in f.noms(),
      "26/10 23:30 UTC est le 27/10 à Paris : c'est la nôtre, reprise")

# ── 5. La recherche échoue : on ne crée RIEN ──
for cas, faux in (("erreur JSON-RPC", FauxMCP("erreur")),
                  ("réseau", FauxMCP(httpx.ConnectTimeout("délai"))),
                  ("réponse illisible", FauxMCP("Technicien introuvable : Fabien Fictif")),
                  ("JSON coupé", FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z"))[:150])),
                  ("tronquée", FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z")) + "\n… (tronqué)")),
                  ("forme inconnue", FauxMCP(json.dumps({"kind": "autre", "items": []}))),
                  ("date illisible", FauxMCP(planning(evenement(2097424, "le 27 octobre"))))):
    e = echoue(faux, interfast.InterFastIndisponible)
    verif(e is not None and not isinstance(e, interfast.CaseSansReference),
          f"{cas} : InterFastIndisponible, pas « à vérifier » (la case reste prête)")
    verif(faux.noms() == ["consulter_planning"], f"{cas} : rien n'est créé ({faux.noms()})")
    verif("rien n'est créé" in str(e), f"{cas} : message clair ({e})")
# Une case existante dont la référence ne se lit pas : rien n'est créé non plus.
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z")), intervention_ok=False)
e = echoue(f, interfast.InterFastIndisponible)
verif("planifier_intervention" not in f.noms(), "référence de la case existante illisible : rien n'est créé")

# Sans technicien relié, on ne peut pas chercher : rien n'est créé.
f = FauxMCP()
try:
    asyncio.run(interfast.poser_case(dict(CASE, techniciens=[]), httpx.MockTransport(f)))
    verif(False, "sans technicien : erreur attendue")
except interfast.InterFastIndisponible:
    verif(f.noms() == [], "sans technicien : ni recherche ni création")

# ── 6. Par l'API REST d'abord (GET /v1/events), paginée ──
autres = [evt_rest(3000000 + i, f"IN{i:05d}", "2026-10-27T05:00:00.000Z", title=f"Dépannage {i}") for i in range(50)]
f = FauxMCP(rest=autres + [evt_rest(2097424, "IN00410", "2026-10-27T07:00:00.000Z")])
r = poser(f)
verif(r == "IN00410" and r.num == 2097424, f"REST, page 2 : la case est reprise avec son id ({r}, {getattr(r, 'num', None)})")
verif(f.appels == [], f"REST qui répond : aucun appel MCP, rien n'est créé ni relu ({f.noms()})")
verif([q["page"] for q in f.rest_vus] == ["0", "1"] and all(q["count"] == "50" for q in f.rest_vus),
      f"deux pages de 50 : {[q['page'] for q in f.rest_vus]}")
q = f.rest_vus[0]
verif((q["start"], q["end"], q["worksites"], q["archived"], q["meeting"])
      == ("2026-10-26T00:00:00", "2026-10-28T23:59:59", "109482", "false", "false"),
      f"filtrée sur le jour (±1 pour les fuseaux) et le chantier : {q}")
# Création par la REST : l'id est retrouvé aussitôt après.
f = FauxMCP(rest=[evt_rest(2097430, "IN00411", "2026-10-28T07:00:00.000Z")])
r = poser(f)
verif(r == "IN00410" and r.num == 2097424, f"créée, puis son id retrouvé : {r} {getattr(r, 'num', None)}")
verif(f.noms() == ["planifier_intervention", "confirmer_action"], f"REST : pas de consulter_planning ({f.noms()})")
# Deux par la REST : à vérifier, références lues dans la réponse.
f = FauxMCP(rest=[evt_rest(2097424, "IN00410", "2026-10-27T07:00:00.000Z"),
                  evt_rest(2097420, "IN00409", "2026-10-27T07:00:00.000Z")])
e = echoue(f, interfast.Doublons)
verif(e and "IN00409" in str(e) and "IN00410" in str(e) and f.appels == [], f"REST, doublons : à vérifier ({e})")
# REST en 404, 401, 403 ou illisible : repli sur consulter_planning.
for refus in (404, 401, 403, "illisible"):
    f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z")), rest=refus)
    r = poser(f)
    verif(r == "IN00410" and f.rest_vus and f.noms()[0] == "consulter_planning"
          and "planifier_intervention" not in f.noms(), f"REST {refus} : repli MCP, reprise ({f.noms()})")
# REST en panne (429, 5xx) : ni repli ni création.
for panne in (429, 500):
    f = FauxMCP(rest=panne)
    e = echoue(f, interfast.InterFastIndisponible)
    verif(f.appels == [] and "rien n'est créé" in str(e), f"REST {panne} : rien n'est créé, sans repli ({e})")
# REST en 404 et repli tronqué : rien n'est créé.
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z")) + "\n… (tronqué)", rest=404)
e = echoue(f, interfast.InterFastIndisponible)
verif(f.noms() == ["consulter_planning"] and "rien n'est créé" in str(e), f"REST 404 + repli tronqué : rien ({e})")

# ── 7. Une référence portée par plusieurs interventions ──
# 05/11/2026 : IN00410 = notre case CH00066 du 27/10 ET une visite de 2022.
HOMONYMES = [evt_rest(2097424, "IN00410", "2026-10-27T07:00:00.000Z"),
             evt_rest(1097612, "IN00410", "2022-05-23T06:00:00.000Z", chantier=None, title="1ERE VISITE 2022")]
f = FauxMCP(rest=list(HOMONYMES))
num = asyncio.run(interfast.retrouver_reference("IN00410", "2026-10-27", 109482, "Fabien Fictif", httpx.MockTransport(f)))
verif(num == 2097424, f"IN00410 : la case du jour et du chantier est retenue, pas la visite de 2022 ({num})")
verif(f.rest_vus[0]["name"] == "IN00410", "cherchée par référence (filtre name)")
for jour, chantier in (("2026-10-28", 109482), ("2026-10-27", 999)):
    try:
        asyncio.run(interfast.retrouver_reference("in00410", jour, chantier, "Fabien Fictif",
                                                  httpx.MockTransport(FauxMCP(rest=list(HOMONYMES)))))
        verif(False, f"{jour} / chantier {chantier} : refus attendu")
    except interfast.ReferenceAmbigue as e:
        verif("2097424" in str(e) and "1097612" in str(e) and "2022-05-23" in str(e),
              f"aucune au jour et au chantier : refus avec la liste ({e})")
f = FauxMCP(rest=list(HOMONYMES) + [evt_rest(2097499, "IN00410", "2026-10-27T09:00:00.000Z")])
try:
    asyncio.run(interfast.retrouver_reference("IN00410", "2026-10-27", 109482, "Fabien Fictif", httpx.MockTransport(f)))
    verif(False, "deux le même jour sur le même chantier : refus attendu")
except interfast.ReferenceAmbigue as e:
    verif("2097499" in str(e), f"deux au jour et au chantier : refus avec la liste ({e})")
# REST refusée : le planning du jour, chaque id relu par reference_de.
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z"), evenement(2097430, "2026-10-27T07:00:00.000Z",
                                                                                "Autre")), rest=404)
num = asyncio.run(interfast.retrouver_reference("IN00410", "2026-10-27", 109482, "Fabien Fictif", httpx.MockTransport(f)))
verif(num == 2097424, f"REST 404 : retrouvée par le planning du jour ({num}, {f.noms()})")

# ── 8. L'id d'une case posée sans lui (l'essai CH00066, IN00410) ──
f = FauxMCP(rest=list(HOMONYMES) + [evt_rest(2097431, "IN00412", "2026-10-27T07:00:00.000Z",
                                             title="RHI · CH00067 · pointage")])
num = asyncio.run(interfast.num_de_case("CH00066", "2026-10-27", "IN00410", 109482, "Fabien Fictif",
                                        httpx.MockTransport(f)))
verif(num == 2097424, f"retrouvé par jour + chantier + titre : {num}")
f = FauxMCP(rest=[evt_rest(2097424, "IN00410", "2026-10-27T07:00:00.000Z"),
                  evt_rest(2097425, "IN00415", "2026-10-27T08:00:00.000Z")])
num = asyncio.run(interfast.num_de_case("CH00066", "2026-10-27", "IN00410", 109482, "Fabien Fictif",
                                        httpx.MockTransport(f)))
verif(num == 2097424, f"deux cases RHI du CH ce jour-là : la référence départage ({num})")
f = FauxMCP(planning(evenement(2097424, "2026-10-27T07:00:00.000Z"), evenement(2097420, "2026-10-27T07:00:00.000Z")),
            rest=404)
num = asyncio.run(interfast.num_de_case("CH00066", "2026-10-27", "IN00410", 109482, "Fabien Fictif",
                                        httpx.MockTransport(f)))
verif(num is None, "par le MCP, deux candidates sans référence : on ne devine pas")

verif("cle-de-banc-doublon" not in journal.getvalue(), "la clé n'est dans aucun journal")

fin("banc-doublon")
