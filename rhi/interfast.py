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
import datetime as dt
import json
import logging
import os
import re

import httpx

MCP_URL = "https://app.inter-fast.fr/mcp/http"

# L'interrupteur. Une ligne pour rebrancher, le jour où l'outil est connu
# ET essayé sur une affaire de test.
ECRITURE = False

# L'essai, avant l'interrupteur (30/09/2026) : l'écriture est ouverte sur
# l'affaire de test SEULEMENT, en production, pour qu'Alexis pose une case
# depuis le bureau sans qu'une autre affaire puisse partir. Réglable par
# RHI_ECRITURE_ESSAI (CH séparés par des virgules ; vide = aucun) ; par défaut
# l'affaire de test de VIP Plus, choisie par Alexis.
ESSAI_PAR_DEFAUT = {"VIP": "CH00066"}


def essai() -> list:
    """Les CH sur lesquels l'écriture est ouverte pour l'essai."""
    v = os.getenv("RHI_ECRITURE_ESSAI")
    if v is None:
        v = ESSAI_PAR_DEFAUT.get(os.getenv("RHI_ENTREPRISE", "VIP").strip().upper(), "")
    return sorted({c.strip().upper() for c in v.split(",") if c.strip()})


def ecriture_permise(ch: str) -> bool:
    """Tout, une fois l'interrupteur levé ; avant, les seules affaires d'essai."""
    return ECRITURE or (ch or "").upper() in essai()


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
        try:
            async with httpx.AsyncClient(timeout=40, transport=transport) as h:
                r = await h.post(f"{MCP_URL}?apiKey={k}", json=corps, headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"})
        except httpx.HTTPError as e:   # délai dépassé, connexion coupée : dit, jamais un 500 muet
            raise InterFastIndisponible(f"InterFast injoignable : {type(e).__name__}") from e
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


REST_URL = "https://app.inter-fast.fr/v1"
REST_TAILLE = 100       # comptes par page
REST_PAGES = 20         # garde : au-delà, ce n'est plus une liste de comptes
REST_DELAI = 20         # secondes par page
# Ces refus-là disent « pas par ici » (clé non admise en REST, route
# absente) : on retombe sur le MCP. Les autres (429, 5xx) disent « pas
# maintenant » : le repli, ~30 s de lectures en série, n'y changerait rien.
REST_REPLI = {401, 403, 404}


class _PasEnRest(InterFastIndisponible):
    """L'API REST ne rend pas les comptes : repli sur le MCP."""


class _Masque(logging.Filter):
    """Le MCP prend la clé dans son adresse (?apiKey=) et httpx journalise
    les adresses : la clé est masquée avant d'atteindre un journal."""

    def filter(self, record):
        k = cle()
        if k and k in record.getMessage():
            record.msg, record.args = record.getMessage().replace(k, "***"), ()
        return True


for _nom in ("httpx", "httpcore"):
    if not any(isinstance(f, _Masque) for f in logging.getLogger(_nom).filters):
        logging.getLogger(_nom).addFilter(_Masque())


def _comptes_rest(r: httpx.Response) -> list:
    """La page /v1/users : une liste, nue ou rangée sous une clé connue."""
    try:
        d = r.json()
    except ValueError:
        raise _PasEnRest("Réponse REST illisible") from None
    if isinstance(d, dict):
        d = next((d[k] for k in ("items", "content", "data", "results", "users")
                  if isinstance(d.get(k), list)), None)
    if not isinstance(d, list) or not all(isinstance(u, dict) and isinstance(u.get("id"), int) for u in d):
        raise _PasEnRest("Réponse REST sans liste de comptes")
    return d


async def utilisateurs_rest(transport=None) -> list:
    """Tous les comptes par l'API REST directe, page par page.

    La clé part dans l'en-tête X-API-KEY (mode éprouvé sur /v1/orders), jamais
    dans l'adresse ni dans un message. On s'arrête sur une page incomplète
    ou vide, ou sur une page qui n'apporte aucun id nouveau (une API qui
    ignorerait `page` rendrait sinon la même page vingt fois)."""
    k = cle()
    if not k:
        raise InterFastIndisponible(f"Clé {CLES[entreprise()]} absente de l'environnement")
    trouves = {}
    async with httpx.AsyncClient(timeout=REST_DELAI, transport=transport) as h:
        for page in range(REST_PAGES):
            try:
                r = await h.get(f"{REST_URL}/users", params={"page": page, "size": REST_TAILLE},
                                headers={"X-API-KEY": k, "Accept": "application/json"})
            except httpx.HTTPError as e:
                raise InterFastIndisponible(f"InterFast injoignable : {type(e).__name__}") from e
            if r.status_code in REST_REPLI:
                raise _PasEnRest(f"API REST : HTTP {r.status_code}")
            if r.status_code != 200:
                raise InterFastIndisponible(f"InterFast répond HTTP {r.status_code} à la liste des comptes")
            lus = _comptes_rest(r)
            nouveaux = [u for u in lus if u["id"] not in trouves]
            for u in nouveaux:
                trouves[u["id"]] = _fiche_utilisateur(u)
            if len(lus) < REST_TAILLE or not nouveaux:
                return [trouves[i] for i in sorted(trouves)]
    raise InterFastIndisponible(f"Plus de {REST_PAGES} pages de {REST_TAILLE} comptes : lecture arrêtée")


def grappes(graines: list, trou: int) -> list:
    """Les ids visibles, regroupés : deux graines distantes de plus de
    2 × trou sont dans deux lots de comptes différents. Le 05/11/2026, des
    comptes créés ce jour-là (ids vers 31 869) côtoyaient les anciens (vers
    23 722) : lire toute la plage entre les deux faisait ~8 000 lectures."""
    lots = []
    for g in sorted(set(graines)):
        if lots and g - lots[-1][-1] <= 2 * trou:
            lots[-1].append(g)
        else:
            lots.append([g])
    return lots


async def utilisateurs_mcp(transport=None, trou=12, plafond=300) -> list:
    """Le repli par le MCP, quand l'API REST ne répond pas.

    Pourquoi ce détour (constaté le 29/09/2026) : le MCP coupe toute réponse
    vers 4 000 caractères — la liste /v1/users s'arrête au 7e utilisateur —
    et `appeler_api` ne transmet ni `page` ni `size` ni `name`. Un
    utilisateur seul, lui, tient en 735 caractères. On part donc des ids
    visibles dans la liste tronquée, regroupés en grappes ; dans chaque
    grappe on lit toute la plage (la liste est triée par NOM, pas par id :
    Cédric et Djellal se cachaient entre deux ids visibles), puis les ids
    voisins dans les deux sens, jusqu'à `trou` absents d'affilée.

    `plafond` borne TOUT le balayage : au-delà, on s'arrête en le disant,
    plutôt qu'une requête que le proxy coupe sans un mot.

    EN SÉRIE, jamais en parallèle : sous une rafale, le MCP a rendu des
    404 pour des comptes qui existent (Cédric, Djellal) — des gars
    silencieusement absents du RHI."""
    texte = await outil("appeler_api", {"methode": "GET", "chemin": "/v1/users",
                                        "params": {"page": 0, "size": 100},
                                        "intention": "Lecture utilisateurs (RHI)"}, transport)
    graines = sorted({int(i) for i in re.findall(r'"id":\s*(\d+),\s*"firstName"', texte)})
    if not graines:
        raise InterFastIndisponible(f"Aucun utilisateur lisible : {texte[:120]}")
    trouves, lus = {}, set()

    async def lire(i):
        if i in lus:
            return i in trouves
        if len(lus) >= plafond:
            raise InterFastIndisponible(
                f"Plafond de {plafond} lectures atteint en relisant les comptes InterFast "
                f"(ids visibles de {graines[0]} à {graines[-1]}) : lecture arrêtée, rien n'a changé")
        lus.add(i)
        u = await utilisateur(i, transport)
        if u:
            trouves[i] = u
        return bool(u)

    for lot in grappes(graines, trou):
        for i in range(lot[0], lot[-1] + 1):
            await lire(i)
        for sens in (1, -1):
            i, absents = (lot[-1] if sens > 0 else lot[0]), 0
            while absents < trou and i + sens > 0:
                i += sens
                absents = 0 if await lire(i) else absents + 1
    return [trouves[k] for k in sorted(trouves)]


async def utilisateurs(transport=None, trou=12, plafond=300) -> list:
    """Tous les utilisateurs du compte : par l'API REST (une poignée de
    pages), et par le MCP seulement si la REST refuse (401, 403, 404) ou
    rend un corps illisible."""
    try:
        return await utilisateurs_rest(transport)
    except _PasEnRest:
        return await utilisateurs_mcp(transport, trou, plafond)


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
    """La confirmation est partie, mais sa réponse ne dit pas clairement
    « créée, IN… » : pas de référence, un refus, un délai dépassé. La case
    existe peut-être — une confirmation qui échoue sur un 502 APRÈS avoir
    créé la case est rejouée, et le second essai répond « Aucune action ».
    On ne la renvoie pas (doublon) ; le bureau vérifie dans InterFast."""


_REF = re.compile(r"\bIN(\d{4,6})\b")
# Depuis le 05/11/2026, confirmer_action rend la référence comme un simple
# numéro : « ✅ **Intervention planifiée avec succès** **Référence:** 410 … ».
# Gras, espaces et deux-points variables ; « Référence client: … » n'en est pas.
_REF_NUMERO = re.compile(r"\bR[ée]f[ée]rence[\s*:_]*(?:IN)?(\d{1,6})\b", re.I)
_REFUS = ("❌", "Aucune action")
# Le jeton de l'action préparée — relevé le 05/11/2026 dans le récapitulatif :
# « appelez **confirmer_action** avec confirmation=true et
# action_id="54ce6167-…" ». Tolérant : guillemets, apostrophes, backticks ou
# rien, `=` ou `:` (forme JSON). Un uuid, rien d'autre.
_ACTION_ID = re.compile(
    r"action_id[\"'`]?\s*[=:]\s*[\"'`]?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.I)

journal = logging.getLogger("rhi.interfast")


def reference_rendue(reponse: str):
    """La référence d'une case créée, au format de reference_de() (IN00410),
    ou None. « Référence: 410 » comme « IN00410 »."""
    m = _REF_NUMERO.search(reponse or "") or _REF.search(reponse or "")
    return f"IN{int(m.group(1)):05d}" if m else None


class Doublons(CaseSansReference):
    """Plusieurs cases RHI identiques déjà dans InterFast : le bureau supprime
    les doublons là-bas, puis tranche."""


class Posee(str):
    """La référence d'une case posée (« IN00410 »), avec l'id interne de
    l'intervention dans `.num` (2097424) ou None. Les références InterFast ne
    sont PAS uniques (05/11/2026 : IN00410 est notre case CH00066 du 27/10 ET
    une visite de 2022 dans un lycée) : l'id, lui, l'est."""

    def __new__(cls, ref, num=None):
        o = super().__new__(cls, ref)
        o.num = num
        return o


def _jour_paris(debut: str) -> str:
    """« 2026-10-26T23:30:00.000Z » → « 2026-10-27 » : le jour à Paris."""
    from zoneinfo import ZoneInfo
    d = dt.datetime.fromisoformat(debut.strip().replace("Z", "+00:00"))
    paris = ZoneInfo("Europe/Paris")
    return (d.replace(tzinfo=paris) if d.tzinfo is None else d.astimezone(paris)).date().isoformat()


def _ref_normale(v):
    """« IN00410 », « 410 », 410 → « IN00410 » ; rien de lisible → None."""
    m = re.fullmatch(r"\s*(?:IN)?0*(\d{1,6})\s*", str(v or ""), re.I)
    return f"IN{int(m.group(1)):05d}" if m else None


def _evenement(it) -> dict:
    """Un événement InterFast, réduit à ce qui sert à reconnaître une case.
    REST (/v1/events) : "reference", "worksite": {"id"} ; MCP
    (consulter_planning) : pas de référence, "worksiteId". Lève ValueError,
    TypeError ou KeyError si l'id ou le début manque."""
    if not isinstance(it, dict):
        raise TypeError("événement illisible")
    w = it.get("worksite")
    chantier = w.get("id") if isinstance(w, dict) else it.get("worksiteId")
    return {"id": int(it["id"]), "titre": (it.get("title") or "").strip(), "ref": _ref_normale(it.get("reference")),
            "jour": _jour_paris(str(it["start"])), "chantier": int(chantier) if chantier else None}


EVENTS_PAGE = 50        # événements par page
EVENTS_PAGES = 10       # garde : une journée d'un chantier n'en a pas 500


async def evenements_rest(filtres: dict, transport=None) -> list:
    """GET /v1/events, page par page. Relevé le 05/11/2026 : {"count": total,
    "items": […], "pageable": …} ; `start`, `end`, `page`, `count`,
    `archived` et `meeting` requis ; `worksites` et `name` (titre ou
    référence) filtrent. Clé dans l'en-tête X-API-KEY, comme pour les
    comptes. 401/403/404 ou corps illisible : _PasEnRest (repli MCP)."""
    k = cle()
    if not k:
        raise InterFastIndisponible(f"Clé {CLES[entreprise()]} absente de l'environnement")
    lus = []
    async with httpx.AsyncClient(timeout=REST_DELAI, transport=transport) as h:
        for page in range(EVENTS_PAGES):
            try:
                r = await h.get(f"{REST_URL}/events", headers={"X-API-KEY": k, "Accept": "application/json"},
                                params={**filtres, "page": page, "count": EVENTS_PAGE,
                                        "archived": "false", "meeting": "false"})
            except httpx.HTTPError as e:
                raise InterFastIndisponible(f"InterFast injoignable : {type(e).__name__}") from e
            if r.status_code in REST_REPLI:
                raise _PasEnRest(f"API REST : HTTP {r.status_code}")
            if r.status_code != 200:
                raise InterFastIndisponible(f"InterFast répond HTTP {r.status_code} à la liste des interventions")
            try:
                d = r.json()
                items, total = d["items"], int(d["count"])
                if not isinstance(items, list):
                    raise TypeError
                lus += [_evenement(it) for it in items]
            except (ValueError, TypeError, KeyError):
                raise _PasEnRest("Réponse REST illisible") from None
            if len(items) < EVENTS_PAGE or len(lus) >= total:
                return lus
    raise InterFastIndisponible(f"Plus de {EVENTS_PAGES} pages d'interventions : lecture arrêtée")


async def _evenements_mcp(jour: str, technicien, transport=None) -> list:
    """Le repli : consulter_planning, par DATE. Pas la semaine ISO : relevé le
    05/11/2026, « 2027-W01 » y rend la semaine du 28/12 au 03/01 (le MCP
    numérote les semaines autrement que l'ISO certaines années), tandis que
    « 2027-01-05 » rend bien le lundi 4 au dimanche 10. Réponse : du JSON
    {"kind": "planning_events", "items": […]}, ou la phrase « Aucun
    événement planifié » quand la semaine est vide. Coupée : illisible."""
    if not technicien:
        raise InterFastIndisponible("Aucun technicien pour chercher dans le planning InterFast")
    texte = await outil("consulter_planning", {"semaine": jour, "technicien": technicien}, transport)
    if "{" not in texte and "Aucun événement planifié" in texte:
        return []
    illisible = InterFastIndisponible(f"Planning InterFast illisible. Début : {texte[:120]}")
    if "(tronqué)" in texte:
        raise illisible
    try:
        d = json.loads(texte[texte.index("{"):texte.rindex("}") + 1])
        items = d.get("items") if isinstance(d, dict) and d.get("kind") == "planning_events" else None
        if not isinstance(items, list):
            raise TypeError
        return [_evenement(it) for it in items]
    except (ValueError, TypeError, KeyError):
        raise illisible from None


async def interventions_du_jour(jour: str, chantier_id, technicien, transport=None) -> list:
    """Les interventions qui commencent, à Paris, le jour donné, sur le
    chantier s'il est connu. Par l'API REST, filtrée sur le jour (±1 pour
    les fuseaux) et le chantier ; par consulter_planning (le planning du
    technicien) seulement si la REST répond 401/403/404 ou illisible.
    Lève InterFastIndisponible si l'on ne peut pas le savoir."""
    j = dt.date.fromisoformat(jour)
    filtres = {"start": f"{j - dt.timedelta(days=1)}T00:00:00", "end": f"{j + dt.timedelta(days=1)}T23:59:59"}
    if chantier_id:
        filtres["worksites"] = int(chantier_id)
    try:
        evts = await evenements_rest(filtres, transport)
    except _PasEnRest as e:
        journal.info("recherche %s : REST refusée (%s), repli sur consulter_planning", jour, e)
        evts = await _evenements_mcp(jour, technicien, transport)
    return [e for e in evts if e["jour"] == jour
            and (not chantier_id or not e["chantier"] or e["chantier"] == int(chantier_id))]


async def cases_existantes(case: dict, transport=None) -> list:
    """Les interventions déjà posées par RHI pour cette case : même titre (la
    description de RHI), même jour à Paris, même chantier. Lève
    InterFastIndisponible si l'on ne peut pas le savoir : dans le doute, on
    ne crée pas (échec fermé)."""
    ferme = "rien n'est créé"
    techniciens = case.get("techniciens") or []
    if not techniciens:
        raise InterFastIndisponible(f"Aucun technicien pour chercher la case dans InterFast : {ferme}")
    try:
        evts = await interventions_du_jour(case["jour"], case.get("chantier_id"), techniciens[0], transport)
    except InterFastIndisponible as e:
        raise InterFastIndisponible(f"Recherche de la case dans InterFast impossible ({e}) : {ferme}") from e
    return [e for e in evts if e["titre"] == case["description"].strip()]


async def num_de_case(ch: str, jour: str, ref: str, chantier_id, technicien, transport=None):
    """L'id interne d'une case RHI déjà posée, par jour + chantier + titre
    (« RHI · CH… · … »), et par la référence quand la REST la donne. Une
    seule candidate : son id ; sinon None (on ne devine pas)."""
    evts = await interventions_du_jour(jour, chantier_id, technicien, transport)
    cands = [e for e in evts if e["titre"].startswith(f"RHI · {ch} · ") and e["ref"] in (None, ref)]
    return cands[0]["id"] if len(cands) == 1 else None


class ReferenceAmbigue(ValueError):
    """La référence donnée au bureau ne désigne pas UNE intervention au jour
    et au chantier de la case."""


async def retrouver_reference(ref: str, jour: str, chantier_id, technicien, transport=None) -> int:
    """« Elle existe : c'est IN00410 » : l'id de l'intervention de cette
    référence qui est au jour et au chantier de la case. Plusieurs
    interventions portent la même référence (05/11/2026) : on retient la
    bonne, ou on refuse avec la liste. Par la REST (filtre `name`), sinon par
    le planning du jour, chaque id relu par reference_de."""
    ref = _ref_normale(ref)
    try:
        toutes = [e for e in await evenements_rest(
            {"name": ref, "start": "2000-01-01T00:00:00", "end": "2100-01-01T00:00:00"}, transport)
            if e["ref"] == ref]
    except _PasEnRest:
        toutes = []
        for e in await _evenements_mcp(jour, technicien, transport):
            if e["jour"] == jour and await reference_de(e["id"], transport) == ref:
                toutes.append(dict(e, ref=ref))
    bonnes = [e for e in toutes if e["jour"] == jour
              and (not chantier_id or e["chantier"] is None or e["chantier"] == int(chantier_id))]
    if len(bonnes) == 1:
        return bonnes[0]["id"]
    liste = ", ".join(f"id {e['id']} le {e['jour']}" + (f" (chantier {e['chantier']})" if e["chantier"] else "")
                      for e in toutes) or "aucune"
    raise ReferenceAmbigue(f"{ref} : {len(bonnes)} intervention(s) de cette référence au jour et au chantier de la "
                           f"case (toutes : {liste}). Vérifier la référence dans InterFast.")


def action_id(recap: str):
    """L'action_id d'un récapitulatif, ou None. Deux jetons différents :
    None aussi — confirmer l'un au hasard pourrait créer la mauvaise case."""
    vus = {m.lower() for m in _ACTION_ID.findall(recap or "")}
    return vus.pop() if len(vus) == 1 else None


async def poser_case(case: dict, transport=None) -> Posee:
    """Pose une case dans le planning InterFast et rend sa référence (IN…).

    Les deux temps du MCP : planifier_intervention prépare et récapitule,
    confirmer_action crée. Depuis le 05/11/2026, le MCP exige l'action_id
    que rend le récapitulatif (l'action expire en 10 minutes) : sans lui,
    rien n'est confirmé et la case reste prête. Un refus (« ❌ », « Aucune
    action ») s'arrête là, sans réessayer avec d'autres paramètres : le MCP
    le demande, et une case posée au mauvais endroit fausse un point
    d'affaire en silence.

    Chaque étape est journalisée (CH, jour, issue) — jamais la clé, ni le
    client, ni les techniciens : c'est ce qui manquait le 05/11/2026 pour
    comprendre pourquoi l'essai sur CH00066 ne posait rien."""
    quoi = f"{case.get('ch')} {case.get('jour')}"
    if not ecriture_permise(case.get("ch")):
        raise EcritureCoupee(
            f"Écriture InterFast coupée pour {case.get('ch')} : seule l'affaire d'essai "
            f"({', '.join(essai()) or 'aucune'}) peut partir avant l'interrupteur (docs/interfast.md).")
    args = {"client": case["client"], "date": case["jour"], "heure": case["heure"],
            "duree": case["duree"], "techniciens": case["techniciens"], "description": case["description"]}
    if case.get("chantier"):
        args["chantier"] = case["chantier"]
    # Jamais deux fois la même case (05/11/2026 : une confirmation lue « sans
    # référence », renvoyée par le bureau, a créé 409 ET 410).
    existantes = await cases_existantes(case, transport)
    if existantes:
        refs = []
        for e in existantes:
            try:
                ref = e["ref"] or await reference_de(e["id"], transport)
            except InterFastIndisponible as err:
                raise InterFastIndisponible(
                    f"Case déjà dans InterFast (id {e['id']}), référence illisible ({err}) : rien n'est créé") from err
            refs.append(ref or f"id {e['id']}")
        if len(existantes) > 1:
            journal.warning("planifier %s : %d cases existantes, rien n'est créé", quoi, len(existantes))
            raise Doublons(f"{len(existantes)} cases RHI identiques déjà dans InterFast ({', '.join(refs)}) : "
                           "supprimer les doublons dans InterFast, puis indiquer la référence gardée")
        if not refs[0].startswith("IN"):
            raise InterFastIndisponible(f"Case déjà dans InterFast ({refs[0]}), référence illisible : rien n'est créé")
        journal.info("planifier %s : case existante reprise, référence %s, id %s", quoi, refs[0], existantes[0]["id"])
        return Posee(refs[0], existantes[0]["id"])
    try:
        recap = await outil("planifier_intervention", args, transport)
    except InterFastIndisponible as e:
        journal.warning("planifier %s : échec (%s)", quoi, type(e).__name__)
        raise
    if any(x in recap for x in _REFUS):
        journal.warning("planifier %s : refus", quoi)
        raise InterFastIndisponible(f"InterFast refuse la case : {recap[:300]}")
    jeton = action_id(recap)
    journal.info("planifier %s : récap reçu, action_id %s", quoi, "trouvé" if jeton else "absent")
    if not jeton:
        raise InterFastIndisponible(
            f"Récapitulatif sans action_id : rien n'est confirmé, la case reste prête. Début : {recap[:200]}")
    # À partir d'ici, tout ce qui n'est pas « créée, IN… » est incertain.
    try:
        reponse = await outil("confirmer_action", {"confirmation": True, "action_id": jeton}, transport)
    except InterFastIndisponible as e:
        journal.warning("confirmer %s : sans réponse (%s)", quoi, type(e).__name__)
        raise CaseSansReference(f"Confirmation sans réponse ({e}) : la case existe peut-être") from e
    if any(x in reponse for x in _REFUS):
        journal.warning("confirmer %s : refus", quoi)
        raise CaseSansReference(f"Confirmation refusée ou déjà faite ({reponse[:300]}) : la case existe peut-être")
    ref = reference_rendue(reponse)
    if not ref:
        journal.warning("confirmer %s : réponse sans référence", quoi)
        raise CaseSansReference(f"Confirmée sans référence : {reponse[:300]}")
    # L'id interne, pour les relectures (la référence n'est pas unique). Le
    # chercher ne fait jamais échouer une case créée : sans lui, la relecture
    # le retrouvera par jour + chantier + titre.
    try:
        num = await num_de_case(case["ch"], case["jour"], ref, case.get("chantier_id"),
                                case["techniciens"][0], transport)
    except InterFastIndisponible:
        num = None
    journal.info("confirmer %s : référence %s, id %s", quoi, ref, num or "à retrouver")
    return Posee(ref, num)


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
