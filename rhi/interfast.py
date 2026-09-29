"""InterFast — la base de tout, et la destination des heures.

Même protocole que dans Ali Baba (MCP en JSON-RPC, réponse en SSE `data:`),
même compte : la serrurerie, c'est la clé `INTERFAST_VIP` (VIP Plus). La clé
vit dans l'environnement Clever Cloud, JAMAIS dans ce dépôt, qui est public.

Ce que la clé a appris (lecture seule, 29/09/2026) :
  · les CH sont les CHANTIERS d'InterFast : `rechercher_chantiers` rend
    « (Réf: CH00xxx) », le client et le statut (348 chantiers ce jour-là ;
    les 36 CH des plannings d'Alexis y sont TOUS) → `chantiers()` ci-dessous ;
  · les ouvriers existent comme utilisateurs « technician » de l'agence
    Serrurerie, jamais connectés, coût horaire à 0 ;
  · les heures (« timesheets ») ne se LISENT qu'attachées à une
    intervention (GET /v1/interventions/{id}/timesheets) : l'API n'offre
    AUCUNE écriture d'heures. Le seul geste d'écriture voisin est
    `planifier_intervention` (client, chantier, date, heure, durée,
    techniciens) — une intervention planifiée, pas un temps pointé.

ECRITURE reste donc à False tant que la façon de faire tomber les heures
n'est pas décidée (voir docs/interfast.md). Une écriture ratée dans
InterFast fausse un point d'affaire en silence ; un export, lui, se relit.
"""
import asyncio
import json
import os
import re

import httpx

MCP_URL = "https://app.inter-fast.fr/mcp/http"

# L'interrupteur. Une ligne pour rebrancher, le jour où l'outil est connu
# ET essayé sur une affaire de test.
ECRITURE = False


class InterFastIndisponible(RuntimeError):
    pass


# Une instance de RHI = une entreprise = un compte InterFast (mêmes noms de
# variables que dans Ali Baba).
CLES = {"VIP": "INTERFAST_VIP", "ALFA": "INTERFAST_ALFA"}


def entreprise() -> str:
    e = os.getenv("RHI_ENTREPRISE", "VIP").strip().upper()
    return e if e in CLES else "VIP"


def cle() -> str:
    return os.getenv(CLES[entreprise()], "")


