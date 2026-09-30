"""La base : personnes, affaires, planning importé, pointages.

SQLite dans un seul fichier (`RHI_DONNEES/rhi.db`) : sept tablettes et
quelques téléphones, pas de quoi justifier un serveur de base de données.

Règle d'or du pointage, tirée de la réunion du 29/09/2026 : « que ce ne soit
jamais bloqué ». Démarrer une affaire arrête la précédente ; un CH inconnu est
accepté (et signalé au bureau) ; un pointage oublié reste ouvert (et signalé)
plutôt que d'être refusé. Tout ce qui est douteux se corrige au bureau, rien
ne se refuse sur la tablette.
"""
import datetime as dt
import re
import os
import sqlite3
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from .textes import normaliser

PARIS = ZoneInfo("Europe/Paris")

# Au-delà, un pointage ouvert est presque sûrement un « j'ai oublié d'arrêter ».
DUREE_SUSPECTE_H = 10

# Le temps hors affaire. Mesurer le temps perdu fait partie de la demande
# (« on verra le temps réel de fab… et le temps perdu ») : ces motifs sont
# pointés comme une affaire, sans CH.
#
# La liste est celle d'Alexis (30/09/2026) : quatre motifs, tous imputés au
# CH des frais généraux dans InterFast, « Autre » à valider par le
# contrôleur. Le trajet n'en est plus un : il compte dans le chantier (on
# pointe au départ, le retour du soir va sur le dernier chantier). Attente
# matière et panne ne sont pas retenues.
MOTIFS = {
    "RANGEMENT": "Rangement (atelier)",
    "ENTRETIEN": "Entretien machine (atelier)",
    "FORMATION": "Formation",
    "AUTRE": "Autre (à valider)",
}
# Les motifs retirés restent lisibles dans l'historique : un RHI déjà
# pointé ne perd pas son libellé. Ils ne sont plus proposés, et un geste
# qui en porte encore un (tablette restée hors ligne) tombe sur « Autre ».
MOTIFS_RETIRES = {
    "ATTENTE_MATIERE": "Attente matière / plans",
    "PANNE": "Panne machine",
    "TRAJET": "Trajet · dépôt",
}
LIBELLES_MOTIFS = {**MOTIFS_RETIRES, **MOTIFS}


def ch_frais_generaux() -> str:
    """Le CH InterFast où tombe le temps hors affaire (« CH FG SER »).

    Réglable par RHI_CH_FRAIS_GENERAUX ; par défaut, celui de VIP Plus donné
    par Alexis le 30/09/2026. Alfa n'en a pas encore : vide, le hors affaire
    reste en dehors d'InterFast, comme avant."""
    v = os.getenv("RHI_CH_FRAIS_GENERAUX")
    if v is not None:
        return v.strip().upper()
    return {"VIP": "CH00081"}.get(os.getenv("RHI_ENTREPRISE", "VIP").strip().upper(), "")


def ch_divers() -> str:
    """Le CH des interventions sans numéro d'affaire (« CH DIVERS »).

    Alexis, 30/09/2026 : à créer dans InterFast, avec la possibilité de
    transférer ensuite les heures vers le bon CH. Tant que son numéro n'est
    pas réglé (RHI_CH_DIVERS), la tablette ne le propose pas."""
    return (os.getenv("RHI_CH_DIVERS") or "").strip().upper()


# Les alertes qui informent sans rien dire de faux : elles n'empêchent pas la
# validation d'un geste (valider_tout).
INFORMATIVES = ("Pointé hors ligne", "CH DIVERS")


def _motif(motif):
    """Un motif proposé, ou « Autre » : jamais un code inconnu en base."""
    return motif if motif in MOTIFS else "AUTRE"


SCHEMA = """
CREATE TABLE IF NOT EXISTS personnes (
  nom TEXT PRIMARY KEY,
  equipe TEXT NOT NULL,            -- 'atelier' | 'pose'
  actif INTEGER NOT NULL DEFAULT 1,
  vu_le TEXT,
  nom_complet TEXT NOT NULL DEFAULT '',  -- « Laurent Dupont », depuis InterFast
  interfast_user_id INTEGER,
  cout_interfast REAL,                    -- coût horaire lu dans InterFast (souvent 0)
  cout_horaire REAL                       -- coût horaire saisi au bureau : prioritaire
);
CREATE TABLE IF NOT EXISTS utilisateurs_interfast (
  id INTEGER PRIMARY KEY,
  prenom TEXT NOT NULL,
  nom TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT '',
  archive INTEGER NOT NULL DEFAULT 0,
  cout REAL
);
CREATE TABLE IF NOT EXISTS etudes_bet (
  ch TEXT,                         -- NULL : étude sans CH (le BET n'en met pas toujours)
  chantier TEXT NOT NULL DEFAULT '',
  intitule TEXT NOT NULL,
  debut TEXT, fin TEXT,
  statut TEXT NOT NULL DEFAULT '',
  commentaire TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS traitements (
  ch TEXT NOT NULL,
  debut TEXT NOT NULL,
  fin TEXT NOT NULL,
  libelle TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS constats (
  jour TEXT NOT NULL,              -- jour de l'analyse
  cle TEXT NOT NULL,               -- même constat d'une analyse à l'autre
  niveau TEXT NOT NULL,
  texte TEXT NOT NULL,
  PRIMARY KEY (jour, cle)
);
CREATE TABLE IF NOT EXISTS validations (
  personne TEXT NOT NULL,
  lundi TEXT NOT NULL,
  par TEXT NOT NULL,
  le TEXT NOT NULL,
  PRIMARY KEY (personne, lundi)
);
CREATE TABLE IF NOT EXISTS affaires (
  ch TEXT PRIMARY KEY,
  chantier TEXT NOT NULL DEFAULT '',
  conduc TEXT NOT NULL DEFAULT '',
  heures_prevues REAL,             -- somme du plan de charge atelier
  source TEXT NOT NULL,            -- 'planning' | 'interfast' | 'tablette'
  maj TEXT,
  client TEXT NOT NULL DEFAULT '', -- les quatre suivants viennent d'InterFast
  titre TEXT NOT NULL DEFAULT '',
  statut TEXT NOT NULL DEFAULT '', -- 'En cours' | 'Non démarré' | 'Terminé'
  interfast_id INTEGER
);
CREATE TABLE IF NOT EXISTS lignes_prevues (
  ch TEXT NOT NULL,
  designation TEXT NOT NULL,
  heures REAL
);
CREATE TABLE IF NOT EXISTS planning (
  personne TEXT NOT NULL,
  jour TEXT NOT NULL,
  ch TEXT,                         -- NULL : tâche sans CH (pliage, débit…)
  libelle TEXT NOT NULL DEFAULT '',
  origine TEXT NOT NULL            -- 'atelier' | 'pose'
);
CREATE INDEX IF NOT EXISTS planning_jour ON planning(jour, personne);
CREATE TABLE IF NOT EXISTS pointages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  personne TEXT NOT NULL,
  ch TEXT,                         -- NULL si motif hors affaire
  motif TEXT,
  libelle TEXT NOT NULL DEFAULT '',
  debut TEXT NOT NULL,             -- ISO, heure de Paris
  fin TEXT,
  appareil TEXT NOT NULL DEFAULT '',
  corrige TEXT,                    -- qui a corrigé au bureau, et quand
  annule INTEGER NOT NULL DEFAULT 0,
  interfast TEXT                   -- réf. de la ligne créée dans InterFast
);
CREATE TABLE IF NOT EXISTS cases_interfast (
  ch TEXT NOT NULL,
  jour TEXT NOT NULL,
  ref TEXT NOT NULL,               -- IN00123, rendu par InterFast
  posee_le TEXT NOT NULL,
  terminee INTEGER NOT NULL DEFAULT 0,   -- le ✅ du planning InterFast, relu
  relue_le TEXT,
  num INTEGER,                     -- id interne InterFast (1819630), trouvé à la relecture
  PRIMARY KEY (ch, jour)
);
CREATE TABLE IF NOT EXISTS courriers (
  jour TEXT NOT NULL,
  quoi TEXT NOT NULL,              -- 'marche'
  statut TEXT NOT NULL,            -- envoye | simule | sans destinataire | erreur: …
  le TEXT NOT NULL,
  PRIMARY KEY (jour, quoi)
);
CREATE TABLE IF NOT EXISTS heures_interfast (
  ref TEXT NOT NULL,               -- la case (IN00123)
  user_id INTEGER NOT NULL,
  debut TEXT NOT NULL,             -- heure de Paris, saisie à la clôture
  fin TEXT NOT NULL,
  minutes INTEGER NOT NULL,
  pause INTEGER NOT NULL,
  PRIMARY KEY (ref, user_id)
);
CREATE INDEX IF NOT EXISTS pointages_personne ON pointages(personne, debut);
CREATE INDEX IF NOT EXISTS pointages_ch ON pointages(ch);
"""


def chemin_base() -> Path:
    dossier = Path(os.getenv("RHI_DONNEES", "donnees"))
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / "rhi.db"


def connexion(chemin=None) -> sqlite3.Connection:
    # FastAPI sert les routes async et sync sur des fils différents.
    db = sqlite3.connect(chemin or chemin_base(), check_same_thread=False)
    db.row_factory = sqlite3.Row
    # PAS de WAL : sur Clever Cloud la base vit sur un FS Bucket (disque
    # réseau), où le mode WAL ne fonctionne pas — leçon d'Ali Baba, qui
    # tourne en « delete » sur le même hébergement. Vérifiable : /api/sante.
    db.execute("PRAGMA journal_mode=DELETE")
    db.executescript(SCHEMA)
    # Une base plus ancienne que ces colonnes les reçoit ici : on ne perd
    # jamais une base de production pour une colonne ajoutée. Une fois par
    # base et par processus.
    cle = str(chemin or chemin_base())
    if cle not in _MIGREES:
        for table, colonnes in AJOUTS.items():
            presentes = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
            for col, decl in colonnes:
                if col not in presentes:
                    ajouter_colonne(db, table, col, decl)
        _MIGREES.add(cle)
    return db


_MIGREES = set()


def ajouter_colonne(db, table, col, decl):
    """ALTER TABLE qui supporte la course : deux requêtes ouvrent la base au
    même instant, toutes deux voient la colonne absente, la seconde trouve
    la colonne ajoutée par la première (constaté le 29/09/2026 : « duplicate
    column name: recu » au chargement de la tablette)."""
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e):
            raise


