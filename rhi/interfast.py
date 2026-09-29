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


def cle() -> str:
    return os.getenv("INTERFAST_VIP", "")


async def _appel(methode: str, params: dict, transport=None) -> dict:
    k = cle()
    if not k:
        raise InterFastIndisponible("Clé INTERFAST_VIP absente de l'environnement")
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
    debut, fin = texte.find("{"), texte.rfind("}")
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


async def envoyer_heures(*_args, **_kw):
    if not ECRITURE:
        raise InterFastIndisponible(
            "Écriture InterFast coupée (rhi/interfast.py, ECRITURE = False) : "
            "l'API n'écrit pas d'heures ; le chemin reste à décider (docs/interfast.md).")
    raise NotImplementedError("À écrire une fois l'outil InterFast connu")
