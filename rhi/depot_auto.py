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
"""
import hashlib
import os
import re
import tempfile
from urllib.parse import urlsplit

from . import base, lecture

TAILLE_MAX = 20_000_000
MINUTES_DEFAUT = 5


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
    import httpx
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        with client.stream("GET", url) as r:
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