AJOUTS = {
    "affaires": [("client", "TEXT NOT NULL DEFAULT ''"), ("titre", "TEXT NOT NULL DEFAULT ''"),
                 ("statut", "TEXT NOT NULL DEFAULT ''"), ("interfast_id", "INTEGER"),
                 # Vendu HT : devis signés/payés dont le titre porte le CH (NULL = non trouvé).
                 ("vendu_ht", "REAL"), ("devis_refs", "TEXT NOT NULL DEFAULT ''"), ("vendu_maj", "TEXT")],
    "personnes": [("nom_complet", "TEXT NOT NULL DEFAULT ''"), ("interfast_user_id", "INTEGER"),
                  ("cout_interfast", "REAL"), ("cout_horaire", "REAL"),
                  # Ajouté au bureau (RH), pas venu d'un planning : un intérimaire.
                  ("interim", "INTEGER NOT NULL DEFAULT 0")],
    # Heure de RÉCEPTION, quand elle diffère de l'heure du geste : pointé hors
    # ligne, rejoué au retour du réseau.
    "pointages": [("recu", "TEXT")],
    "cases_interfast": [("num", "INTEGER")],
    # Pour la marche en avant : semaines de fab et commentaire du plan de charge.
    "lignes_prevues": [("semaines", "TEXT NOT NULL DEFAULT ''"), ("commentaire", "TEXT NOT NULL DEFAULT ''"),
                       ("chantier", "TEXT NOT NULL DEFAULT ''")],
}

# Écart au-delà duquel un geste est dit « rejoué » (hors ligne).
DIFFERE_S = 120


class SemaineValidee(ValueError):
    """Correction refusée : la semaine a été validée au bureau."""


def maintenant() -> dt.datetime:
    return dt.datetime.now(PARIS).replace(microsecond=0, tzinfo=None)


