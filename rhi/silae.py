"""Les salariés lus dans Silae, par la route RHI de mcp.vipplus.com.

    GET RHI_SILAE_URL   (https://mcp.vipplus.com/rhi/salaries?dossiers=VIPPLUS,MELMAR,REGA)
    Authorization: Bearer <jeton Entra, scope https://mcp.vipplus.com/mcp/.default>

La route rend une liste de {dossier, matricule, nom, prenom, intitule_emploi,
etablissement, date_entree, date_sortie} — rien d'autre : ni e-mail, ni NIR,
ni salaire. Le serveur garde sa réponse une heure ; RHI la relit une fois par
heure et à la demande du bureau (onglet Personnes, « Relire Silae »).

Une lecture en échec, ou une réponse qui ne ressemble pas au contrat, ne
touche JAMAIS à la table : mieux vaut une liste d'hier qu'une liste vide ou
à moitié remplie, qui ferait croire que des salariés sont partis. Rien n'est
jamais écrit dans Silae : la route ne sait que lire.
"""
import os

import httpx

from . import base, entra

SOURCE = "silae"


class SilaeIndisponible(Exception):
    """Lecture impossible. Le message est montrable : ni jeton, ni lien."""


# Ce que la route veut dire, en clair pour le bureau.
STATUTS = {
    401: "Silae : jeton refusé (401) — identifiants Entra ou audience",
    403: "Silae : accès refusé (403) — rôle RHI.Salaries.Read absent, ou dossier non ouvert à RHI",
    429: "Silae : trop de lectures (429), réessayer dans une minute",
    502: "Silae : lecture incomplète côté serveur (502), réessayer",
}


def url() -> str:
    u = os.getenv("RHI_SILAE_URL", "").strip()
    return u if u.startswith("https://") else ""


def configure() -> bool:
    return bool(url()) and entra.configure()


def _verifier(corps) -> list:
    """Le contrat, ou rien : une seule ligne fausse et toute la réponse est refusée."""
    if not isinstance(corps, list):
        raise SilaeIndisponible("Silae : réponse inattendue (pas une liste)")
    lignes, vues = [], set()
    for l in corps:
        if not isinstance(l, dict) or set(l) != set(base.CHAMPS_SILAE):
            raise SilaeIndisponible("Silae : réponse inattendue (champs différents du contrat)")
        if l["dossier"] not in base.DOSSIERS_SILAE or not isinstance(l["matricule"], str) or not l["matricule"]:
            raise SilaeIndisponible("Silae : réponse inattendue (dossier ou matricule)")
        propre = {k: (l[k] if l[k] is None else str(l[k]).strip()) for k in base.CHAMPS_SILAE}
        for k in ("nom", "prenom", "intitule_emploi", "etablissement"):
            propre[k] = propre[k] or ""
        cle = (propre["dossier"], propre["matricule"])
        if cle in vues:
            raise SilaeIndisponible("Silae : réponse inattendue (matricule en double)")
        vues.add(cle)
        lignes.append(propre)
    return lignes


def lire() -> list:
    if not url():
        raise SilaeIndisponible("RHI_SILAE_URL absent")
    if not entra.configure():
        raise SilaeIndisponible("variables RHI_GRAPH_TENANT, RHI_GRAPH_CLIENT_ID, RHI_GRAPH_SECRET absentes")
    try:
        jeton = entra.jeton(entra.SCOPE_SILAE)
    except entra.EntraIndisponible as e:
        raise SilaeIndisponible(f"Silae : pas de jeton ({e})") from None
    try:
        # Une première lecture côté serveur interroge Silae salarié par
        # salarié : une à deux minutes sur un gros dossier.
        with entra.client(timeout=300) as c:
            r = c.get(url(), headers={"Authorization": f"Bearer {jeton}", "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise SilaeIndisponible(f"Silae injoignable : {type(e).__name__}") from None
    if r.status_code == 401:
        entra.oublier(entra.SCOPE_SILAE)
    if r.status_code in STATUTS:
        raise SilaeIndisponible(STATUTS[r.status_code])
    if r.status_code != 200:
        raise SilaeIndisponible(f"Silae répond {r.status_code}")
    try:
        corps = r.json()
    except ValueError:
        raise SilaeIndisponible("Silae : réponse illisible (pas du JSON)") from None
    return _verifier(corps)


def relire(db, quand) -> dict:
    """Une lecture : la table remplacée si tout est bon, intacte sinon."""
    try:
        lignes = lire()
        if not lignes and db.execute("SELECT COUNT(*) FROM salaries").fetchone()[0]:
            # Une liste vide alors qu'on connaissait des salariés : plus
            # probablement une panne qu'un licenciement général.
            raise SilaeIndisponible("Silae : aucun salarié rendu, la liste en place est gardée")
    except SilaeIndisponible as e:
        base.noter_lecture(db, SOURCE, str(e), quand, reussie=False)
        raise
    bilan = base.importer_salaries(db, lignes, quand)
    base.noter_lecture(db, SOURCE, f"lu : {bilan['salaries']} salariés", quand, reussie=True)
    return bilan
