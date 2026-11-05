"""Les plannings relus tout seuls (revue avec Alexis, 01/10/2026).

« Le truc un peu chiant, c'est qu'à chaque fois qu'on change le planning, il
faut aller le redéposer. L'idéal, ce serait qu'il se mette à jour dès qu'il
est enregistré » — « une boucle toutes les cinq minutes ». Les plannings
vivent dans un dossier partagé (OneDrive, SharePoint, Google Drive…) ; un
lien de téléchargement direct par fichier, posé dans RHI_PLANNINGS_URL, et
RHI va le relire toutes les cinq minutes. Il n'importe que si le fichier a
changé (empreinte) : un planning inchangé ne refait rien.

Un lien de partage porte souvent un jeton : il n'est JAMAIS écrit, ni en
base ni à l'écran ni au journal — seulement son hôte et une empreinte.
Le dépôt à la main (onglet Plannings) reste : c'est le secours.

SharePoint par Microsoft Graph (04/11/2026) : un lien dont l'hôte est
graph.microsoft.com (…/v1.0/drives/{driveId}/items/{itemId}/content) est lu
avec un jeton applicatif Entra (rhi/entra.py, scope Graph) — le site ne donne
qu'un droit de lecture (Sites.Selected). Les autres liens https gardent le GET
sans authentification. Graph répond par une redirection vers une adresse de
téléchargement pré-signée : httpx ne lui transmet pas le jeton (autre hôte).
"""
import hashlib
import os
import re
import tempfile
from urllib.parse import urlsplit

from . import base, entra, lecture

TAILLE_MAX = 20_000_000
MINUTES_DEFAUT = 5
HOTE_GRAPH = "graph.microsoft.com"


class LienRefuse(Exception):
    """Un refus qu'on sait expliquer. Le message est le statut montré au
    bureau : il ne recopie jamais le lien ni le jeton."""


# Ce que Graph veut dire, en clair pour le bureau.
STATUTS_GRAPH = {
    401: "Graph : identifiants refusés",
    403: "Graph : pas de droit lecture sur ce site (Sites.Selected)",
    404: "Graph : fichier introuvable (identifiant changé ?)",
}


def est_graph(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == HOTE_GRAPH


def sources() -> list:
    """Les liens de RHI_PLANNINGS_URL (séparés par des espaces ou des retours)."""
    return [u for u in re.split(r"\s+", os.getenv("RHI_PLANNINGS_URL", "").strip()) if u.startswith("https://")]


def minutes() -> int:
    try:
        return max(1, int(os.getenv("RHI_PLANNINGS_MINUTES", MINUTES_DEFAUT)))
    except ValueError:
        return MINUTES_DEFAUT


def etiquette(url: str) -> str:
    """Ce qu'on peut montrer d'un lien : son hôte et une empreinte courte."""
    return f"{urlsplit(url).hostname or '?'} · {hashlib.sha256(url.encode()).hexdigest()[:8]}"


def telecharger(url: str) -> bytes:
    entetes = {}
    if est_graph(url):
        if not entra.configure():
            raise LienRefuse("Graph : lien posé mais variables RHI_GRAPH_TENANT, RHI_GRAPH_CLIENT_ID, "
                             "RHI_GRAPH_SECRET absentes")
        try:
            entetes["Authorization"] = "Bearer " + entra.jeton(entra.SCOPE_GRAPH)
        except entra.IdentifiantsRefuses:
            raise LienRefuse(STATUTS_GRAPH[401]) from None
        except entra.EntraIndisponible as e:
            raise LienRefuse(f"Graph : pas de jeton ({e})") from None
    with entra.client(follow_redirects=True, timeout=60) as client:
        with client.stream("GET", url, headers=entetes) as r:
            if est_graph(url) and r.status_code in STATUTS_GRAPH:
                if r.status_code == 401:
                    entra.oublier(entra.SCOPE_GRAPH)   # le prochain passage en redemande un
                raise LienRefuse(STATUTS_GRAPH[r.status_code])
            r.raise_for_status()
            morceaux, taille = [], 0
            for m in r.iter_bytes():
                taille += len(m)
                if taille > TAILLE_MAX:
                    raise ValueError("fichier de plus de 20 Mo : ce n'est pas un planning")
                morceaux.append(m)
    return b"".join(morceaux)


def _noter(db, source, statut, maintenant, sha=None, nature=None):
    with db:
        db.execute("""INSERT INTO depots_auto(source, sha, nature, importe_le, vu_le, statut)
                      VALUES (?,?,?,?,?,?)
                      ON CONFLICT(source) DO UPDATE SET vu_le=excluded.vu_le, statut=excluded.statut,
                        sha=COALESCE(excluded.sha, depots_auto.sha),
                        nature=CASE WHEN excluded.nature != '' THEN excluded.nature ELSE depots_auto.nature END,
                        importe_le=COALESCE(excluded.importe_le, depots_auto.importe_le)""",
                   (source, sha, nature or "", maintenant if sha else None, maintenant, statut))


def relever(db, entreprise: str = "VIP", lire_lien=telecharger) -> list:
    """Un passage : chaque lien relu, importé s'il a changé. Une erreur sur un
    fichier n'empêche pas les autres, et ne touche jamais au planning en place."""
    maintenant = base._iso(base.maintenant())
    sortie = []
    for url in sources():
        source = etiquette(url)
        try:
            contenu = lire_lien(url)
        except LienRefuse as e:  # Graph : un refus qu'on sait dire
            statut = str(e)
            _noter(db, source, statut, maintenant)
            sortie.append({"source": source, "statut": statut})
            continue
        except Exception as e:  # réseau, 404, lien expiré, trop gros
            # Le message d'erreur peut recopier le lien (jeton compris) : on ne garde que sa nature.
            statut = "injoignable : " + type(e).__name__
            _noter(db, source, statut, maintenant)
            sortie.append({"source": source, "statut": statut})
            continue
        if contenu.lstrip()[:1] == b"<":
            statut = ("le lien donne une page web, pas le fichier : prendre un lien de "
                      "téléchargement direct (OneDrive/SharePoint : ajouter download=1)")
            _noter(db, source, statut, maintenant)
            sortie.append({"source": source, "statut": statut})
            continue
        sha = hashlib.sha256(contenu).hexdigest()
        avant = db.execute("SELECT sha FROM depots_auto WHERE source=?", (source,)).fetchone()
        if avant and avant["sha"] == sha:
            _noter(db, source, "inchangé", maintenant)
            sortie.append({"source": source, "statut": "inchangé"})
            continue
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as t:
            t.write(contenu)
            t.flush()
            try:
                donnees = lecture.lire(t.name, entreprise)
            except lecture.FichierInattendu as e:
                statut = "refusé : " + str(e)[:200]
                _noter(db, source, statut, maintenant)
                sortie.append({"source": source, "statut": statut})
                continue
        res = base.importer(db, donnees)
        statut = f"importé : {res.get('affectations', res.get('etudes', 0))} cases"
        _noter(db, source, statut, maintenant, sha=sha, nature=donnees["nature"])
        sortie.append({"source": source, "statut": statut, "nature": donnees["nature"]})
    return sortie


def etat(db) -> dict:
    connues = {etiquette(u) for u in sources()}
    return {"actif": bool(connues), "minutes": minutes(),
            "fichiers": [dict(r) | {"sha": None} for r in db.execute(
                "SELECT * FROM depots_auto ORDER BY nature, source") if r["source"] in connues]}