def _iso(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat(timespec="seconds")


# ═══════════════════════ IMPORT DES PLANNINGS ═══════════════════════

def chantiers_de(libelle: str, codes: list) -> dict:
    """{CH: nom du chantier} tiré d'une case de planning.

    Une case = « CHANTIER / TRAVAUX », et parfois deux chantiers à la suite
    (« LES PINS / STRUCTURE BALCON / LE PORT / POSE PORTAIL », CH00901/CH00903).
    On n'attribue un nom que quand le compte tombe juste : mieux vaut un
    nom vide qu'on complète qu'un CH baptisé du chantier voisin."""
    morceaux = [m for m in libelle.split(" / ") if m]
    if len(codes) == 1 and morceaux:
        return {codes[0]: morceaux[0]}
    if codes and len(morceaux) == 2 * len(codes):
        return {ch: morceaux[2 * i] for i, ch in enumerate(codes)}
    return {}


def importer(db, donnees: dict) -> dict:
    """Range le résultat de lecture.lire() dans la base.

    Le planning d'une origine est REMPLACÉ en entier à chaque import : le
    fichier d'Alexis change tous les jours, c'est lui qui fait foi. Les
    pointages, eux, ne sont jamais touchés par un import."""
    origine = donnees["nature"]
    now = _iso(maintenant())
    if origine == "bet":
        with db:
            db.execute("DELETE FROM etudes_bet")
            for e in donnees["etudes"]:
                for ch in (e["codes"] or [None]):
                    db.execute("INSERT INTO etudes_bet VALUES (?,?,?,?,?,?,?)",
                               (ch, e["chantier"], e["intitule"],
                                e["debut"].isoformat() if e["debut"] else None,
                                e["fin"].isoformat() if e["fin"] else None, e["statut"], e["commentaire"]))
        return {"nature": "bet", "personnes": 0, "affectations": 0, "etudes": len(donnees["etudes"])}
    with db:
        for nom in donnees["personnes"]:
            db.execute("""INSERT INTO personnes(nom, equipe, vu_le) VALUES (?,?,?)
                          ON CONFLICT(nom) DO UPDATE SET vu_le=excluded.vu_le""",
                       (nom, origine, now))
        db.execute("DELETE FROM planning WHERE origine=?", (origine,))
        for a in donnees["affectations"]:
            noms = chantiers_de(a["libelle"], a["codes"])
            for ch in (a["codes"] or [None]):
                db.execute("INSERT INTO planning VALUES (?,?,?,?,?)",
                           (a["personne"], a["jour"].isoformat(), ch, a["libelle"], origine))
                if ch:
                    db.execute("""INSERT INTO affaires(ch, chantier, source, maj)
                                  VALUES (?,?, 'planning', ?)
                                  ON CONFLICT(ch) DO UPDATE SET chantier=excluded.chantier
                                  WHERE affaires.chantier = '' """, (ch, noms.get(ch, ""), now))
        if "traitements" in donnees:
            db.execute("DELETE FROM traitements")
            for t in donnees["traitements"]:
                db.execute("INSERT INTO traitements VALUES (?,?,?,?)",
                           (t["ch"], t["debut"].isoformat(), t["fin"].isoformat(), t["libelle"]))
        if "affaires" in donnees:
            db.execute("DELETE FROM lignes_prevues")
            totaux = {}
            for l in donnees["affaires"]:
                # Les lignes sans CH sont gardées (ch = '') : la marche en avant
                # les rapproche d'une pose par le nom du chantier.
                db.execute("""INSERT INTO lignes_prevues(ch, designation, heures, semaines, commentaire, chantier)
                              VALUES (?,?,?,?,?,?)""",
                           (l["ch"] or "", l["designation"], l["heures"], ",".join(map(str, l["semaines"])),
                            l["commentaire"], l["chantier"]))
                if not l["ch"]:
                    continue
                totaux.setdefault(l["ch"], [l["chantier"], l["conduc"], 0.0])
                totaux[l["ch"]][2] += l["heures"] or 0
            for ch, (chantier, conduc, h) in totaux.items():
                db.execute("""INSERT INTO affaires(ch, chantier, conduc, heures_prevues, source, maj)
                              VALUES (?,?,?,?, 'planning', ?)
                              ON CONFLICT(ch) DO UPDATE SET chantier=excluded.chantier,
                                conduc=excluded.conduc, heures_prevues=excluded.heures_prevues,
                                maj=excluded.maj""", (ch, chantier, conduc, h, now))
    return {"nature": origine, "personnes": len(donnees["personnes"]),
            "affectations": len(donnees["affectations"])}


def importer_chantiers(db, chantiers: list) -> dict:
    """Range les chantiers lus dans InterFast (interfast.chantiers()).

    InterFast fait foi pour le client, le titre et le statut. Le nom court
    du planning (« LES PINS ») est gardé s'il existe : c'est celui que les
    gars reconnaissent sur la tablette ; sinon on prend le titre InterFast."""
    now = _iso(maintenant())
    with db:
        for c in chantiers:
            db.execute("""INSERT INTO affaires(ch, chantier, source, maj, client, titre, statut, interfast_id)
                          VALUES (?,?, 'interfast', ?,?,?,?,?)
                          ON CONFLICT(ch) DO UPDATE SET client=excluded.client, titre=excluded.titre,
                            statut=excluded.statut, interfast_id=excluded.interfast_id, maj=excluded.maj,
                            chantier=CASE WHEN affaires.chantier = '' THEN excluded.chantier
                                          ELSE affaires.chantier END,
                            source=CASE WHEN affaires.source = 'tablette' THEN 'interfast'
                                        ELSE affaires.source END""",
                       (c["ch"], c["titre"], now, c["client"], c["titre"], c["statut"], c["id"]))
    inconnus = [r["ch"] for r in db.execute(
        "SELECT ch FROM affaires WHERE interfast_id IS NULL ORDER BY ch")]
    return {"chantiers": len(chantiers), "absents_d_interfast": inconnus}


def importer_utilisateurs(db, utilisateurs: list) -> dict:
    """Garde les comptes InterFast et relie chaque personne de RHI au sien.

    Les plannings ne donnent qu'un prénom (« LAURENT ») ; InterFast a prénom
    et nom. On ne relie que sur une correspondance UNIQUE parmi les comptes
    non archivés : deux « Laurent » et c'est au bureau de trancher, jamais
    au hasard — des heures posées sur le mauvais homme faussent deux RHI.
    Une liaison faite à la main au bureau n'est jamais défaite ici."""
    from .textes import normaliser
    with db:
        db.execute("DELETE FROM utilisateurs_interfast")
        for u in utilisateurs:
            db.execute("INSERT INTO utilisateurs_interfast VALUES (?,?,?,?,?,?)",
                       (u["id"], u["prenom"], u["nom"], u["role"], int(u["archive"]), u.get("cout")))
    actifs = [u for u in utilisateurs if not u.get("archive")]
    archives = [u for u in utilisateurs if u.get("archive")]

    def correspond(u, nom):
        return normaliser(u["prenom"]) == nom or normaliser(f"{u['prenom']} {u['nom']}") == nom

    rapport = {"liees": [], "deja_liees": [], "ambigus": {}, "archives": {}, "sans_correspondance": []}
    with db:
        for p in db.execute("SELECT nom, interfast_user_id FROM personnes").fetchall():
            nom = p["nom"]
            if p["interfast_user_id"]:
                rapport["deja_liees"].append(nom)
                _rafraichir_liaison(db, nom, p["interfast_user_id"])
                continue
            cand = [u for u in actifs if correspond(u, nom)]
            if len(cand) == 1:
                lier(db, nom, cand[0]["id"])
                rapport["liees"].append(nom)
            elif cand:
                rapport["ambigus"][nom] = [f"{u['prenom']} {u['nom']}" for u in cand]
            elif any(correspond(u, nom) for u in archives):
                rapport["archives"][nom] = [f"{u['prenom']} {u['nom']}" for u in archives if correspond(u, nom)]
            else:
                rapport["sans_correspondance"].append(nom)
    return rapport


def _rafraichir_liaison(db, nom, uid):
    u = db.execute("SELECT * FROM utilisateurs_interfast WHERE id=?", (uid,)).fetchone()
    if u:
        db.execute("UPDATE personnes SET nom_complet=?, cout_interfast=? WHERE nom=?",
                   (f"{u['prenom']} {u['nom']}".strip(), u["cout"], nom))


def lier(db, nom: str, uid) -> None:
    """Relie (ou délie, uid None) une personne à un compte InterFast connu."""
    if uid is None:
        db.execute("""UPDATE personnes SET interfast_user_id=NULL, nom_complet='',
                      cout_interfast=NULL WHERE nom=?""", (nom,))
        return
    if not db.execute("SELECT 1 FROM utilisateurs_interfast WHERE id=?", (uid,)).fetchone():
        raise ValueError(f"Compte InterFast {uid} inconnu : relire les utilisateurs d'abord")
    db.execute("UPDATE personnes SET interfast_user_id=? WHERE nom=?", (uid, nom))
    _rafraichir_liaison(db, nom, uid)


def utilisateurs_interfast(db) -> list:
    return [dict(r) for r in db.execute(
        "SELECT * FROM utilisateurs_interfast ORDER BY archive, prenom, nom")]


def affaires_a_chiffrer(db) -> list:
    """Les CH dont le vendu vaut d'être relu : au planning ou pointés."""
    return [r[0] for r in db.execute(
        """SELECT ch FROM planning WHERE ch IS NOT NULL
           UNION SELECT ch FROM pointages WHERE ch IS NOT NULL AND annule=0 ORDER BY 1""")]


def importer_montants(db, montants: list) -> dict:
    now = _iso(maintenant())
    with db:
        for m in montants:
            db.execute("""INSERT INTO affaires(ch, source, maj, vendu_ht, devis_refs, vendu_maj)
                          VALUES (?, 'interfast', ?, ?, ?, ?)
                          ON CONFLICT(ch) DO UPDATE SET vendu_ht=excluded.vendu_ht,
                            devis_refs=excluded.devis_refs, vendu_maj=excluded.vendu_maj""",
                       (m["ch"], now, m["vendu_ht"], ", ".join(m["refs"]), now))
    trouves = [m["ch"] for m in montants if m["vendu_ht"] is not None]
    return {"lus": len(montants), "avec_vendu": len(trouves),
            "sans_devis_signe": [m["ch"] for m in montants if m["vendu_ht"] is None]}


def cout_defaut():
    """Taux moyen de l'environnement (RHI_COUT_HORAIRE), ou None."""
    try:
        v = float(os.getenv("RHI_COUT_HORAIRE", "").replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def couts(db) -> dict:
    """{personne: coût horaire} — saisi au bureau, sinon InterFast (> 0), sinon le taux moyen."""
    defaut = cout_defaut()
    sortie = {}
    for r in db.execute("SELECT nom, cout_horaire, cout_interfast FROM personnes"):
        sortie[r["nom"]] = (r["cout_horaire"] or (r["cout_interfast"] if (r["cout_interfast"] or 0) > 0 else None)
                            or defaut)
    return sortie


NOM_MAX = 40


def ajouter_personne(db, nom: str, equipe: str, quand: dt.datetime) -> dict:
    """Le bureau (les RH) ajoute quelqu'un aux tablettes : un intérimaire.

    Alexis, 30/09/2026 : les intérimaires pointent sous leur propre nom, sur
    les tablettes des permanents, et ce sont les RH qui ajoutent les noms.
    Un nom déjà connu mais désactivé est réactivé plutôt que doublé."""
    nom = " ".join((nom or "").split()).upper()
    if not nom or len(nom) > NOM_MAX:
        raise ValueError(f"Un nom, de {NOM_MAX} caractères au plus")
    if equipe not in ("atelier", "pose"):
        raise ValueError("Équipe : atelier ou pose")
    with db:
        ancien = db.execute("SELECT * FROM personnes WHERE nom=?", (nom,)).fetchone()
        if ancien:
            db.execute("UPDATE personnes SET actif=1, equipe=? WHERE nom=?", (equipe, nom))
        else:
            db.execute("""INSERT INTO personnes(nom, equipe, actif, vu_le, interim)
                          VALUES (?, ?, 1, ?, 1)""", (nom, equipe, _iso(quand)))
    return dict(db.execute("SELECT * FROM personnes WHERE nom=?", (nom,)).fetchone()) | {"deja": bool(ancien)}


def personnes_detail(db) -> list:
    """Toutes les personnes, actives ou non, avec ce que le bureau règle."""
    c = couts(db)
    return [dict(r) | {"cout_retenu": c.get(r["nom"])}
            for r in db.execute("SELECT * FROM personnes ORDER BY equipe, nom")]


# ═══════════════════════ VALIDATION HEBDOMADAIRE ═══════════════════════

def _lundi_de(jour) -> str:
    d = jour if isinstance(jour, dt.date) else dt.date.fromisoformat(str(jour)[:10])
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def validation(db, personne: str, jour):
    r = db.execute("SELECT par, le FROM validations WHERE personne=? AND lundi=?",
                   (personne, _lundi_de(jour))).fetchone()
    return dict(r) if r else None


def valider(db, personne: str, lundi: dt.date, par: str, le: dt.datetime | None = None) -> dict:
    """Le bureau valide le RHI d'une personne pour une semaine.

    Refusé s'il reste un pointage ouvert : on ne valide pas une semaine
    dont une durée n'est pas connue. Une fois validée, la semaine ne se
    corrige plus sans être dévalidée — c'est elle qui partira vers
    InterFast le jour où l'envoi sera branché."""
    fin = (lundi + dt.timedelta(days=7)).isoformat()
    ouverts = db.execute("""SELECT COUNT(*) FROM pointages WHERE personne=? AND annule=0
                            AND fin IS NULL AND debut >= ? AND debut < ?""",
                         (personne, lundi.isoformat(), fin)).fetchone()[0]
    if ouverts:
        raise ValueError(f"{personne} a encore {ouverts} pointage(s) ouvert(s) cette semaine")
    with db:
        db.execute("""INSERT INTO validations VALUES (?,?,?,?)
                      ON CONFLICT(personne, lundi) DO UPDATE SET par=excluded.par, le=excluded.le""",
                   (personne, lundi.isoformat(), par, _iso(le or maintenant())))
    return validation(db, personne, lundi)


class DejaDansInterFast(ValueError):
    """Dévalidation refusée : la semaine a déjà des cases dans InterFast."""


def devalider(db, personne: str, lundi: dt.date) -> None:
    """Rouvre une semaine à la correction — sauf si ses heures sont déjà
    posées dans InterFast : une correction faite ensuite n'y arriverait
    jamais, et les deux outils diraient deux choses sans que personne le
    sache. On corrige alors d'abord la case dans InterFast."""
    refs = refs_semaine(db, personne, lundi)
    if refs:
        raise DejaDansInterFast(f"Semaine de {personne} déjà posée dans InterFast ({', '.join(refs)}) : "
                                "corriger d'abord ces cases dans InterFast")
    with db:
        db.execute("DELETE FROM validations WHERE personne=? AND lundi=?",
                   (personne, lundi.isoformat()))


def _verifier_ouverte(db, personne, *jours):
    for j in jours:
        if j and validation(db, personne, j):
            raise SemaineValidee(f"Semaine du {_lundi_de(j)} validée pour {personne} : "
                                 "la dévalider avant de corriger")


# ═══════════════════════ CE QU'ON PROPOSE SUR LA TABLETTE ═══════════════════════

def personnes(db, equipe=None) -> list:
    sql = "SELECT nom, equipe FROM personnes WHERE actif=1"
    args = ()
    if equipe:
        sql += " AND equipe=?"
        args = (equipe,)
    return [dict(r) for r in db.execute(sql + " ORDER BY nom", args)]


def menu(db, personne: str, jour: dt.date) -> dict:
    """Ce que la personne peut pointer : son planning du jour d'abord.

    La liste complète des affaires suit, parce que le planning a toujours
    un temps de retard (« ça change tous les jours ») : le gars doit pouvoir
    pointer sur une affaire qu'Alexis n'a pas encore reportée."""
    du_jour = [dict(r) for r in db.execute(
        """SELECT p.ch, p.libelle, COALESCE(a.chantier,'') AS chantier
           FROM planning p LEFT JOIN affaires a ON a.ch = p.ch
           WHERE p.personne=? AND p.jour=? ORDER BY p.rowid""",
        (personne, jour.isoformat()))]
    # Sans rien au planning du jour, la semaine sert d'indice.
    if not du_jour:
        lundi = jour - dt.timedelta(days=jour.weekday())
        du_jour = [dict(r) for r in db.execute(
            """SELECT DISTINCT p.ch, p.libelle, COALESCE(a.chantier,'') AS chantier
               FROM planning p LEFT JOIN affaires a ON a.ch = p.ch
               WHERE p.personne=? AND p.jour BETWEEN ? AND ? AND p.ch IS NOT NULL""",
            (personne, lundi.isoformat(), (lundi + dt.timedelta(days=4)).isoformat()))]
    # Un chantier terminé dans InterFast ne se propose plus, sauf s'il est
    # encore au planning du jour (le planning a le dernier mot sur le terrain).
    toutes = [dict(r) for r in db.execute(
        """SELECT ch, chantier, client, titre FROM affaires
           WHERE statut != 'Terminé' ORDER BY chantier, ch""")]
    return {"planning": [p for p in du_jour if p["ch"]],
            "taches_sans_ch": [p["libelle"] for p in du_jour if not p["ch"]],
            "affaires": toutes,
            "ch_divers": ch_divers(),
            "motifs": [{"code": k, "libelle": v} for k, v in MOTIFS.items()]}


def mes_heures(db, personne: str, jour: dt.date, a: dt.datetime) -> dict:
    """Ce que la personne a pointé aujourd'hui et cette semaine, pour la
    tablette. Qui voit ses heures pointe juste, et le signale quand il manque
    une journée — c'est le contrôle le moins cher qui soit."""
    lundi = jour - dt.timedelta(days=jour.weekday())
    r = rhi(db, personne, lundi, a)
    return {"jour": r["par_jour"][jour.weekday()], "semaine": r["total"]}


def ecran(db, jour: dt.date) -> dict:
    """Ce que l'écran de l'atelier affiche : aujourd'hui à l'atelier, la
    semaine de la pose. Lecture seule, tiré du planning importé et des
    pointages en cours."""
    tourne = {p["personne"]: p for p in en_cours(db)}
    atelier = []
    for p in personnes(db, "atelier"):
        prevu = [dict(r) for r in db.execute(
            """SELECT p.ch, p.libelle, COALESCE(a.chantier,'') AS chantier FROM planning p
               LEFT JOIN affaires a ON a.ch = p.ch
               WHERE p.personne=? AND p.jour=? AND p.origine='atelier' ORDER BY p.rowid""",
            (p["nom"], jour.isoformat()))]
        t = tourne.get(p["nom"])
        atelier.append({"nom": p["nom"], "prevu": prevu,
                        "en_cours": {k: t[k] for k in ("ch", "motif", "chantier", "debut")} if t else None})
    lundi = jour - dt.timedelta(days=jour.weekday())
    pose = []
    for i in range(5):
        j = lundi + dt.timedelta(days=i)
        equipes = {}
        for r in db.execute("""SELECT personne, libelle, ch FROM planning
                               WHERE origine='pose' AND jour=? ORDER BY rowid""", (j.isoformat(),)):
            e = equipes.setdefault(r["libelle"], {"libelle": r["libelle"], "ch": [], "personnes": []})
            if r["ch"] and r["ch"] not in e["ch"]:
                e["ch"].append(r["ch"])
            if r["personne"] not in e["personnes"]:
                e["personnes"].append(r["personne"])
        pose.append({"jour": j.isoformat(), "equipes": list(equipes.values())})
    traitement = [dict(r) for r in db.execute(
        """SELECT DISTINCT t.ch, t.debut, t.fin, t.libelle, COALESCE(a.chantier,'') AS chantier FROM traitements t
           LEFT JOIN affaires a ON a.ch = t.ch
           WHERE t.fin >= ? AND t.debut <= ? ORDER BY t.debut""",
        (lundi.isoformat(), (lundi + dt.timedelta(days=6)).isoformat()))]
    return {"jour": jour.isoformat(), "atelier": atelier, "pose": pose, "traitement": traitement}


# ═══════════════════════ POINTAGE ═══════════════════════

def en_cours(db, personne=None) -> list:
    sql = """SELECT p.*, COALESCE(a.chantier,'') AS chantier FROM pointages p
             LEFT JOIN affaires a ON a.ch = p.ch
             WHERE p.fin IS NULL AND p.annule=0"""
    args = ()
    if personne:
        sql += " AND p.personne=?"
        args = (personne,)
    return [dict(r) for r in db.execute(sql + " ORDER BY p.debut", args)]


def arreter(db, noms: list, quand: dt.datetime) -> int:
    """Clôt le pointage ouvert de chaque personne. Rien d'ouvert : rien à faire.

    `quand` peut être dans le passé (geste hors ligne rejoué) : seul un
    pointage commencé AVANT est clos — un pointage démarré depuis, sur un
    autre appareil, n'est pas touché."""
    n = 0
    with db:
        for nom in noms:
            n += db.execute("""UPDATE pointages SET fin=? WHERE personne=? AND fin IS NULL
                               AND annule=0 AND debut <= ?""",
                            (_iso(quand), nom, _iso(quand))).rowcount
    return n


def demarrer(db, noms: list, quand: dt.datetime, ch=None, motif=None,
             libelle="", appareil="", recu: dt.datetime | None = None) -> list:
    """Démarre un pointage pour une ou plusieurs personnes (chef + binôme).

    Arrête d'abord ce qui tournait : on ne fabrique pas deux choses à la
    fois, et c'est l'oubli le plus courant. Un CH inconnu est créé à la
    volée, marqué 'tablette', pour que le bureau le vérifie."""
    if not noms:
        raise ValueError("Personne à pointer")
    if not ch and not motif:
        raise ValueError("Un CH ou un motif")
    if motif:
        motif = _motif(motif)
    # Le geste en direct n'est jamais bloqué, même dans une semaine validée
    # (banc-couts). Mais un geste REJOUÉ (hors ligne, arrivé en retard) ne
    # rouvre pas une semaine que le bureau a déjà relue — revue de sécurité
    # du 29/09/2026 : une tablette oubliée réécrivait un RHI signé.
    if recu and (recu - quand).total_seconds() > DIFFERE_S:
        for nom in noms:
            _verifier_ouverte(db, nom, quand.date())
    arreter(db, noms, quand)
    ids = []
    with db:
        if ch:
            db.execute("""INSERT INTO affaires(ch, chantier, source, maj)
                          VALUES (?, '', 'tablette', ?) ON CONFLICT(ch) DO NOTHING""",
                       (ch, _iso(quand)))
        for nom in noms:
            db.execute("""INSERT INTO personnes(nom, equipe, vu_le) VALUES (?, 'atelier', ?)
                          ON CONFLICT(nom) DO NOTHING""", (nom, _iso(quand)))
            differe = recu and (recu - quand).total_seconds() > DIFFERE_S
            cur = db.execute("""INSERT INTO pointages(personne, ch, motif, libelle, debut, appareil, recu)
                                VALUES (?,?,?,?,?,?,?)""",
                             (nom, ch, None if ch else motif, libelle or "", _iso(quand), appareil,
                              _iso(recu) if differe else None))
            ids.append(cur.lastrowid)
            # Rejoué dans le passé alors qu'un pointage plus récent existe
            # déjà (pointé ailleurs entre-temps) : celui-ci s'arrête là où
            # l'autre commence. Jamais deux choses à la fois.
            suivant = db.execute("""SELECT MIN(debut) FROM pointages WHERE personne=? AND annule=0
                                    AND debut > ? AND id != ?""",
                                 (nom, _iso(quand), cur.lastrowid)).fetchone()[0]
            if suivant:
                db.execute("UPDATE pointages SET fin=? WHERE id=?", (suivant, cur.lastrowid))
    return ids


def corriger(db, pid: int, qui: str, **champs) -> dict:
    """Correction au bureau : CH, motif, début, fin, annulation. Tracée."""
    permis = {"ch", "motif", "libelle", "debut", "fin", "annule"}
    maj = {k: v for k, v in champs.items() if k in permis}
    if not maj:
        raise ValueError("Rien à corriger")
    for k in ("debut", "fin"):
        if maj.get(k):
            maj[k] = _iso(dt.datetime.fromisoformat(maj[k]))
    avant = db.execute("SELECT personne, debut, fin FROM pointages WHERE id=?", (pid,)).fetchone()
    if not avant:
        raise KeyError(pid)
    debut, fin = maj.get("debut") or avant["debut"], maj.get("fin") or avant["fin"]
    if fin and fin <= debut:
        raise ValueError("La fin doit suivre le début")
    _verifier_ouverte(db, avant["personne"], avant["debut"], maj.get("debut"))
    maj["corrige"] = f"{qui} · {_iso(maintenant())}"
    with db:
        n = db.execute(f"UPDATE pointages SET {', '.join(k + '=?' for k in maj)} WHERE id=?",
                       (*maj.values(), pid)).rowcount
    if not n:
        raise KeyError(pid)
    return dict(db.execute("SELECT * FROM pointages WHERE id=?", (pid,)).fetchone())


def ajouter(db, personne, debut, fin, ch=None, motif=None, libelle="", qui="bureau") -> int:
    """Saisie a posteriori au bureau (feuille papier, oubli de la tablette)."""
    if not ch and not motif:
        raise ValueError("Un CH ou un motif")
    if motif:
        motif = _motif(motif)
    # Une durée nulle cachait une journée oubliée sans rien y mettre (un clic
    # sur « Ajouter » sans toucher aux heures), et la validation de masse la
    # laissait alors passer.
    if dt.datetime.fromisoformat(fin) <= dt.datetime.fromisoformat(debut):
        raise ValueError("La fin doit suivre le début")
    _verifier_ouverte(db, personne, debut)
    with db:
        cur = db.execute("""INSERT INTO pointages(personne, ch, motif, libelle, debut, fin,
                            appareil, corrige) VALUES (?,?,?,?,?,?, 'bureau', ?)""",
                         (personne, ch, None if ch else motif, libelle,
                          _iso(dt.datetime.fromisoformat(debut)),
                          _iso(dt.datetime.fromisoformat(fin)),
                          f"{qui} · {_iso(maintenant())}"))
    return cur.lastrowid


# ═══════════════════════ LECTURES : RHI ET POINT D'AFFAIRE ═══════════════════════

def _heures(p: dict, a: dt.datetime) -> float:
    fin = dt.datetime.fromisoformat(p["fin"]) if p["fin"] else a
    return max(0.0, (fin - dt.datetime.fromisoformat(p["debut"])).total_seconds() / 3600)


def _suspendu(p: dict, a: dt.datetime) -> bool:
    """Ouvert depuis trop longtemps : un arrêt oublié, pas du travail.

    Ces heures sortent du point d'affaire (sinon un oubli du vendredi gonfle
    l'affaire de tout le week-end) et y figurent à part, « en suspens »,
    jusqu'à la correction du bureau. Le RHI, lui, les montre et les signale."""
    return p["fin"] is None and _heures(p, a) > DUREE_SUSPECTE_H


def _alertes(p: dict, a: dt.datetime) -> list:
    alertes = []
    h = _heures(p, a)
    if p["fin"] is None and h > DUREE_SUSPECTE_H:
        alertes.append("Toujours ouvert depuis plus de %d h : arrêt oublié ?" % DUREE_SUSPECTE_H)
    elif h > DUREE_SUSPECTE_H:
        alertes.append("Plus de %d h d'affilée" % DUREE_SUSPECTE_H)
    if p["fin"] and p["fin"][:10] != p["debut"][:10]:
        alertes.append("Passe minuit")
    if not p["ch"] and p["motif"] == "AUTRE":
        alertes.append("Motif « autre » à valider")
    if p.get("recu"):
        alertes.append("Pointé hors ligne, reçu le %s à %s" % (p["recu"][8:10] + "/" + p["recu"][5:7],
                                                              p["recu"][11:16]))
    if p.get("source") == "tablette" and p["ch"] != ch_divers():
        alertes.append("CH saisi à la main, absent des plannings")
    if p["ch"] and p["ch"] == ch_divers():
        alertes.append("CH DIVERS : à transférer vers le bon CH dès qu'il est connu")
    return alertes


def rhi(db, personne: str, lundi: dt.date, a: dt.datetime) -> dict:
    """Le Relevé Hebdomadaire Individuel : une ligne par CH, une colonne par jour."""
    fin_sem = lundi + dt.timedelta(days=7)
    lignes = {}
    detail = []
    for r in db.execute(
            """SELECT p.*, COALESCE(a.chantier,'') AS chantier, a.source
               FROM pointages p LEFT JOIN affaires a ON a.ch = p.ch
               WHERE p.personne=? AND p.annule=0 AND p.debut >= ? AND p.debut < ?
               ORDER BY p.debut""",
            (personne, lundi.isoformat(), fin_sem.isoformat())):
        p = dict(r)
        h = _heures(p, a)
        jour = dt.date.fromisoformat(p["debut"][:10]).weekday()
        cle = p["ch"] or ("HORS·" + (p["motif"] or "AUTRE"))
        l = lignes.setdefault(cle, {
            "ch": p["ch"], "motif": p["motif"],
            "libelle": p["chantier"] or LIBELLES_MOTIFS.get(p["motif"] or "", "") or p["libelle"],
            # Où ces heures tombent dans InterFast : le CH des frais généraux
            # pour le hors affaire (vide s'il n'est pas réglé).
            "ch_impute": p["ch"] or ch_frais_generaux() or None,
            "jours": [0.0] * 7, "total": 0.0})
        l["jours"][jour] += h
        l["total"] += h
        p["heures"] = round(h, 2)
        p["alertes"] = _alertes(p, a)
        p["motif_libelle"] = LIBELLES_MOTIFS.get(p["motif"] or "", "")
        detail.append(p)
    rangees = sorted(lignes.values(), key=lambda l: (l["ch"] is None, -l["total"]))
    for l in rangees:
        l["jours"] = [round(x, 2) for x in l["jours"]]
        l["total"] = round(l["total"], 2)
    par_jour = [round(sum(l["jours"][i] for l in rangees), 2) for i in range(7)]
    total = round(sum(par_jour), 2)
    hors = round(sum(l["total"] for l in rangees if not l["ch"]), 2)
    return {"personne": personne, "lundi": lundi.isoformat(), "lignes": rangees,
            "validee": validation(db, personne, lundi),
            "par_jour": par_jour, "total": total, "hors_affaire": hors,
            "pointages": detail,
            "a_verifier": sum(1 for p in detail if p["alertes"])}


def oublis(db, lundi: dt.date, a: dt.datetime) -> list:
    """Les journées au planning où la personne n'a RIEN pointé.

    Le lundi matin, c'est le premier trou à boucher : une journée entière
    absente du RHI ne lève aucune alerte ailleurs (il n'y a pas de pointage
    à signaler). Jours passés seulement — aujourd'hui n'est pas fini. Une
    absence réelle (congé, maladie) apparaît aussi : le bureau la connaît,
    RHI ne la devine pas."""
    fin_sem = min(lundi + dt.timedelta(days=7), a.date())
    sortie = {}
    for r in db.execute(
            """SELECT pl.personne, pl.jour, pl.ch, pl.libelle, pl.origine FROM planning pl
               JOIN personnes pe ON pe.nom = pl.personne AND pe.actif = 1
               WHERE pl.jour >= ? AND pl.jour < ?
               AND NOT EXISTS (SELECT 1 FROM pointages po WHERE po.personne = pl.personne
                               AND po.annule = 0 AND substr(po.debut, 1, 10) = pl.jour)
               ORDER BY pl.jour, pl.personne""", (lundi.isoformat(), fin_sem.isoformat())):
        o = sortie.setdefault((r["jour"], r["personne"]), {
            "personne": r["personne"], "jour": r["jour"], "origine": r["origine"], "prevu": []})
        prevu = {"ch": r["ch"], "libelle": r["libelle"]}
        if prevu not in o["prevu"]:
            o["prevu"].append(prevu)
    return list(sortie.values())


def temps_perdu(db, lundi: dt.date, a: dt.datetime) -> dict:
    """Le temps hors affaire de la semaine, par motif : ce que la réunion
    voulait mesurer (rangement, entretien…), au lieu de le deviner."""
    fin_sem = (lundi + dt.timedelta(days=7)).isoformat()
    par_motif, par_personne, total = {}, {}, 0.0
    for r in db.execute("""SELECT * FROM pointages WHERE annule=0 AND debut >= ? AND debut < ?""",
                        (lundi.isoformat(), fin_sem)):
        p = dict(r)
        if _suspendu(p, a):
            continue
        h = _heures(p, a)
        total += h
        if p["ch"]:
            continue
        m = p["motif"] or "AUTRE"
        par_motif[m] = par_motif.get(m, 0.0) + h
        par_personne.setdefault(p["personne"], {}).setdefault(m, 0.0)
        par_personne[p["personne"]][m] += h
    hors = sum(par_motif.values())
    return {"total": round(total, 2), "hors_affaire": round(hors, 2),
            "part": round(100 * hors / total) if total else 0,
            # Moins d'une minute : un doigt qui a glissé, pas du temps perdu.
            "motifs": [{"code": k, "libelle": LIBELLES_MOTIFS.get(k, k), "heures": round(v, 2),
                        "qui": sorted(((n, round(d[k], 2)) for n, d in par_personne.items()
                                       if d.get(k, 0) >= 1 / 60), key=lambda x: -x[1])}
                       for k, v in sorted(par_motif.items(), key=lambda x: -x[1]) if v >= 1 / 60]}


def valider_tout(db, lundi: dt.date, par: str, a: dt.datetime) -> dict:
    """Valide d'un geste les relevés qui n'ont rien à regarder.

    Mis de côté, avec la raison : une alerte (sauf « pointé hors ligne », qui
    informe sans rien dire de faux), une journée au planning sans pointage,
    un pointage ouvert. Ceux-là, le bureau les regarde un par un — c'est
    tout l'intérêt : le geste de masse ne valide que ce qu'on n'aurait pas
    corrigé."""
    valides, ecartes = [], []
    sans_pointage = {o["personne"] for o in oublis(db, lundi, a)}
    for p in personnes(db):
        r = rhi(db, p["nom"], lundi, a)
        if not r["total"] or r["validee"]:
            continue
        raisons = sorted({x for q in r["pointages"] for x in q["alertes"] if not x.startswith(INFORMATIVES)})
        if p["nom"] in sans_pointage:
            raisons.append("journée au planning sans pointage")
        if not raisons:
            try:
                valider(db, p["nom"], lundi, par, a)
                valides.append(p["nom"])
                continue
            except ValueError as e:
                raisons.append(str(e))
        ecartes.append({"personne": p["nom"], "raisons": raisons})
    return {"valides": valides, "ecartes": ecartes}


def point_affaire(db, ch: str, a: dt.datetime) -> dict:
    """Heures réelles d'une affaire, par personne et par semaine, face au prévu."""
    aff = db.execute("SELECT * FROM affaires WHERE ch=?", (ch,)).fetchone()
    par_personne, par_semaine, total, suspens = {}, {}, 0.0, 0.0
    tarif = couts(db)
    for r in db.execute("SELECT * FROM pointages WHERE ch=? AND annule=0", (ch,)):
        p = dict(r)
        h = _heures(p, a)
        if _suspendu(p, a):
            suspens += h
            continue
        total += h
        par_personne[p["personne"]] = par_personne.get(p["personne"], 0) + h
        d = dt.date.fromisoformat(p["debut"][:10])
        sem = "%d-S%02d" % d.isocalendar()[:2]
        par_semaine[sem] = par_semaine.get(sem, 0) + h
    prevues = aff["heures_prevues"] if aff else None
    return {
        "ch": ch,
        "chantier": aff["chantier"] if aff else "",
        "conduc": aff["conduc"] if aff else "",
        "heures_reelles": round(total, 2),
        "heures_prevues": prevues,
        "heures_en_suspens": round(suspens, 2),
        "consomme_pct": round(100 * total / prevues) if prevues else None,
        "par_personne": {k: round(v, 2) for k, v in sorted(par_personne.items(), key=lambda x: -x[1])},
        "cout_main_oeuvre": round(sum(h * (tarif.get(k) or 0) for k, h in par_personne.items()), 2),
        "vendu_ht": aff["vendu_ht"] if aff else None,
        "devis_refs": aff["devis_refs"] if aff else "",
        "sans_cout": sorted(k for k in par_personne if not tarif.get(k)),
        "par_semaine": {k: round(v, 2) for k, v in sorted(par_semaine.items())},
        "lignes_prevues": [dict(r) for r in db.execute(
            "SELECT designation, heures FROM lignes_prevues WHERE ch=?", (ch,))],
    }


def affaires_pointees(db, a: dt.datetime) -> list:
    """Toutes les affaires, heures réelles et prévues, les plus consommées d'abord."""
    reelles, cout = {}, {}
    tarif = couts(db)
    for r in db.execute("SELECT * FROM pointages WHERE ch IS NOT NULL AND annule=0"):
        p = dict(r)
        if _suspendu(p, a):
            continue
        h = _heures(p, a)
        reelles[p["ch"]] = reelles.get(p["ch"], 0) + h
        cout[p["ch"]] = cout.get(p["ch"], 0) + h * (tarif.get(p["personne"]) or 0)
    sortie = []
    for r in db.execute("SELECT * FROM affaires"):
        h = reelles.get(r["ch"], 0.0)
        if not h and not r["heures_prevues"]:
            continue
        sortie.append({"ch": r["ch"], "chantier": r["chantier"], "conduc": r["conduc"],
                       "source": r["source"], "heures_reelles": round(h, 2),
                       "client": r["client"], "cout_main_oeuvre": round(cout.get(r["ch"], 0), 2),
                       "vendu_ht": r["vendu_ht"],
                       "part_mo_pct": (round(100 * cout.get(r["ch"], 0) / r["vendu_ht"], 1)
                                       if r["vendu_ht"] and cout.get(r["ch"]) else None),
                       "heures_prevues": r["heures_prevues"],
                       "consomme_pct": round(100 * h / r["heures_prevues"]) if r["heures_prevues"] else None})
    return sorted(sortie, key=lambda x: -(x["consomme_pct"] or 0) if x["heures_prevues"] else -x["heures_reelles"])


# ═══════════════════════ MARCHE EN AVANT ═══════════════════════
#
# L'analyse du lundi d'Alexis (études → fabrication → pose), jusqu'ici faite
# à la main par un agent Claude sur les Excel. Reprise en code pour une
# raison écrite dans sa synthèse du 28/09/2026 : elle y comptait comme
# « réalisées » des fabrications datées du 06/10 et du 12/10 — et sortait
# deux affaires du suivi prioritaire sur cette erreur. Ici, une fabrication
# n'est RÉALISÉE que si elle est datée d'avant le jour de l'analyse.

MOTS_BLOQUANTS = ("ATTENTE", "MANQUE", "BLOQU", "EN COURS DE VALIDATION")
DELAI_ETUDES_J = 21          # « Délais minimum 3 semaines » (planning BET)
ECART_STOCK_J = 120          # fab plus de 4 mois avant la pose : à confirmer
URGENT_J = 7

NIVEAUX = {"rouge": 0, "orange": 1, "gris": 2, "vert": 3}


AVANCE_MAX_J = 56   # le plan de charge ne planifie pas au-delà de ~8 semaines


def semaine_proche(semaine: int, jour: dt.date) -> tuple:
    """(lundi, dimanche) de la semaine ISO `semaine` telle que le plan de
    charge l'entend — il écrit « S36 » sans l'année, à cheval sur deux ans.

    Pas « la plus proche » : S11 lue le 28/09/2026 tombait en mars 2027 (plus
    proche que mars 2026) et passait pour une fab future. Les semaines du plan
    de charge sont passées ou proches : on prend l'année la plus récente dont
    la semaine ne tombe pas à plus de 8 semaines devant."""
    candidats = []
    for annee in (jour.year - 1, jour.year, jour.year + 1):
        try:
            lundi = dt.date.fromisocalendar(annee, semaine, 1)
        except ValueError:
            continue
        if (lundi - jour).days <= AVANCE_MAX_J:
            candidats.append(lundi)
    lundi = max(candidats)
    return lundi, lundi + dt.timedelta(days=6)


# Les mots qui disent QUOI (une porte, une grille, un garde-corps) — pas
# les mots de geste ou de remplissage.
MOTS_VIDES = {"POSE", "REPRISE", "FINALISATION", "FINITION", "MODIF", "MODIFICATION", "DEPOSE",
              "PROVISOIRE", "CHANTIER", "TRAVAUX", "AVEC", "POUR", "SUITE", "DIVERS", "FAB",
              "FABRICATION", "ETUDE", "VISA", "EXE", "REPOSE", "REFABRICATION", "MONTAGE", "SUR",
              "DES", "LES", "UNE", "ALFA", "SGM"}
MOTS_COURTS = {"GC", "MC", "BSO", "TS", "OM", "VS", "PMR"}


def mots(texte) -> set:
    """« PORTES (X5) / GRILLES ACCOUSTIQUE (x2) » → {PORTE, GRILLE, ACCOUSTIQUE}."""
    sortie = set()
    for m in normaliser(texte).split():
        if m in MOTS_COURTS:
            sortie.add(m)
        elif len(m) >= 4 and not m.isdigit() and m not in MOTS_VIDES and not re.fullmatch(r"X\d+", m):
            sortie.add(m[:-1] if len(m) > 4 and m[-1] in "SX" else m)
    return sortie


def meme_chantier(a, b) -> bool:
    a, b = normaliser(a), normaliser(b)
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)))


