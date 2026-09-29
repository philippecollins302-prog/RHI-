"""InterFast — la base de tout, et la destination des heures.

Même protocole que dans Ali Baba (MCP en JSON-RPC, réponse en SSE `data:`),
même compte : la serrurerie, c'est la clé `INTERFAST_VIP` (VIP Plus). La clé
vit dans l'environnement Clever Cloud, JAMAIS dans ce dépôt, qui est public.

Ce qu'on NE sait PAS encore (29/09/2026), et qu'il faut apprendre avec une
vraie clé avant d'écrire la moindre heure :
  1. quel outil du MCP liste les affaires (les CH) ;
  2. quel outil pose des heures sur une affaire. Les outils qu'Ali Baba
     connaît (planifier_intervention, creer_tache…) visent un CLIENT, pas un
     CH : les utiliser tels quels poserait les heures au mauvais endroit.
`GET /api/interfast/outils` (bureau) affiche la liste exacte des outils :
c'est le premier geste à faire avec la clé.

D'ici là, ECRITURE reste à False : les heures vivent dans RHI et s'exportent
en CSV. Une écriture ratée dans InterFast fausse un point d'affaire en
silence ; un export manuel, lui, se relit.
"""
import json
import os

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
    async with httpx.AsyncClient(timeout=40, transport=transport) as h:
        r = await h.post(f"{MCP_URL}?apiKey={k}", json=corps, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"})
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


async def envoyer_heures(*_args, **_kw):
    if not ECRITURE:
        raise InterFastIndisponible(
            "Écriture InterFast coupée (rhi/interfast.py, ECRITURE = False) : "
            "l'outil qui pose des heures sur un CH n'est pas encore identifié.")
    raise NotImplementedError("À écrire une fois l'outil InterFast connu")
