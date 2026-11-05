"""Les jetons Entra : un jeu d'identifiants, un jeton par scope, gardé jusqu'à
cinq minutes avant son expiration, jamais montré.

Faux serveur Entra (httpx.MockTransport) : aucun appel réseau réel."""
import os
import urllib.parse

import httpx

from bancs.outils import fin, verif

SECRET = "secret-tres-secret-0123"
os.environ.update({"RHI_GRAPH_TENANT": "tenant-fictif", "RHI_GRAPH_CLIENT_ID": "client-fictif",
                   "RHI_GRAPH_SECRET": SECRET})

from rhi import entra  # noqa: E402

demandes = []
refuser = {"oui": False}


def entra_faux(req: httpx.Request) -> httpx.Response:
    corps = dict(urllib.parse.parse_qsl(req.content.decode()))
    demandes.append((req.url.path, corps))
    if refuser["oui"]:
        return httpx.Response(401, json={"error": "invalid_client",
                                         "error_description": f"AADSTS7000215 secret {corps['client_secret']}"})
    n = len(demandes)
    return httpx.Response(200, json={"access_token": f"jeton-{n}-{corps['scope']}", "expires_in": 3600})


entra.TRANSPORT = httpx.MockTransport(entra_faux)
temps = {"t": 1000.0}
entra.horloge = lambda: temps["t"]

# ── Un jeton obtenu, avec les bons paramètres ──
j = entra.jeton(entra.SCOPE_GRAPH)
chemin, corps = demandes[0]
verif(chemin == "/tenant-fictif/oauth2/v2.0/token", f"le point de jeton du tenant : {chemin}")
verif(corps == {"grant_type": "client_credentials", "client_id": "client-fictif", "client_secret": SECRET,
                "scope": "https://graph.microsoft.com/.default"}, f"client credentials, scope Graph : {corps}")
verif(j.startswith("jeton-1-"), "le jeton rendu est celui d'Entra")

# ── Gardé par scope ──
verif(entra.jeton(entra.SCOPE_GRAPH) == j and len(demandes) == 1, "redemandé : servi depuis la mémoire, Entra pas rappelé")
temps["t"] += 1000      # le jeton Silae est demandé plus tard : il expirera plus tard
s = entra.jeton(entra.SCOPE_SILAE)
verif(len(demandes) == 2 and s != j and demandes[1][1]["scope"] == "https://mcp.vipplus.com/mcp/.default",
      "un autre scope : un autre jeton, mêmes identifiants")
verif(demandes[1][1]["client_id"] == "client-fictif", "les mêmes identifiants servent aux deux")

# ── Expiration : redemandé à moins de cinq minutes de la fin ──
temps["t"] += 3600 - 301 - 1000
verif(entra.jeton(entra.SCOPE_GRAPH) == j and len(demandes) == 2, "à 5 min 01 de l'expiration : encore servi")
temps["t"] += 2
j2 = entra.jeton(entra.SCOPE_GRAPH)
verif(len(demandes) == 3 and j2 != j, "à moins de 5 min : un jeton neuf est demandé")
verif(entra.jeton(entra.SCOPE_SILAE) == s, "le jeton Silae, lui, n'a pas bougé")

# ── oublier() : après un 401 du service, le suivant est redemandé ──
entra.oublier(entra.SCOPE_SILAE)
verif(entra.jeton(entra.SCOPE_SILAE) != s and len(demandes) == 4, "oublié : redemandé")

# ── 401 d'Entra : refus clair, sans le secret ──
entra.oublier()
refuser["oui"] = True
try:
    entra.jeton(entra.SCOPE_GRAPH)
    verif(False, "un 401 d'Entra doit lever une erreur")
except entra.IdentifiantsRefuses as e:
    verif("identifiants refusés" in str(e) and "invalid_client" in str(e), f"le refus est dit : {e}")
    verif(SECRET not in str(e) and "AADSTS" not in str(e), "le message ne recopie ni le secret ni le corps d'Entra")
verif(entra.essayer(entra.SCOPE_GRAPH) is False, "santé : jeton_ok faux")
refuser["oui"] = False
verif(entra.essayer(entra.SCOPE_GRAPH) is True, "identifiants corrigés : jeton_ok vrai")

# ── Variables absentes ──
os.environ.pop("RHI_GRAPH_SECRET")
entra.oublier()
verif(entra.configure() is False and entra.essayer(entra.SCOPE_SILAE) is False, "sans secret : non configuré")
try:
    entra.jeton(entra.SCOPE_SILAE)
    verif(False, "sans variables, pas de jeton")
except entra.EntraIndisponible as e:
    verif("RHI_GRAPH_SECRET" in str(e), f"le message dit quelles variables poser : {e}")

# ── Entra injoignable : une erreur montrable, pas une trace ──
os.environ["RHI_GRAPH_SECRET"] = SECRET


def panne(req):
    raise httpx.ConnectError("réseau coupé", request=req)


entra.TRANSPORT = httpx.MockTransport(panne)
try:
    entra.jeton(entra.SCOPE_GRAPH)
    verif(False, "panne réseau : erreur attendue")
except entra.EntraIndisponible as e:
    verif("injoignable" in str(e), f"panne réseau dite : {e}")

fin("banc-entra")