def _constat(niveau, cle, texte):
    return {"niveau": niveau, "cle": cle, "texte": texte}


def analyser_ch(db, ch: str, pose: dt.date, jour: dt.date, libelle: str = "") -> list:
    """Les constats d'un CH pour une pose donnée.

    Une affaire a plusieurs pièces (des portes, une pergola…) : la pose d'une
    pièce se juge sur l'amont de CETTE pièce. On rapproche par les mots du
    libellé (PORTE, GRILLE, GC…) ; s'ils ne rapprochent rien alors que
    l'affaire a de l'amont, c'est la pièce qui n'a pas de trace — le cas
    « Assas, portes (X5) » de la synthèse d'Alexis. Les lignes du plan de
    charge sans CH sont rapprochées par le nom du chantier."""
    morceaux = [m for m in libelle.split(" / ") if m]
    chantier, cherches = (morceaux[0] if morceaux else ""), mots(" ".join(morceaux[1:]))
    fab_lignes = [(dt.date.fromisoformat(r["jour"]), r["libelle"]) for r in db.execute(
        "SELECT DISTINCT jour, libelle FROM planning WHERE origine='atelier' AND ch=?", (ch,))]
    # Le CH n'est saisi au planning FAB que depuis peu : une fab plus ancienne
    # n'a que son libellé (« MAISON MED ASSAS / PERGOLA ALU »). Rapprochée par
    # le nom du chantier ET les mots de la pièce, jamais par le nom seul.
    fab_par_nom = [(dt.date.fromisoformat(r["jour"]), r["libelle"]) for r in db.execute(
        "SELECT DISTINCT jour, libelle FROM planning WHERE origine='atelier' AND ch IS NULL")
        if meme_chantier(r["libelle"].split(" / ")[0], chantier)
        and (mots(" ".join(r["libelle"].split(" / ")[1:])) & cherches)]
    fab_lignes += fab_par_nom
    backlog = [dict(r) for r in db.execute("SELECT * FROM lignes_prevues WHERE ch=?", (ch,))]
    par_nom = [dict(r) | {"par_nom": True} for r in db.execute("SELECT * FROM lignes_prevues WHERE ch=''")
               if meme_chantier(r["chantier"], chantier)]
    etudes = [dict(r) for r in db.execute("SELECT * FROM etudes_bet WHERE ch=?", (ch,))]
    j = (pose - jour).days
    sortie = []
    if not fab_lignes and not backlog and not etudes and not par_nom:
        return [_constat("rouge" if j <= URGENT_J else "orange", f"{ch}|aucune-trace",
                         "Aucune trace amont : ni plan de charge, ni planning FAB, ni BET "
                         "(approvisionnement extérieur ? à vérifier)")]
    if cherches:
        f2 = [x for x in fab_lignes if mots(x[1]) & cherches]
        b2 = [l for l in backlog + par_nom if mots(l["designation"]) & cherches]
        e2 = [e for e in etudes if mots(e["intitule"]) & cherches]
        if not (f2 or b2 or e2):
            return [_constat("rouge" if j <= URGENT_J else "orange", f"{ch}|piece|{libelle[:60]}",
                             "L'affaire a de l'amont, mais rien au plan de charge, au planning FAB ni au BET "
                             f"ne ressemble à « {' / '.join(morceaux[1:])} » (approvisionnement extérieur ?)")]
        fab_lignes, backlog, etudes = f2, b2, e2
    else:
        backlog = backlog + par_nom
    fab = sorted({d for d, _ in fab_lignes})
    faites = [d for d in fab if d < jour]
    prevues = [d for d in fab if d >= jour]
    if any(l.get("par_nom") for l in backlog):
        sortie.append(_constat("vert", f"{ch}|par-nom", "Plan de charge rapproché par le nom du chantier (ligne sans CH)"))
    if fab_par_nom and set(fab_par_nom) & set(fab_lignes):
        sortie.append(_constat("vert", f"{ch}|fab-par-nom",
                               "Planning FAB rapproché par le nom du chantier et de la pièce (cases sans CH)"))
    if prevues and prevues[-1] >= pose:
        sortie.append(_constat("rouge", f"{ch}|fab-apres-pose",
                               f"Fabrication prévue jusqu'au {prevues[-1]:%d/%m}, pour une pose le {pose:%d/%m}"))
    elif prevues and not faites and (pose - prevues[-1]).days < 2:
        sortie.append(_constat("orange", f"{ch}|fab-juste-avant",
                               f"Fabrication finie le {prevues[-1]:%d/%m} seulement, pose le {pose:%d/%m}"))
    if not fab and backlog:
        semaines = sorted({int(x) for l in backlog for x in (l["semaines"] or "").split(",") if x})
        if not semaines:
            sortie.append(_constat("orange", f"{ch}|sans-semaine",
                                   "Au plan de charge, mais sans semaine de fab ni trace au planning FAB"))
        else:
            fin_s = semaine_proche(semaines[-1], jour)[1]
            if fin_s < jour:
                sortie.append(_constat("orange", f"{ch}|backlog-passe",
                                       f"Plan de charge : fab en S{semaines[-1]:02d} (passée), "
                                       "mais aucune trace au planning FAB"))
            elif fin_s >= pose:
                sortie.append(_constat("rouge", f"{ch}|backlog-apres-pose",
                                       f"Plan de charge : fab en S{semaines[-1]:02d}, pour une pose le {pose:%d/%m}"))
    for e in etudes:
        if e["statut"] in ("termine", "annule"):
            continue
        fin_e = dt.date.fromisoformat(e["fin"]) if e["fin"] else None
        if fin_e is None or (pose - fin_e).days < DELAI_ETUDES_J:
            quand = f"prévue le {fin_e:%d/%m}" if fin_e else "sans date"
            sortie.append(_constat("rouge" if j <= 2 * URGENT_J else "orange", f"{ch}|etude|{e['intitule'][:40]}",
                                   f"Étude « {e['intitule']} » {e['statut'] or 'non close'} ({quand}) : "
                                   f"moins de 3 semaines avant la pose"
                                   + (f" — {e['commentaire']}" if e["commentaire"] else "")))
    # Le traitement de surface, entre la fab et la pose (affaire entière : le
    # planning TRAITEMENT ne nomme pas la pièce).
    # Seul un envoi DÉJÀ PARTI le jour de la pose est un risque : un envoi qui
    # part le jour même ou après concerne les pièces suivantes (Rapoport, envoi
    # du 12 au 19/10 pour une pose le 09/10). Le même envoi écrit dans deux
    # cases ne compte qu'une fois.
    for r in db.execute("""SELECT DISTINCT debut, fin FROM traitements WHERE ch=? AND debut < ? AND fin >= ?
                           ORDER BY fin""", (ch, pose.isoformat(), pose.isoformat())):
        fin_t = dt.date.fromisoformat(r["fin"])
        if fin_t >= pose:
            # Orange, jamais rouge : le planning TRAITEMENT nomme le chantier,
            # pas la pièce — l'envoi peut concerner une autre pièce de l'affaire.
            sortie.append(_constat("orange", f"{ch}|traitement|{r['debut']}",
                                   f"Un envoi en traitement de surface de l'affaire court jusqu'au {fin_t:%d/%m}, "
                                   f"pose le {pose:%d/%m} — même pièce ? (le planning TRAITEMENT ne le dit pas)"))
    for l in backlog:
        com = (l["commentaire"] or "").upper()
        if any(m in com for m in MOTS_BLOQUANTS):
            if faites:
                sortie.append(_constat("gris", f"{ch}|commentaire-fige|{l['designation'][:40]}",
                                       f"Commentaire « {l['commentaire']} » toujours au plan de charge, "
                                       f"alors que la fab a eu lieu (dernière le {faites[-1]:%d/%m}) : à nettoyer"))
            else:
                sortie.append(_constat("orange", f"{ch}|commentaire|{l['designation'][:40]}",
                                       f"« {l['designation']} » : {l['commentaire']}"))
    for e in etudes:
        com = (e["commentaire"] or "").upper()
        if e["statut"] == "termine" and any(m in com for m in MOTS_BLOQUANTS):
            sortie.append(_constat("gris", f"{ch}|bet-fige|{e['intitule'][:40]}",
                                   f"BET : étude « {e['intitule']} » terminée, mais toujours « {e['commentaire']} »"
                                   " : à confirmer ou nettoyer"))
    if faites and (pose - faites[-1]).days > ECART_STOCK_J:
        sortie.append(_constat("gris", f"{ch}|ecart",
                               f"Fabriqué le {faites[-1]:%d/%m/%Y}, posé le {pose:%d/%m} : plus de 4 mois d'écart "
                               "(stock en attente de site ?) — à confirmer"))
    if all(c["niveau"] == "vert" for c in sortie):
        detail = (f"fab faite (dernière le {faites[-1]:%d/%m})" if faites else
                  f"fab prévue jusqu'au {prevues[-1]:%d/%m}" if prevues else "au plan de charge")
        sortie.append(_constat("vert", f"{ch}|ok", f"Cohérent : {detail}"))
    return sortie


