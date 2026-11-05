"""Poser une case : l'action_id du récapitulatif part avec la confirmation.

Le 05/11/2026, l'essai sur CH00066 ne posait rien : le MCP InterFast exige
désormais l'action_id que rend planifier_intervention, et RHI confirmait avec
{"confirmation": true} seulement. Faux MCP, noms inventés."""
import asyncio
import io
import json
import logging
import os

import httpx

from bancs.outils import fin, verif

CLE = "cle-de-banc-41d2e8"
os.environ["INTERFAST_VIP"] = CLE
os.environ.pop("RHI_ENTREPRISE", None)
os.environ["RHI_ECRITURE_ESSAI"] = "CH00066"

journal = io.StringIO()
gestion = logging.StreamHandler(journal)
gestion.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(gestion)
logging.getLogger().setLevel(logging.DEBUG)

from rhi import interfast  # noqa: E402

ACTION = "54ce6167-6dce-4cfd-bfb2-ce0bfadb1922"
# Le récapitulatif tel que relevé le 05/11/2026.
RECAP = ("📋 **Récapitulatif** — intervention pour BAILLEUR FICTIF, le 2026-11-05 à 07:00, 8h.\n"
         "Une fois l'utilisateur d'accord, appelez **confirmer_action** avec confirmation=true et "
         f'action_id="{ACTION}". Pour abandonner: confirmation=false, avec le même action_id. '
         "_Cette action expire dans 10 minutes._")

CASE = {"ch": "CH00066", "jour": "2026-11-05", "client": "BAILLEUR FICTIF", "chantier": "Résidence Essai",
        "heure": "07:00", "duree": "8h", "techniciens": ["Paulo Fictif", "Jeannot Inventé"],
        "description": "RHI · CH00066 · pointage"}


class FauxMCP:
    """N'accepte confirmer_action qu'avec le bon action_id, comme le vrai."""

    def __init__(self, recap=RECAP, attendu=ACTION, refus="texte"):
        self.recap, self.attendu, self.refus, self.appels = recap, attendu, refus, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        verif(CLE not in req.content.decode(), "la clé ne part jamais dans le corps")
        corps = json.loads(req.content)
        nom, args = corps["params"]["name"], corps["params"]["arguments"]
        self.appels.append((nom, args))
        if nom == "planifier_intervention":
            texte = self.recap
        elif nom == "confirmer_action":
            if set(args) != {"confirmation", "action_id"}:
                return self._erreur("confirmation et action_id sont requis")
            if args["action_id"] != self.attendu or args["confirmation"] is not True:
                if self.refus == "jsonrpc":
                    return self._erreur("Action inconnue ou expirée")
                texte = "❌ Aucune action en attente pour cet identifiant (expirée ?)."
            else:
                texte = "✅ Intervention créée : IN00512, le 05/11/2026 à 07:00."
        else:
            raise AssertionError(f"outil inattendu : {nom}")
        res = {"content": [{"type": "text", "text": texte}]}
        return httpx.Response(200, text="data: " + json.dumps({"result": res}) + "\n\n")

    @staticmethod
    def _erreur(message):
        return httpx.Response(200, text="data: " + json.dumps({"error": {"code": -32602, "message": message}}) + "\n\n")

    def noms(self):
        return [n for n, _ in self.appels]


def poser(faux):
    return asyncio.run(interfast.poser_case(dict(CASE), httpx.MockTransport(faux)))


messages = []

# ── L'extraction, tolérante ──
for forme in (f'action_id="{ACTION}"', f"action_id={ACTION}", f"action_id=`{ACTION}`",
              f"action_id='{ACTION}'", f'"action_id": "{ACTION}"', f"ACTION_ID = {ACTION.upper()}",
              f"avec `action_id={ACTION}`."):
    verif(interfast.action_id(f"… {forme} …") == ACTION, f"action_id lu dans « {forme} »")
verif(interfast.action_id(RECAP) == ACTION, "action_id lu dans le récapitulatif réel (cité deux fois : un seul)")
verif(interfast.action_id("appelez confirmer_action avec confirmation=true") is None, "pas d'action_id : None")
verif(interfast.action_id('action_id="pas-un-uuid"') is None, "un faux jeton n'est pas un action_id")
verif(interfast.action_id(f'action_id="{ACTION}" puis action_id="{ACTION[:-1]}0"') is None,
      "deux jetons différents : on ne choisit pas au hasard")

# ── Le bon action_id : la case est posée ──
f = FauxMCP()
ref = poser(f)
verif(ref == "IN00512", f"case posée, référence rendue : {ref}")
verif(f.noms() == ["planifier_intervention", "confirmer_action"], f"deux temps : {f.noms()}")
verif(f.appels[1][1] == {"confirmation": True, "action_id": ACTION}, f"confirmation avec l'action_id : {f.appels[1][1]}")

# ── Récapitulatif sans action_id : aucune confirmation ──
f = FauxMCP(recap="📋 Récapitulatif … Confirmez avec confirmer_action.")
try:
    poser(f)
    verif(False, "sans action_id : erreur attendue")
except interfast.CaseSansReference:
    verif(False, "sans action_id, rien n'est parti : ce n'est pas « à vérifier »")
except interfast.InterFastIndisponible as e:
    messages.append(str(e))
    verif(f.noms() == ["planifier_intervention"], f"aucune confirmation envoyée : {f.noms()}")
    verif("sans action_id" in str(e) and "Récapitulatif" in str(e), f"dit, avec le début du récapitulatif : {e}")

# ── Mauvais action_id : réponse incertaine → à vérifier ──
for refus in ("texte", "jsonrpc"):
    f = FauxMCP(attendu="00000000-0000-0000-0000-000000000000", refus=refus)
    try:
        poser(f)
        verif(False, "mauvais action_id : erreur attendue")
    except interfast.CaseSansReference as e:
        messages.append(str(e))
        verif(f.noms() == ["planifier_intervention", "confirmer_action"], "la confirmation est partie")
        verif("peut-être" in str(e), f"mauvais action_id ({refus}) : CaseSansReference, à vérifier : {e}")

# ── Le journal : chaque étape, sans clé ni données personnelles ──
trace = journal.getvalue()
for ligne in ("planifier CH00066 2026-11-05 : récap reçu, action_id trouvé",
              "confirmer CH00066 2026-11-05 : référence IN00512",
              "planifier CH00066 2026-11-05 : récap reçu, action_id absent",
              "confirmer CH00066 2026-11-05 : refus",
              "confirmer CH00066 2026-11-05 : sans réponse (InterFastIndisponible)"):
    verif(ligne in trace, f"journal : « {ligne} »")
verif("HTTP Request" in trace and "/mcp/http" in trace, "le journal de httpx a bien été capté")
verif(CLE not in trace, "la clé n'est dans aucun journal")
for perso in ("BAILLEUR FICTIF", "Paulo", "Jeannot", "Résidence Essai"):
    verif(perso not in "\n".join(l for l in trace.splitlines() if l.startswith("rhi.interfast")),
          f"le journal de RHI ne contient pas « {perso} »")
verif(not any(CLE in m for m in messages), "la clé n'est dans aucun message")

fin("banc-confirmer")
