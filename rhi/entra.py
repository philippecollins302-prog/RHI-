"""Les jetons Entra de RHI : un seul jeu d'identifiants applicatifs, deux usages.

Les plannings vivent dans SharePoint (lus par Microsoft Graph) et les
salariés dans Silae (lus par la route RHI de mcp.vipplus.com). Les deux
acceptent un jeton Entra obtenu par « client credentials » avec les MÊMES
identifiants (RHI_GRAPH_TENANT, RHI_GRAPH_CLIENT_ID, RHI_GRAPH_SECRET) ;
seul le scope change, et donc le jeton : un jeton Graph n'ouvre pas Silae, et
inversement.

Un jeton est gardé en mémoire, par scope, jusqu'à cinq minutes avant son
expiration. Il n'est JAMAIS écrit : ni en base, ni à l'écran, ni au journal.
Le secret non plus — même pas dans un message d'erreur (le dépôt est public,
et un message d'erreur finit toujours affiché quelque part).
"""
import os
import threading
import time

import httpx

SCOPE_GRAPH = "https://graph.microsoft.com/.default"
SCOPE_SILAE = "https://mcp.vipplus.com/mcp/.default"

# Un jeton n'est plus servi à moins de cinq minutes de son expiration : un
# téléchargement de planning ou une lecture Silae peut durer une minute.
MARGE_S = 300

# Le transport HTTP de tous les appels sortants Entra, Graph et Silae : les
# bancs y posent un faux serveur (httpx.MockTransport), jamais le réseau réel.
TRANSPORT = None
# L'horloge est remplaçable : un banc fait expirer un jeton sans attendre une heure.
horloge = time.monotonic

_CACHE: dict = {}          # scope -> (jeton, expire_a selon horloge())
_VERROU = threading.Lock()


class EntraIndisponible(Exception):
    """Pas de jeton. Le message est montrable tel quel : il ne porte ni
    jeton, ni secret, ni lien."""


class IdentifiantsRefuses(EntraIndisponible):
    """Entra refuse les identifiants (secret expiré ou faux, application inconnue)."""


def reglage() -> dict:
    return {"tenant": os.getenv("RHI_GRAPH_TENANT", "").strip(),
            "client_id": os.getenv("RHI_GRAPH_CLIENT_ID", "").strip(),
            "secret": os.getenv("RHI_GRAPH_SECRET", "").strip()}


def configure() -> bool:
    """Les trois variables sont posées (on ne dit pas lesquelles valent quoi)."""
    return all(reglage().values())


def client(**options) -> httpx.Client:
    return httpx.Client(transport=TRANSPORT, **options)


def oublier(scope: str | None = None) -> None:
    """Jette un jeton gardé (tous si scope est None) : après un 401, le
    prochain appel en redemande un."""
    with _VERROU:
        if scope is None:
            _CACHE.clear()
        else:
            _CACHE.pop(scope, None)


def jeton(scope: str) -> str:
    """Un jeton pour ce scope : celui gardé s'il vaut encore plus de cinq
    minutes, sinon un neuf demandé à Entra."""
    with _VERROU:
        garde = _CACHE.get(scope)
        if garde and garde[1] - horloge() > MARGE_S:
            return garde[0]
        r = reglage()
        if not all(r.values()):
            raise EntraIndisponible("variables RHI_GRAPH_TENANT, RHI_GRAPH_CLIENT_ID, RHI_GRAPH_SECRET absentes")
        url = f"https://login.microsoftonline.com/{r['tenant']}/oauth2/v2.0/token"
        try:
            with client(timeout=20) as c:
                rep = c.post(url, data={"grant_type": "client_credentials", "client_id": r["client_id"],
                                        "client_secret": r["secret"], "scope": scope})
        except httpx.HTTPError as e:
            raise EntraIndisponible(f"Entra injoignable : {type(e).__name__}") from None
        if rep.status_code in (400, 401):
            # Le corps d'Entra ne contient pas le secret, mais il n'apprend rien
            # d'utile au bureau : seul son code d'erreur est gardé.
            try:
                code = rep.json().get("error", "")
            except ValueError:
                code = ""
            raise IdentifiantsRefuses(f"identifiants refusés par Entra ({rep.status_code} {code})".strip())
        if rep.status_code != 200:
            raise EntraIndisponible(f"Entra répond {rep.status_code}")
        try:
            corps = rep.json()
            valeur, duree = corps["access_token"], int(corps.get("expires_in", 3599))
        except (ValueError, KeyError, TypeError):
            raise EntraIndisponible("réponse d'Entra illisible") from None
        _CACHE[scope] = (valeur, horloge() + duree)
        return valeur


def essayer(scope: str) -> bool:
    """Pour /api/sante/detail : un jeton s'obtient-il ? Oui ou non, rien d'autre."""
    if not configure():
        return False
    try:
        jeton(scope)
        return True
    except EntraIndisponible:
        return False