def marche(db, jour: dt.date, semaines: int = 4, enregistrer: bool = True) -> dict:
    """Toutes les poses des `semaines` à venir, chacune avec ses constats,
    et pour chaque constat le nombre d'analyses consécutives où il revient."""
    fin = jour + dt.timedelta(weeks=semaines)
    poses = {}
    for r in db.execute("""SELECT jour, libelle, ch, personne FROM planning WHERE origine='pose'
                           AND jour >= ? AND jour < ? ORDER BY jour""", (jour.isoformat(), fin.isoformat())):
        cle = (r["libelle"], r["ch"])
        p = poses.setdefault(cle, {"libelle": r["libelle"], "ch": r["ch"], "jours": [], "personnes": []})
        if r["jour"] not in p["jours"]:
            p["jours"].append(r["jour"])
        if r["personne"] not in p["personnes"]:
            p["personnes"].append(r["personne"])
    lignes = []
    for p in poses.values():
        premiere = dt.date.fromisoformat(p["jours"][0])
        if p["ch"]:
            constats = analyser_ch(db, p["ch"], premiere, jour, p["libelle"])
        else:
            constats = [_constat("orange" if (premiere - jour).days > URGENT_J else "rouge",
                                 f"sans-ch|{p['libelle'][:60]}",
                                 "Pose sans N° d'affaire : rapprochement impossible avec l'amont")]
        niveau = min((c["niveau"] for c in constats), key=NIVEAUX.get)
        lignes.append({**p, "pose": premiere.isoformat(), "dans_j": (premiere - jour).days,
                       "niveau": niveau, "constats": constats})
    lignes.sort(key=lambda x: (NIVEAUX[x["niveau"]], x["pose"]))
    if enregistrer:
        with db:
            db.execute("DELETE FROM constats WHERE jour=?", (jour.isoformat(),))
            for l in lignes:
                for c in l["constats"]:
                    if c["niveau"] != "vert":
                        db.execute("INSERT OR IGNORE INTO constats VALUES (?,?,?,?)",
                                   (jour.isoformat(), c["cle"], c["niveau"], c["texte"]))
    anterieures = [r[0] for r in db.execute(
        "SELECT DISTINCT jour FROM constats WHERE jour < ? ORDER BY jour DESC", (jour.isoformat(),))]
    for l in lignes:
        for c in l["constats"]:
            n = 1
            for j_ant in anterieures:
                if db.execute("SELECT 1 FROM constats WHERE jour=? AND cle=?", (j_ant, c["cle"])).fetchone():
                    n += 1
                else:
                    break
            c["consecutifs"] = n if c["niveau"] != "vert" else 0
    bet_a_jour = db.execute("SELECT MAX(fin) FROM etudes_bet").fetchone()[0]
    return {"jour": jour.isoformat(), "jusqu_au": fin.isoformat(), "lignes": lignes,
            "compte": {n: sum(1 for l in lignes if l["niveau"] == n) for n in NIVEAUX},
            "bet_charge": db.execute("SELECT COUNT(*) FROM etudes_bet").fetchone()[0] > 0,
            "bet_a_jour_au": bet_a_jour}


