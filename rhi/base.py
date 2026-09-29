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
from pathlib import Path
from zoneinfo import ZoneInfo

from .textes import normaliser

PARIS = ZoneInfo("Europe/Paris")

# Au-delà, un pointage ouvert est presque sûrement un « j'ai oublié d'arrêter ».
DUREE_SUSPECTE_H = 10

# Le temps hors affaire. Mesurer le temps perdu fait partie de la demande
# (« on verra le temps réel de fab… et le temps perdu ») : ces motifs sont
# pointés comme une affaire, sans CH.
MOTIFS = {
    "ATTENTE_MATIERE": "Attente matière / plans",
    "RANGEMENT": "Rangement · nettoyage",
    "PANNE": "Panne machine",
    "ENTRETIEN": "Entretien machine",
    "TRAJET": "Trajet · dépôt",
    "FORMATION": "Formation",
    "AUTRE": "Autre (à préciser au bureau)",
}

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
                  ("cout_interfast", "REAL"), ("cout_horaire", "REAL")],
    # Heure de RÉCEPTION, quand elle diffère de l'heure du geste : pointé hors
    # ligne, rejoué au retour du réseau.
    "pointages": [("recu", "TEXT")],
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


def valider(db, personne: str, lundi: dt.date, par: str) -> dict:
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
                   (personne, lundi.isoformat(), par, _iso(maintenant())))
    return validation(db, personne, lundi)


def devalider(db, personne: str, lundi: dt.date) -> None:
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
            "motifs": [{"code": k, "libelle": v} for k, v in MOTIFS.items()]}


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
    return {"jour": jour.isoformat(), "atelier": atelier, "pose": pose}


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
    if motif and motif not in MOTIFS:
        motif = "AUTRE"
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
    avant = db.execute("SELECT personne, debut FROM pointages WHERE id=?", (pid,)).fetchone()
    if not avant:
        raise KeyError(pid)
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
        alertes.append("Motif « autre » à préciser")
    if p.get("recu"):
        alertes.append("Pointé hors ligne, reçu le %s à %s" % (p["recu"][8:10] + "/" + p["recu"][5:7],
                                                              p["recu"][11:16]))
    if p.get("source") == "tablette":
        alertes.append("CH saisi à la main, absent des plannings")
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
            "libelle": p["chantier"] or MOTIFS.get(p["motif"] or "", "") or p["libelle"],
            "jours": [0.0] * 7, "total": 0.0})
        l["jours"][jour] += h
        l["total"] += h
        p["heures"] = round(h, 2)
        p["alertes"] = _alertes(p, a)
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
                         "Aucune trace amont : ni plan de charge, ni planning FAB, ni BET")]
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


# ═══════════════════════ VERS INTERFAST (à blanc) ═══════════════════════

def envois(db, lundi: dt.date, a: dt.datetime) -> dict:
    """Ce que le chemin A de docs/interfast.md enverrait pour une semaine :
    une intervention par personne, par CH et par jour, durée réelle,
    SEULEMENT pour les RHI validés. Rien n'est écrit : on montre, pour que
    le jour du branchement personne ne découvre ce qui part.

    Une ligne est « bloquée » si InterFast ne pourrait pas la recevoir :
    personne sans compte InterFast, CH inconnu d'InterFast, chantier sans
    client (planifier_intervention exige un client)."""
    fin = lundi + dt.timedelta(days=7)
    valides = {r["personne"]: dict(r) for r in db.execute(
        "SELECT * FROM validations WHERE lundi=?", (lundi.isoformat(),))}
    gens = {r["nom"]: dict(r) for r in db.execute("SELECT * FROM personnes")}
    affaires = {r["ch"]: dict(r) for r in db.execute("SELECT * FROM affaires")}
    lignes = {}
    for r in db.execute("""SELECT * FROM pointages WHERE annule=0 AND ch IS NOT NULL
                           AND fin IS NOT NULL AND debut >= ? AND debut < ? ORDER BY debut""",
                        (lundi.isoformat(), fin.isoformat())):
        p = dict(r)
        if p["personne"] not in valides:
            continue
        cle = (p["personne"], p["ch"], p["debut"][:10])
        l = lignes.setdefault(cle, {"personne": p["personne"], "ch": p["ch"], "jour": p["debut"][:10],
                                    "heure": p["debut"][11:16], "heures": 0.0, "libelles": [],
                                    "deja_envoye": False})
        l["heures"] += _heures(p, a)
        if p["libelle"] and p["libelle"] not in l["libelles"]:
            l["libelles"].append(p["libelle"])
        l["deja_envoye"] = l["deja_envoye"] or bool(p["interfast"])
    sortie = []
    for l in lignes.values():
        g, aff = gens.get(l["personne"], {}), affaires.get(l["ch"], {})
        blocages = []
        if not g.get("interfast_user_id"):
            blocages.append("personne sans compte InterFast")
        if not aff.get("interfast_id"):
            blocages.append("CH inconnu d'InterFast")
        elif not aff.get("client"):
            blocages.append("chantier sans client")
        sortie.append({
            **l, "heures": round(l["heures"], 2),
            "technicien": g.get("nom_complet") or l["personne"],
            "client": aff.get("client", ""), "chantier": aff.get("titre") or aff.get("chantier", ""),
            "description": f"RHI · {l['ch']} · " + (" / ".join(l["libelles"]) or "pointage"),
            "etat": "déjà envoyé" if l["deja_envoye"] else ("bloqué" if blocages else "prêt"),
            "blocages": blocages})
    sortie.sort(key=lambda x: (x["jour"], x["personne"], x["ch"]))
    return {"lundi": lundi.isoformat(), "lignes": sortie,
            "personnes_validees": sorted(valides),
            "prets": sum(1 for x in sortie if x["etat"] == "prêt"),
            "bloques": sum(1 for x in sortie if x["etat"] == "bloqué"),
            "heures_pretes": round(sum(x["heures"] for x in sortie if x["etat"] == "prêt"), 2)}


# ═══════════════════════ SAUVEGARDE ═══════════════════════

GARDER_JOURS = 30


def sauvegarder(db, dossier: Path, jour: dt.date) -> Path | None:
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
