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
import os
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

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
  vu_le TEXT
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
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    # Une base créée avant l'arrivée d'InterFast n'a pas ces colonnes.
    presentes = {r[1] for r in db.execute("PRAGMA table_info(affaires)")}
    for col, decl in (("client", "TEXT NOT NULL DEFAULT ''"), ("titre", "TEXT NOT NULL DEFAULT ''"),
                      ("statut", "TEXT NOT NULL DEFAULT ''"), ("interfast_id", "INTEGER")):
        if col not in presentes:
            db.execute(f"ALTER TABLE affaires ADD COLUMN {col} {decl}")
    return db


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
                if not l["ch"]:
                    continue
                db.execute("INSERT INTO lignes_prevues VALUES (?,?,?)",
                           (l["ch"], l["designation"], l["heures"]))
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
    """Clôt le pointage ouvert de chaque personne. Rien d'ouvert : rien à faire."""
    n = 0
    with db:
        for nom in noms:
            n += db.execute("""UPDATE pointages SET fin=? WHERE personne=? AND fin IS NULL
                               AND annule=0 AND debut <= ?""",
                            (_iso(quand), nom, _iso(quand))).rowcount
    return n


def demarrer(db, noms: list, quand: dt.datetime, ch=None, motif=None,
             libelle="", appareil="") -> list:
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
            cur = db.execute("""INSERT INTO pointages(personne, ch, motif, libelle, debut, appareil)
                                VALUES (?,?,?,?,?,?)""",
                             (nom, ch, None if ch else motif, libelle or "", _iso(quand), appareil))
            ids.append(cur.lastrowid)
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
            "par_jour": par_jour, "total": total, "hors_affaire": hors,
            "pointages": detail,
            "a_verifier": sum(1 for p in detail if p["alertes"])}


def point_affaire(db, ch: str, a: dt.datetime) -> dict:
    """Heures réelles d'une affaire, par personne et par semaine, face au prévu."""
    aff = db.execute("SELECT * FROM affaires WHERE ch=?", (ch,)).fetchone()
    par_personne, par_semaine, total, suspens = {}, {}, 0.0, 0.0
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
        "par_semaine": {k: round(v, 2) for k, v in sorted(par_semaine.items())},
        "lignes_prevues": [dict(r) for r in db.execute(
            "SELECT designation, heures FROM lignes_prevues WHERE ch=?", (ch,))],
    }


def affaires_pointees(db, a: dt.datetime) -> list:
    """Toutes les affaires, heures réelles et prévues, les plus consommées d'abord."""
    reelles = {}
    for r in db.execute("SELECT * FROM pointages WHERE ch IS NOT NULL AND annule=0"):
        p = dict(r)
        if _suspendu(p, a):
            continue
        reelles[p["ch"]] = reelles.get(p["ch"], 0) + _heures(p, a)
    sortie = []
    for r in db.execute("SELECT * FROM affaires"):
        h = reelles.get(r["ch"], 0.0)
        if not h and not r["heures_prevues"]:
            continue
        sortie.append({"ch": r["ch"], "chantier": r["chantier"], "conduc": r["conduc"],
                       "source": r["source"], "heures_reelles": round(h, 2),
                       "heures_prevues": r["heures_prevues"],
                       "consomme_pct": round(100 * h / r["heures_prevues"]) if r["heures_prevues"] else None})
    return sorted(sortie, key=lambda x: -(x["consomme_pct"] or 0) if x["heures_prevues"] else -x["heures_reelles"])