def synthese_md(m: dict) -> str:
    """La marche en avant en Markdown, dans la forme des synthèses d'Alexis
    (« Risques prioritaires / À surveiller / Cohérent / BET ») : le « point
    MD » qu'il demandait à son agent pour l'envoyer."""
    def jj(iso):
        return f"{iso[8:10]}/{iso[5:7]}"
    titres = {"rouge": "Risques prioritaires", "orange": "À surveiller",
              "gris": "À confirmer ou nettoyer", "vert": "Cohérent, rien à signaler"}
    out = [f"# Marche en avant — semaine du {jj(m['jour'])}",
           "",
           f"Poses du {jj(m['jour'])} au {jj(m['jusqu_au'])}, face au plan de charge, au planning FAB, "
           "au planning TRAITEMENT et au BET. Une fabrication n'est comptée faite que si elle est datée "
           "d'avant le jour de l'analyse.",
           "",
           "**Bilan** : " + " · ".join(f"{m['compte'][n]} {titres[n].split(',')[0].lower()}"
                                        for n in ("rouge", "orange", "gris", "vert")),
           ""]
    for n in ("rouge", "orange", "gris"):
        lignes = [l for l in m["lignes"] if l["niveau"] == n]
        if not lignes:
            continue
        out += [f"## {titres[n]}", ""]
        for l in lignes:
            out.append(f"- **{l['libelle']}** ({l['ch'] or 'sans CH'}) — pose le {jj(l['pose'])} "
                       f"(J{'+' if l['dans_j'] >= 0 else ''}{l['dans_j']}), {', '.join(l['personnes'])}")
            for c in l["constats"]:
                if c["niveau"] == "vert":
                    continue
                suite = f" *({c['consecutifs']}ᵉ analyse d'affilée)*" if c.get("consecutifs", 0) > 1 else ""
                out.append(f"  - {c['texte']}{suite}")
        out.append("")
    verts = [l for l in m["lignes"] if l["niveau"] == "vert"]
    if verts:
        out += [f"## {titres['vert']}", "",
                ", ".join(f"{l['libelle']} ({jj(l['pose'])})" for l in verts), ""]
    out += ["## BET", "",
            (f"Chargé, planifié jusqu'au {jj(m['bet_a_jour_au'])}." if m["bet_charge"] and m["bet_a_jour_au"]
             else "Non chargé : pas d'alerte « études » possible cette semaine."), ""]
    return "\n".join(out)