async def _appel(methode: str, params: dict, transport=None) -> dict:
    k = cle()
    if not k:
        raise InterFastIndisponible(f"Clé {CLES[entreprise()]} absente de l'environnement")
    corps = {"jsonrpc": "2.0", "id": 1, "method": methode, "params": params}
    # InterFast répond parfois 401 ou 429 sous une rafale d'appels, puis
    # accepte la même requête une seconde plus tard (constaté le 29/09/2026
    # en lisant les utilisateurs un par un). Trois essais, espacés.
    for essai in range(3):
        async with httpx.AsyncClient(timeout=40, transport=transport) as h:
            r = await h.post(f"{MCP_URL}?apiKey={k}", json=corps, headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"})
        if r.status_code not in (401, 429, 502, 503) or essai == 2:
            break
        await asyncio.sleep(1 + 2 * essai)
    for ligne in r.text.splitlines():
        if ligne.startswith("data: "):
            d = json.loads(ligne[6:])
            if "error" in d:
                raise InterFastIndisponible(d["error"].get("message", "Erreur InterFast"))
            return d.get("result", {})
    raise InterFastIndisponible(f"Réponse illisible (HTTP {r.status_code})")


async def outils(transport=None) -> list:
    """Noms et descriptions des outils du MCP — pour trouver les deux qui manquent."""
    res = await _appel("tools/list", {}, transport)
    return [{"nom": o.get("name"), "description": o.get("description", "")}
            for o in res.get("tools", [])]


async def outil(nom: str, args: dict, transport=None) -> str:
    """Appelle un outil du MCP et rend son texte."""
    res = await _appel("tools/call", {"name": nom, "arguments": args}, transport)
    return "".join(b.get("text", "") for b in res.get("content", []))


# « • [127006] M-6449 — VIDEO SURVEILLANCE … (Réf: CH00347)
#     Statut: En cours | Client: SYNAGOGUE … »  — relevé le 29/09/2026.
_CHANTIER = re.compile(r"^\s*•\s*\[(\d+)\]\s*(.*?)\s*\(Réf:\s*(CH\d{5})\)\s*$")
_STATUT = re.compile(r"^\s*Statut:\s*(.*?)\s*\|\s*Client:\s*(.*?)\s*$")
_PAGES = re.compile(r"Page\s+(\d+)\s*/\s*(\d+)")


def lire_chantiers(texte: str) -> list:
    """La réponse texte de rechercher_chantiers, en fiches."""
    fiches = []
    for ligne in texte.splitlines():
        m = _CHANTIER.match(ligne)
        if m:
            fiches.append({"id": int(m.group(1)), "titre": m.group(2), "ch": m.group(3),
                           "statut": "", "client": ""})
            continue
        m = _STATUT.match(ligne)
        if m and fiches:
            fiches[-1]["statut"], fiches[-1]["client"] = m.group(1), m.group(2)
    return fiches


async def chantiers(transport=None, plafond=100) -> list:
    """Tous les chantiers du compte, page par page (20 par page, le maximum)."""
    tous, page, dernieres = [], 0, 1
    while page < min(dernieres, plafond):
        texte = await outil("rechercher_chantiers", {"page": page, "taille": 20}, transport)
        m = _PAGES.search(texte)
        dernieres = int(m.group(2)) if m else 1
        lus = lire_chantiers(texte)
        if not lus:
            break
        tous += lus
        page += 1
    return tous


class Tronque(InterFastIndisponible):
    """Le MCP coupe ses réponses vers 4 000 caractères (« … (tronqué) »)."""


def _json_de(texte: str):
    """Le bloc JSON d'une réponse d'appeler_api (« 📥 **GET …** ```json {…} ``` »)."""
    if "(tronqué)" in texte:
        raise Tronque("Réponse InterFast tronquée")
    # Un objet ou une liste : on part du premier des deux qui apparaît.
    ouvrants = [i for i in (texte.find("{"), texte.find("[")) if i >= 0]
    debut = min(ouvrants) if ouvrants else -1
    fin = texte.rfind("}" if debut >= 0 and texte[debut] == "{" else "]")
    if debut < 0 or fin < debut:
        raise InterFastIndisponible(f"Réponse sans JSON : {texte[:120]}")
    return json.loads(texte[debut:fin + 1])


async def lire_api(chemin: str, params: dict, transport=None):
    """GET générique par appeler_api. GET SEULEMENT : c'est une garde, pas
    une convention — un POST passerait par une confirmation d'écriture."""
    texte = await outil("appeler_api", {"methode": "GET", "chemin": chemin, "params": params,
                                        "intention": f"Lecture {chemin} (RHI)"}, transport)
    return _json_de(texte)


def _fiche_utilisateur(u: dict) -> dict:
    return {"id": u.get("id"), "prenom": u.get("firstName") or "", "nom": u.get("lastName") or "",
            "role": u.get("role") or "", "archive": bool(u.get("archived")),
            "cout": u.get("hourlyCost") or 0}


async def utilisateur(uid: int, transport=None):
    """Un utilisateur par son id, ou None s'il n'existe pas (404)."""
    texte = await outil("appeler_api", {"methode": "GET", "chemin": f"/v1/users/{uid}",
                                        "intention": "Lecture utilisateur (RHI)"}, transport)
    if "erreur 404" in texte[:80] or "n'existe pas" in texte[:200]:
        return None
    u = _fiche_utilisateur(_json_de(texte))
    if u["id"] != uid:
        raise InterFastIndisponible(f"Réponse pour l'id {u['id']} alors qu'on demandait {uid}")
    return u


async def utilisateurs(transport=None, trou=12, plafond=300) -> list:
    """Tous les utilisateurs du compte.

    Pourquoi ce détour (constaté le 29/09/2026) : le MCP coupe toute réponse
    vers 4 000 caractères — la liste /v1/users s'arrête au 7e utilisateur —
    et `appeler_api` ne transmet ni `page` ni `size` ni `name`. Un
    utilisateur seul, lui, tient en 735 caractères. On part donc des ids
    visibles dans la liste tronquée, et on lit les ids voisins un par un,
    dans les deux sens, jusqu'à `trou` absents d'affilée (les comptes d'une
    entreprise sont créés par lots : ids contigus, avec des trous).

    EN SÉRIE, jamais en parallèle : sous une rafale, le MCP a rendu des
    404 pour des comptes qui existent (Cédric, Djellal) — des gars
    silencieusement absents du RHI. Une trentaine de secondes, au bureau,
    une fois de temps en temps : c'est le bon prix."""
    texte = await outil("appeler_api", {"methode": "GET", "chemin": "/v1/users",
                                        "params": {"page": 0, "size": 100},
                                        "intention": "Lecture utilisateurs (RHI)"}, transport)
    graines = sorted({int(i) for i in re.findall(r'"id":\s*(\d+),\s*"firstName"', texte)})
    if not graines:
        raise InterFastIndisponible(f"Aucun utilisateur lisible : {texte[:120]}")
    trouves, essais = {}, 0
    # La liste est triée par NOM, pas par id : entre deux ids visibles se
    # cachent des comptes (Cédric, Djellal manquaient). On lit donc toute
    # la plage, pas seulement les ids affichés.
    for i in range(graines[0], graines[-1] + 1):
        essais += 1
        u = await utilisateur(i, transport)
        if u:
            trouves[i] = u
    for sens in (1, -1):
        i, absents = (graines[-1] if sens > 0 else graines[0]), 0
        while absents < trou and essais < plafond and i + sens > 0:
            i += sens
            essais += 1
            u = await utilisateur(i, transport)
            if u:
                trouves[i], absents = u, 0
            else:
                absents += 1
    return [trouves[k] for k in sorted(trouves)]


# « • [uuid] Import Optima - CH00045 (Réf: D0348)
#     Statut: Signé / Client: … / Montant: HT: 454 256,92 € | TTC: … »  — 29/09/2026
_DEVIS = re.compile(r"^\s*•\s*\[([0-9a-f-]+)\]\s*(.*?)\s*\((?:Réf:\s*)?([^)]*)\)\s*$")
_MONTANT = re.compile(r"HT:\s*([\d\s\u00a0\u202f.,]+?)\s*€")
VENDU = {"Signé", "Payé"}


def montant(texte: str):
    """« 454 256,92 » (espaces fines ou insécables) → 454256.92."""
    propre = re.sub(r"[\s\u00a0\u202f]", "", texte)
    if "," in propre:                      # 1.234,56 ou 1234,56 : la virgule décimale
        propre = propre.replace(".", "").replace(",", ".")
    try:
        return float(propre)
    except ValueError:
        return None


def lire_devis(texte: str) -> list:
    fiches = []
    for ligne in texte.splitlines():
        m = _DEVIS.match(ligne)
        if m:
            fiches.append({"id": m.group(1), "titre": m.group(2), "ref": m.group(3),
                           "statut": "", "ht": None})
            continue
        if not fiches:
            continue
        if ligne.strip().startswith("Statut:"):
            fiches[-1]["statut"] = ligne.split(":", 1)[1].strip()
        m = _MONTANT.search(ligne)
        if m and ligne.strip().startswith("Montant"):
            fiches[-1]["ht"] = montant(m.group(1))
    return fiches


async def devis_de(ch: str, transport=None) -> dict:
    """Le vendu HT d'un CH : les devis signés ou payés dont le TITRE porte le CH.

    InterFast ne relie pas un devis à un chantier par l'API ; les devis
    importés d'Optima portent le CH dans leur titre (« Import Optima -
    CH00045 »). C'est une convention de saisie, pas un lien : un devis sans
    le CH dans son titre n'est pas compté, et RHI dit « non trouvé » plutôt
    que 0 € (13 CH sur 33 trouvés le 29/09/2026)."""
    texte = await outil("rechercher_devis", {"recherche": ch, "taille": 20}, transport)
    tous = [d for d in lire_devis(texte) if ch in d["titre"]]
    vendus = [d for d in tous if d["statut"] in VENDU and d["ht"] is not None]
    return {"ch": ch, "devis": len(tous), "vendus": len(vendus),
            "vendu_ht": round(sum(d["ht"] for d in vendus), 2) if vendus else None,
            "refs": [d["ref"] for d in vendus]}


class EcritureCoupee(InterFastIndisponible):
    """ECRITURE = False : rien ne part, et on le dit."""


class CaseSansReference(InterFastIndisponible):
    """InterFast a confirmé sans rendre de référence IN… : la case existe
    peut-être. On ne la renvoie pas (doublon) ; on la fait vérifier."""


_REF = re.compile(r"\bIN\d{4,6}\b")
_REFUS = ("❌", "Aucune action")


async def poser_case(case: dict, transport=None) -> str:
    """Pose une case dans le planning InterFast et rend sa référence (IN…).

    Les deux temps du MCP : planifier_intervention prépare et récapitule,
    confirmer_action crée. Un refus (« ❌ », « Aucune action ») s'arrête là,
    sans réessayer avec d'autres paramètres : le MCP le demande, et une
    case posée au mauvais endroit fausse un point d'affaire en silence."""
    if not ECRITURE:
        raise EcritureCoupee(
            "Écriture InterFast coupée (rhi/interfast.py, ECRITURE = False) : à rebrancher "
            "après l'essai sur une affaire de test (docs/interfast.md).")
    args = {"client": case["client"], "date": case["jour"], "heure": case["heure"],
            "duree": case["duree"], "techniciens": case["techniciens"], "description": case["description"]}
    if case.get("chantier"):
        args["chantier"] = case["chantier"]
    recap = await outil("planifier_intervention", args, transport)
    if any(x in recap for x in _REFUS):
        raise InterFastIndisponible(f"InterFast refuse la case : {recap[:300]}")
    reponse = await outil("confirmer_action", {"confirmation": True}, transport)
    if any(x in reponse for x in _REFUS):
        raise InterFastIndisponible(f"InterFast refuse la confirmation : {reponse[:300]}")
    m = _REF.search(reponse)
    if not m:
        raise CaseSansReference(f"Confirmée sans référence : {reponse[:300]}")
    return m.group(0)


# Les heures saisies à la clôture d'une intervention — relevé du 29/09/2026 :
#   GET /v1/users/{id}/timesheets/{a}/{m}/{j}/interventions → une entrée par
#   intervention du jour : "startHour", "endHour" (UTC), "totalWorkedTime" et
#   "breakTime" (minutes), "interventionId", puis l'intervention entière
#   (~3 000 caractères). Au-delà de la première, les entrées sont coupées par
#   le MCP : on lit donc les champs de tête un à un, pas le JSON.
_ENTREE = re.compile(
    r'"startHour":\s*"([^"]+)".*?"endHour":\s*"([^"]+)".*?"totalWorkedTime":\s*(\d+)'
    r'.*?"breakTime":\s*(\d+).*?"interventionId":\s*"?(\d+)', re.S)


def lire_journee(texte: str) -> list:
    """Les entrées lisibles d'une journée, même tronquée. Une entrée dont
    l'interventionId est coupé n'est pas rendue : mieux vaut une ligne
    absente qu'une ligne rattachée au hasard."""
    morceaux = re.split(r'"id":\s*"[0-9a-f-]{36}"', texte)[1:]
    sortie = []
    for m in morceaux:
        e = _ENTREE.search(m)
        if e:
            sortie.append({"debut": e.group(1), "fin": e.group(2), "minutes": int(e.group(3)),
                           "pause": int(e.group(4)), "intervention": int(e.group(5))})
    return sortie


async def journee(uid: int, jour, transport=None) -> tuple:
    """(entrées lisibles, coupée ?) — au 29/09/2026, seules les deux
    premières interventions d'une journée passent la coupure du MCP."""
    texte = await outil("appeler_api", {
        "methode": "GET", "chemin": f"/v1/users/{uid}/timesheets/{jour.year}/{jour.month}/{jour.day}/interventions",
        "intention": "Lecture des heures du jour (RHI)"}, transport)
    return lire_journee(texte), "(tronqué)" in texte


async def reference_de(num: int, transport=None):
    """« IN00047 » d'une intervention, par son id interne (1819630). Le
    premier "reference" après l'id est celui de l'intervention ; ceux du
    client et de l'adresse viennent après."""
    texte = await outil("appeler_api", {"methode": "GET", "chemin": f"/v1/intervention/{num}",
                                        "params": {"withFollowUp": False},
                                        "intention": "Lecture d'une intervention (RHI)"}, transport)
    m = re.search(r'"id":\s*%d\s*,.*?"reference":\s*(\d+)' % num, texte, re.S)
    return f"IN{int(m.group(1)):05d}" if m else None


async def heures_intervention(num: int, transport=None) -> list:
    """Les heures de chaque technicien sur une intervention terminée (vide
    tant qu'elle ne l'est pas). Réponse courte : du vrai JSON."""
    lu = await lire_api(f"/v1/interventions/{num}/timesheets", {}, transport)
    return [{"user": int(t["user"]), "debut": t["startHour"], "fin": t["endHour"],
             "minutes": int(t.get("totalWorkedTime") or 0), "pause": int(t.get("breakTime") or 0)}
            for t in (lu if isinstance(lu, list) else [])]