# ═══════════════════════ VERS INTERFAST (à blanc) ═══════════════════════

LONG_H = 12


def _hm(t: dt.datetime) -> str:
    return t.strftime("%H:%M")


def duree_texte(heures: float) -> str:
    """4.5 → « 4h30 » : la forme que planifier_intervention comprend."""
    m = int(round(heures * 60))
    return f"{m // 60}h{m % 60:02d}" if m % 60 else f"{m // 60}h"


def envois(db, lundi: dt.date, a: dt.datetime) -> dict:
    """Ce que RHI poserait dans le planning InterFast pour une semaine.

    Le chemin décidé le 29/09/2026 (docs/interfast.md) : des CASES dans le
    planning, que l'on termine puis valide dans InterFast. Une case par CH
    et par jour, avec toute l'équipe dessus, plutôt qu'une par personne :
    autant de cases de moins à terminer et à valider, et le rapport
    d'intervention garde de toute façon les heures de chaque technicien.

    Pour chaque technicien, la case dit ce qu'il faudra saisir en la
    terminant (« Date et heures pour … ») : début, fin, et la pause — qui
    comprend le temps passé sur un autre CH entre les deux.

    Une case n'est « prête » que si TOUS ceux qui ont pointé ce CH ce jour-là
    ont leur RHI validé : une case partie incomplète se rattrape à la main.
    Elle est « bloquée » si InterFast ne pourrait pas la recevoir : CH
    inconnu d'InterFast, chantier sans client, aucun technicien relié à un
    compte InterFast. Un technicien sans compte n'empêche pas la case : il
    est nommé, pour être ajouté à la main."""
    fin_sem = lundi + dt.timedelta(days=7)
    valides = {r["personne"] for r in db.execute(
        "SELECT personne FROM validations WHERE lundi=?", (lundi.isoformat(),))}
    gens = {r["nom"]: dict(r) for r in db.execute("SELECT * FROM personnes")}
    affaires = {r["ch"]: dict(r) for r in db.execute("SELECT * FROM affaires")}
    posees = {(r["ch"], r["jour"]): dict(r) for r in db.execute(
        "SELECT * FROM cases_interfast WHERE jour >= ? AND jour < ?", (lundi.isoformat(), fin_sem.isoformat()))}
    recues = {(r["ref"], r["user_id"]): dict(r) for r in db.execute("SELECT * FROM heures_interfast")}
    cases = {}
    # Le hors affaire part sur le CH des frais généraux (Alexis, 30/09/2026) ;
    # sans ce CH réglé, il reste en dehors d'InterFast.
    fg = ch_frais_generaux()
    for r in db.execute("""SELECT * FROM pointages WHERE annule=0 AND (ch IS NOT NULL OR ? != '')
                           AND fin IS NOT NULL AND debut >= ? AND debut < ? ORDER BY debut""",
                        (fg, lundi.isoformat(), fin_sem.isoformat())):
        p = dict(r)
        if not p["ch"]:
            p["ch"] = fg
            p["libelle"] = p["libelle"] or LIBELLES_MOTIFS.get(p["motif"] or "", "hors affaire")
        jour = p["debut"][:10]
        c = cases.setdefault((p["ch"], jour), {"ch": p["ch"], "jour": jour, "gens": {}, "libelles": []})
        g = c["gens"].setdefault(p["personne"], {"personne": p["personne"], "debut": None, "fin": None,
                                                 "heures": 0.0, "ids": [], "envoye": True, "douteux": False})
        d, f = dt.datetime.fromisoformat(p["debut"]), dt.datetime.fromisoformat(p["fin"])
        # Un pointage à cheval sur deux jours ou de plus de 12 h est un arrêt
        # oublié ou mal rattrapé : il ne part pas tel quel dans une case.
        g["douteux"] = g["douteux"] or f.date() != d.date() or f - d > dt.timedelta(hours=LONG_H)
        g["debut"] = min(g["debut"] or d, d)
        g["fin"] = max(g["fin"] or f, f)
        g["heures"] += _heures(p, a)
        g["ids"].append(p["id"])
        g["envoye"] = g["envoye"] and bool(p["interfast"])
        if p["libelle"] and p["libelle"] not in c["libelles"]:
            c["libelles"].append(p["libelle"])
    sortie = []
    for (ch, jour), c in cases.items():
        aff = affaires.get(ch, {})
        equipe = []
        for g in sorted(c["gens"].values(), key=lambda x: x["debut"]):
            fiche = gens.get(g["personne"], {})
            amplitude = (g["fin"] - g["debut"]).total_seconds() / 3600
            equipe.append({
                "personne": g["personne"], "technicien": fiche.get("nom_complet") or g["personne"],
                "compte": bool(fiche.get("interfast_user_id")), "valide": g["personne"] in valides,
                "debut": _hm(g["debut"]), "fin": _hm(g["fin"]), "heures": round(g["heures"], 2),
                "pause": duree_texte(max(0.0, amplitude - g["heures"])) if amplitude - g["heures"] >= 1 / 60 else "",
                "envoye": g["envoye"], "ids": g["ids"], "douteux": g["douteux"]})
        debut = min(dt.datetime.fromisoformat(f"{jour}T{e['debut']}") for e in equipe)
        fin = max(dt.datetime.fromisoformat(f"{jour}T{e['fin']}") for e in equipe)
        blocages = []
        if not aff.get("interfast_id"):
            blocages.append("CH inconnu d'InterFast")
        elif not aff.get("client"):
            blocages.append("chantier sans client")
        if not any(e["compte"] for e in equipe):
            blocages.append("aucun technicien relié à InterFast")
        douteux = [e["personne"] for e in equipe if e["douteux"]]
        if douteux:
            blocages.append(f"pointage de plus de {LONG_H} h ou sur deux jours ({', '.join(douteux)}) : à corriger")
        attente = [e["personne"] for e in equipe if not e["valide"]]
        pose = posees.get((ch, jour))
        # Ce qu'InterFast a reçu en clôture, face au RHI : un écart de plus
        # d'un quart d'heure est une saisie à reprendre dans InterFast.
        for e in equipe:
            uid = gens.get(e["personne"], {}).get("interfast_user_id")
            recu = recues.get((pose["ref"], uid)) if pose and uid else None
            e["interfast"] = round(recu["minutes"] / 60, 2) if recu else None
            e["ecart"] = bool(pose and pose["terminee"] and e["valide"] and e["compte"] and (
                recu is None or abs(recu["minutes"] - e["heures"] * 60) > ECART_MIN))
        a_ajouter = [e["technicien"] for e in equipe if e["valide"] and not e["envoye"]] if pose else []
        if pose:
            etat = ("à vérifier" if pose["ref"] == A_VERIFIER else "à compléter" if a_ajouter
                    else "terminée" if pose["terminee"] else "posée")
            if etat == "terminée" and any(e["ecart"] for e in equipe):
                etat = "écart"
        elif attente:
            etat = "en attente"
        else:
            etat = "bloquée" if blocages else "prête"
        sortie.append({
            "id": f"{ch}|{jour}", "ch": ch, "jour": jour, "heure": _hm(debut), "fin": _hm(fin),
            "duree": duree_texte((fin - debut).total_seconds() / 3600),
            "heures": round(sum(e["heures"] for e in equipe), 2),
            "equipe": equipe, "techniciens": [e["technicien"] for e in equipe if e["compte"]],
            "sans_compte": [e["technicien"] for e in equipe if not e["compte"]],
            "en_attente": attente, "a_ajouter": a_ajouter,
            "client": aff.get("client", ""), "chantier": aff.get("titre") or aff.get("chantier", ""),
            "description": f"RHI · {ch} · " + (" / ".join(c["libelles"]) or "pointage"),
            "ref": pose["ref"] if pose else "", "etat": etat, "blocages": blocages})
    sortie.sort(key=lambda x: (x["jour"], x["heure"], x["ch"]))
    compte = lambda e: sum(1 for x in sortie if x["etat"] == e)  # noqa: E731
    return {"lundi": lundi.isoformat(), "cases": sortie, "personnes_validees": sorted(valides),
            "pretes": compte("prête"), "bloquees": compte("bloquée"), "en_attente": compte("en attente"),
            "posees": compte("posée") + compte("à compléter") + compte("à vérifier"),
            "terminees": compte("terminée"),
            "ecarts": compte("écart"),
            "heures_pretes": round(sum(x["heures"] for x in sortie if x["etat"] == "prête"), 2)}


def case_posee(db, case: dict, ref: str) -> None:
    """InterFast a créé la case : on garde sa référence, sur la case et sur
    chaque pointage qu'elle porte — c'est ce qui interdit de l'envoyer deux
    fois et de dévalider la semaine en silence."""
    ids = [i for e in case["equipe"] if e["valide"] for i in e["ids"]]
    with db:
        db.execute("""INSERT INTO cases_interfast(ch, jour, ref, posee_le) VALUES (?,?,?,?)
                      ON CONFLICT(ch, jour) DO UPDATE SET ref=excluded.ref, posee_le=excluded.posee_le""",
                   (case["ch"], case["jour"], ref, _iso(maintenant())))
        db.executemany("UPDATE pointages SET interfast=? WHERE id=?", [(ref, i) for i in ids])


ECART_MIN = 15


A_VERIFIER = "À VÉRIFIER"


def _case(db, ch: str, jour: str):
    r = db.execute("SELECT * FROM cases_interfast WHERE ch=? AND jour=?", (ch, jour)).fetchone()
    if not r:
        raise KeyError(f"{ch} le {jour} : aucune case posée")
    return dict(r)


def completer_case(db, ch: str, jour: str) -> int:
    """Les validés arrivés après la pose ont été ajoutés à la main dans la
    case InterFast : leurs pointages prennent la référence de la case.
    Sans ce geste, la case restait « à compléter » pour toujours et leur
    semaine se dévalidait en silence."""
    case = _case(db, ch, jour)
    lundi = _lundi_de(jour)
    with db:
        return db.execute(
            """UPDATE pointages SET interfast=? WHERE ch=? AND substr(debut, 1, 10)=? AND annule=0
               AND fin IS NOT NULL AND interfast IS NULL
               AND personne IN (SELECT personne FROM validations WHERE lundi=?)""",
            (case["ref"], ch, jour, lundi)).rowcount


def reference_case(db, ch: str, jour: str, ref: str) -> dict:
    """Une case « À VÉRIFIER » tranchée par le bureau, après un œil dans
    InterFast : elle y est (on garde sa vraie référence IN…), ou elle n'y
    est pas (on l'efface de RHI, et elle redevient prête à partir).
    Seule une case À VÉRIFIER se tranche : une vraie référence ne se
    réécrit pas."""
    case = _case(db, ch, jour)
    if case["ref"] != A_VERIFIER:
        raise ValueError(f"La case {ch} du {jour} a déjà sa référence ({case['ref']})")
    ref = ref.strip().upper()
    if ref and not re.fullmatch(r"IN\d{4,6}", ref):
        raise ValueError("Une référence InterFast : IN suivi de chiffres (ex. IN00123)")
    with db:
        if ref:
            db.execute("UPDATE cases_interfast SET ref=? WHERE ch=? AND jour=?", (ref, ch, jour))
        else:
            db.execute("DELETE FROM cases_interfast WHERE ch=? AND jour=?", (ch, jour))
        db.execute("""UPDATE pointages SET interfast=? WHERE interfast=? AND ch=?
                      AND substr(debut, 1, 10)=?""", (ref or None, A_VERIFIER, ch, jour))
    return {"ch": ch, "jour": jour, "ref": ref or None}


def cases_posees(db, lundi: dt.date) -> list:
    """Les cases posées d'une semaine, avec les comptes InterFast de ceux
    qu'elles portent — de quoi aller relire leurs heures."""
    fin_sem = (lundi + dt.timedelta(days=7)).isoformat()
    sortie = []
    for r in db.execute("""SELECT * FROM cases_interfast WHERE jour >= ? AND jour < ?
                           AND ref LIKE 'IN%' ORDER BY jour, ch""", (lundi.isoformat(), fin_sem)):
        users = [u[0] for u in db.execute(
            """SELECT DISTINCT pe.interfast_user_id FROM pointages po JOIN personnes pe ON pe.nom = po.personne
               WHERE po.interfast=? AND pe.interfast_user_id IS NOT NULL""", (r["ref"],))]
        sortie.append({"ref": r["ref"], "num": r["num"], "ch": r["ch"],
                       "jour": dt.date.fromisoformat(r["jour"]), "users": users})
    return sortie


def _paris(iso_utc: str) -> str:
    t = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return _iso(t.astimezone(PARIS).replace(tzinfo=None))


def enregistrer_suivi(db, ref: str, num, entrees: list) -> None:
    """Ce qu'InterFast a reçu à la clôture de la case. Aucune entrée : la
    case n'est pas encore terminée."""
    par_user = {}
    for e in entrees:
        u = par_user.setdefault(e["user"], {"debut": _paris(e["debut"]), "fin": _paris(e["fin"]),
                                            "minutes": 0, "pause": 0})
        u["debut"], u["fin"] = min(u["debut"], _paris(e["debut"])), max(u["fin"], _paris(e["fin"]))
        u["minutes"] += e["minutes"]
        u["pause"] += e["pause"]
    with db:
        db.execute("UPDATE cases_interfast SET num=COALESCE(?, num), terminee=?, relue_le=? WHERE ref=?",
                   (num, 1 if par_user else 0, _iso(maintenant()), ref))
        db.execute("DELETE FROM heures_interfast WHERE ref=?", (ref,))
        db.executemany("INSERT INTO heures_interfast VALUES (?,?,?,?,?,?)",
                       [(ref, uid, u["debut"], u["fin"], u["minutes"], u["pause"]) for uid, u in par_user.items()])


def refs_semaine(db, personne: str, lundi: dt.date) -> list:
    fin_sem = (lundi + dt.timedelta(days=7)).isoformat()
    return sorted({r[0] for r in db.execute(
        """SELECT interfast FROM pointages WHERE personne=? AND interfast IS NOT NULL
           AND debut >= ? AND debut < ?""", (personne, lundi.isoformat(), fin_sem))})


# ═══════════════════════ SAUVEGARDE ═══════════════════════

GARDER_JOURS = 30


_VERROU_SAUVEGARDE = threading.Lock()


def sauvegarder(db, dossier: Path, jour: dt.date) -> Path | None:
    """Une à la fois : le veilleur la lance dans un fil au démarrage, et un
    second appel au même instant écrivait le même fichier provisoire que le
    premier (vu le 29/09/2026 : banc-sauvegarde rouge une fois sur
    plusieurs). Le second attend, puis trouve la copie faite."""
    with _VERROU_SAUVEGARDE:
        return _sauvegarder(db, dossier, jour)


def _sauvegarder(db, dossier: Path, jour: dt.date) -> Path | None:
    """Une copie cohérente de la base par jour, gardée 30 jours.

    L'API de sauvegarde de SQLite copie une base en cours d'écriture sans la
    bloquer ni la corrompre (un simple cp pendant une écriture le pourrait).
    Rien si la copie du jour existe déjà. Sur Clever Cloud, le dossier est
    sur le bucket : cela protège d'une erreur (import raté, correction de
    masse), pas de la perte du bucket — d'où aussi le téléchargement au
    bureau (docs/deploiement.md)."""
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / f"rhi-{jour.isoformat()}.db"
    if cible.exists():
        return None
    provisoire = cible.with_suffix(".tmp")
    copie = sqlite3.connect(provisoire)
    try:
        db.backup(copie)
    finally:
        copie.close()
    provisoire.rename(cible)
    limite = jour - dt.timedelta(days=GARDER_JOURS)
    for vieux in dossier.glob("rhi-*.db"):
        try:
            if dt.date.fromisoformat(vieux.stem[4:]) < limite:
                vieux.unlink()
        except ValueError:
            pass
    return cible


def copie_complete(db) -> bytes:
    """La base entière, cohérente, pour un téléchargement au bureau."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "rhi.db"
        copie = sqlite3.connect(f)
        try:
            db.backup(copie)
        finally:
            copie.close()
        return f.read_bytes()
