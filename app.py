"""RHI — le pointage des heures par affaire, pour VIP Plus (serrurerie).

    uvicorn app:app --host 0.0.0.0 --port 9000

Deux écrans :
  /         la tablette de l'atelier ou le téléphone du chef d'équipe de pose :
            je choisis mon nom, je touche mon chantier, le chrono tourne ;
  /bureau   le RHI de chacun (lundi matin), le point d'affaire, l'import des
            plannings, les corrections.
"""
import collections
import csv
import hmac
import datetime as dt
import io
import os
import tempfile
import time
from typing import Annotated
from pathlib import Path

import asyncio
import contextlib

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rhi import base, courrier, interfast, lecture

PUBLIC = Path(__file__).parent / "public"

def sauvegarde_du_jour():
    c = base.connexion(getattr(app.state, "chemin_base", None))
    try:
        dossier = Path(getattr(app.state, "chemin_base", None) or base.chemin_base()).parent / "sauvegardes"
        return base.sauvegarder(c, dossier, maintenant().date())
    finally:
        c.close()


FINIS = ("envoye", "simule", "sans destinataire")


def marche_du_lundi(c, a: dt.datetime, force: bool = False):
    """La synthèse de la marche en avant, envoyée le lundi à partir de 7 h.

    Une fois par lundi : ce qui est parti, ou ce qui ne pouvait pas partir
    (SMTP non réglé, aucun destinataire), est noté et ne se retente pas.
    Seule une erreur se retente à l'heure suivante. `force` : le bouton du
    bureau, n'importe quel jour."""
    if not force and (a.weekday() != 0 or a.hour < 7):
        return None
    jour = a.date()
    deja = c.execute("SELECT statut FROM courriers WHERE jour=? AND quoi='marche'",
                     (jour.isoformat(),)).fetchone()
    if deja and deja[0] in FINIS and not force:
        return None
    texte = base.synthese_md(base.marche(c, jour))
    statut = courrier.envoyer(f"Marche en avant — {jour.strftime('%d/%m/%Y')}", texte,
                              f"marche-en-avant-{jour.isoformat()}.md", texte.encode("utf-8"))
    with c:
        c.execute("""INSERT INTO courriers VALUES (?, 'marche', ?, ?)
                     ON CONFLICT(jour, quoi) DO UPDATE SET statut=excluded.statut, le=excluded.le""",
                  (jour.isoformat(), statut, a.isoformat(timespec="seconds")))
    return statut


def lundi_matin():
    c = base.connexion(getattr(app.state, "chemin_base", None))
    try:
        return marche_du_lundi(c, maintenant())
    finally:
        c.close()


async def veilleur():
    """Toutes les heures : la sauvegarde du jour, et le lundi la marche en avant."""
    while True:
        for tache in (sauvegarde_du_jour, lundi_matin):
            try:
                await asyncio.to_thread(tache)
            except Exception as e:  # une tâche ratée ne doit pas tuer l'appli
                print(tache.__name__, "ratée :", e)
        await asyncio.sleep(3600)


@contextlib.asynccontextmanager
async def vie(_app):
    tache = asyncio.create_task(veilleur())
    yield
    tache.cancel()


app = FastAPI(title="RHI", lifespan=vie)
# L'horloge est remplaçable : les bancs jouent une semaine entière en une seconde.
app.state.horloge = base.maintenant


def db():
    c = base.connexion(getattr(app.state, "chemin_base", None))
    try:
        yield c
    finally:
        c.close()


def maintenant() -> dt.datetime:
    return app.state.horloge()


# ── Accès : deux codes, dans l'environnement. Absents = ouvert (poste de dev). ──
#    Le terrain ne voit que le pointage ; le bureau voit tout. Pas de mot de
#    passe par ouvrier : une tablette sur pied, des gants, 7 h du matin.

def en_production() -> bool:
    """Clever Cloud pose CC_APP_ID sur ses machines ; RHI_PRODUCTION pour ailleurs."""
    return bool(os.getenv("CC_APP_ID") or os.getenv("RHI_PRODUCTION"))


LONGUEUR_BUREAU = 12


def reglage_des_codes() -> str | None:
    """Ce qui cloche dans les codes, ou None. Échoue FERMÉ : un seul code
    posé ouvrait tout le bureau (sauvegarde de la base comprise) à Internet
    si l'autre variable manquait — revue de sécurité du 29/09/2026."""
    t, b = os.getenv("RHI_CODE_TERRAIN", ""), os.getenv("RHI_CODE_BUREAU", "")
    if not t and not b:
        return "aucun code d'accès" if en_production() else None
    if not b:
        return "RHI_CODE_BUREAU absent"
    if not t:
        return "RHI_CODE_TERRAIN absent"
    if t == b:
        return "codes terrain et bureau identiques"
    if en_production() and len(b) < LONGUEUR_BUREAU:
        return f"code bureau trop court ({LONGUEUR_BUREAU} caractères au moins)"
    return None


# Au-delà de 10 codes faux en une minute depuis la même adresse : 429 pendant
# une minute. Sans frein, un code se devinait en quelques heures.
ECHECS: dict = collections.defaultdict(collections.deque)
FENETRE_S, ECHECS_MAX = 60, 10


def _adresse(request: Request) -> str:
    # Derrière le proxy de Clever, la dernière adresse de X-Forwarded-For est
    # celle que le proxy a vue ; les précédentes, le client peut les inventer.
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[-1].strip() if xff else (request.client.host if request.client else "?")


def _verifier(request: Request, donne: str, admis: list, quoi: str):
    ip, now = _adresse(request), time.monotonic()
    q = ECHECS[ip]
    while q and now - q[0] > FENETRE_S:
        q.popleft()
    if len(q) >= ECHECS_MAX:
        raise HTTPException(429, "Trop de codes faux : attendre une minute")
    if any(hmac.compare_digest(donne.encode(), a.encode()) for a in admis):
        if not q:
            ECHECS.pop(ip, None)
        return
    q.append(now)
    print(f"code {quoi} refusé depuis {ip}")
    raise HTTPException(401, f"Code {quoi}")


def acces_terrain(request: Request, x_rhi_code: str = Header(default="")):
    probleme = reglage_des_codes()
    if probleme:
        raise HTTPException(503, f"Accès fermé, réglage incomplet : {probleme}")
    t, b = os.getenv("RHI_CODE_TERRAIN", ""), os.getenv("RHI_CODE_BUREAU", "")
    if t or b:
        _verifier(request, x_rhi_code, [x for x in (t, b) if x], "d'accès")


def acces_bureau(request: Request, x_rhi_code: str = Header(default="")):
    probleme = reglage_des_codes()
    if probleme:
        raise HTTPException(503, f"Accès fermé, réglage incomplet : {probleme}")
    b = os.getenv("RHI_CODE_BUREAU", "")
    if b:
        _verifier(request, x_rhi_code, [b], "bureau")


def _jour(texte: str | None) -> dt.date:
    """Une date AAAA-MM-JJ venue d'un paramètre : illisible = 422, pas 500."""
    if not texte:
        return maintenant().date()
    try:
        return dt.date.fromisoformat(texte[:10])
    except ValueError:
        raise HTTPException(422, "Date illisible (AAAA-MM-JJ)")


def _lundi(texte: str | None) -> dt.date:
    d = _jour(texte)
    return d - dt.timedelta(days=d.weekday())


# ═══════════════════════ TERRAIN ═══════════════════════

# Bornes : un chef et son équipe, pas cent mille noms (revue du 29/09/2026).
Nom = Annotated[str, Field(max_length=60)]


class Demarrage(BaseModel):
    personnes: list[Nom] = Field(max_length=6)
    ch: str | None = Field(default=None, max_length=20)
    motif: str | None = Field(default=None, max_length=30)
    libelle: str = Field(default="", max_length=200)
    appareil: str = Field(default="", max_length=60)
    quand: str | None = Field(default=None, max_length=40)   # heure du geste, si pointé hors ligne


class Arret(BaseModel):
    personnes: list[Nom] = Field(max_length=6)
    quand: str | None = Field(default=None, max_length=40)


# Un geste rejoué plus de 72 h après : le bureau le saisit à la main, en
# connaissance de cause, plutôt qu'une tablette oubliée dans un tiroir ne
# réécrive une semaine déjà relue.
RETARD_MAX = dt.timedelta(hours=72)


def _quand(texte: str | None) -> dt.datetime:
    """L'heure du geste. Une horloge d'appareil en avance est ramenée à maintenant."""
    now = maintenant()
    if not texte:
        return now
    try:
        t = dt.datetime.fromisoformat(texte).replace(tzinfo=None, microsecond=0)
    except ValueError:
        raise HTTPException(422, "Heure illisible")
    if t > now:
        return now
    if now - t > RETARD_MAX:
        raise HTTPException(422, "Pointage de plus de 72 h : à saisir au bureau")
    return t


@app.get("/api/config")
def api_config():
    """Pour les titres des écrans : quelle entreprise sert cette instance."""
    e = interfast.entreprise()
    return {"entreprise": e, "nom": lecture.ENTREPRISES[e]}


def _etat(c) -> dict:
    chemin = Path(getattr(app.state, "chemin_base", None) or base.chemin_base()).resolve()
    return {"ok": True, "heure": maintenant().isoformat(), "interfast_ecriture": interfast.ECRITURE,
            "entreprise": interfast.entreprise(),
            "base": {"dans_donnees": "donnees" in chemin.parts or bool(os.getenv("RHI_DONNEES")),
                     "journal": c.execute("PRAGMA journal_mode").fetchone()[0],
                     "inscriptible": os.access(chemin.parent, os.W_OK)},
            "cle_interfast": bool(interfast.cle()),
            "codes_acces": reglage_des_codes() or "ok",
            "courrier": {"smtp": bool(courrier.reglage()["host"] and courrier.reglage()["user"]),
                         "destinataires": len(courrier.destinataires())}}


@app.get("/api/sante")
def sante(c=Depends(db)):
    """Public, donc muet : « prêt » ou non. Le détail (clé, codes, courrier)
    renseignait un visiteur sans code ; il est derrière le code bureau
    (/api/sante/detail). Un code mal réglé ferme l'accès, et « codes » le dit :
    c'est la seule chose qu'on ne peut pas lire autrement à ce moment-là."""
    e = _etat(c)
    pret = (e["codes_acces"] == "ok" and e["base"]["journal"] == "delete" and e["base"]["inscriptible"]
            and (e["base"]["dans_donnees"] or not en_production()))
    return {"ok": True, "heure": e["heure"], "pret": pret, "codes": "ok" if e["codes_acces"] == "ok" else "à régler",
            "version": version()}


def version() -> str:
    """Le commit qui tourne. Clever pose COMMIT_ID au déploiement ; la chaîne
    compare cette valeur au commit qu'elle vient de pousser. Un déploiement
    « réussi » qui sert encore l'ancien code (Ali Baba, 01/09/2026 : cinq
    fois) se voit ici. Le dépôt est public : le commit n'apprend rien."""
    return os.getenv("COMMIT_ID") or os.getenv("RHI_VERSION") or "inconnue"


@app.get("/api/sante/detail", dependencies=[Depends(acces_bureau)])
def sante_detail(c=Depends(db)):
    """Ce qu'on vérifie après chaque déploiement (docs/deploiement.md) : la
    base doit être dans donnees/ (le bucket), en journal « delete »."""
    return _etat(c)


@app.get("/api/personnes", dependencies=[Depends(acces_terrain)])
def api_personnes(equipe: str | None = None, c=Depends(db)):
    return base.personnes(c, equipe)


@app.get("/api/menu", dependencies=[Depends(acces_terrain)])
def api_menu(personne: str, jour: str | None = None, c=Depends(db)):
    j = _jour(jour)
    return base.menu(c, personne, j) | {"mes_heures": base.mes_heures(c, personne.upper(), j, maintenant())}


@app.get("/api/en-cours", dependencies=[Depends(acces_terrain)])
def api_en_cours(personne: str | None = None, c=Depends(db)):
    # `maintenant_ms` (instant absolu) : l'appareil en déduit son écart
    # d'horloge sans dépendre de son fuseau — une tablette réglée en UTC
    # lisait « 11:36 » de Paris comme 11:36 UTC, deux heures d'erreur.
    return {"maintenant": maintenant().isoformat(), "maintenant_ms": int(time.time() * 1000),
            "pointages": base.en_cours(c, personne)}


@app.post("/api/demarrer", dependencies=[Depends(acces_terrain)])
def api_demarrer(d: Demarrage, c=Depends(db)):
    ch = (d.ch or "").strip().upper() or None
    if ch and not lecture.codes_ch(ch):
        raise HTTPException(422, "Un CH s'écrit CH suivi de 5 chiffres (CH00901)")
    if ch:
        ch = lecture.codes_ch(ch)[0]
    try:
        ids = base.demarrer(c, [p.strip().upper() for p in d.personnes if p.strip()],
                            _quand(d.quand), ch=ch, motif=d.motif, libelle=d.libelle,
                            appareil=d.appareil, recu=maintenant())
    except base.SemaineValidee as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ids": ids, "pointages": base.en_cours(c)}


@app.post("/api/arreter", dependencies=[Depends(acces_terrain)])
def api_arreter(a: Arret, c=Depends(db)):
    n = base.arreter(c, [p.strip().upper() for p in a.personnes], _quand(a.quand))
    return {"arretes": n}


@app.get("/api/ecran", dependencies=[Depends(acces_terrain)])
def api_ecran(jour: str | None = None, c=Depends(db)):
    j = _jour(jour)
    return base.ecran(c, j) | {"maintenant_ms": int(time.time() * 1000)}


# ═══════════════════════ BUREAU ═══════════════════════

TAILLE_MAX = 20_000_000   # les vrais plannings font moins de 2 Mo


@app.post("/api/plannings", dependencies=[Depends(acces_bureau)])
async def api_plannings(fichier: UploadFile = File(...), c=Depends(db)):
    """Dépôt d'un planning Excel : atelier ou pose de la serrurerie."""
    contenu = await fichier.read(TAILLE_MAX + 1)
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, f"Fichier de plus de {TAILLE_MAX // 1_000_000} Mo : ce n'est pas un planning")
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as t:
        t.write(contenu)
        t.flush()
        try:
            # Hors de la boucle : un gros classeur ne gèle plus les tablettes.
            donnees = await asyncio.to_thread(lecture.lire, t.name, interfast.entreprise())
        except lecture.FichierInattendu as e:
            raise HTTPException(422, str(e))
    res = base.importer(c, donnees)
    res["fichier"] = fichier.filename
    return res


@app.get("/api/rhi", dependencies=[Depends(acces_bureau)])
def api_rhi(personne: str | None = None, semaine: str | None = None, c=Depends(db)):
    lundi = _lundi(semaine)
    noms = [personne] if personne else [p["nom"] for p in base.personnes(c)]
    a = maintenant()
    releves = [base.rhi(c, n, lundi, a) for n in noms]
    return {"lundi": lundi.isoformat(), "releves": releves,
            "oublis": [o for o in base.oublis(c, lundi, a) if o["personne"] in noms],
            "temps_perdu": base.temps_perdu(c, lundi, a)}


@app.get("/api/rhi.csv", dependencies=[Depends(acces_bureau)])
def api_rhi_csv(semaine: str | None = None, c=Depends(db)):
    """Le RHI de toute l'équipe, à ouvrir dans Excel (séparateur « ; »)."""
    lundi = _lundi(semaine)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")

    def cellule(x) -> str:
        # Pas de formule Excel : un nom ou un libellé saisi sur la tablette
        # (« =HYPERLINK(…) ») s'exécutait à l'ouverture du CSV au bureau.
        x = str(x)
        return "'" + x if x[:1] in ("=", "+", "-", "@", "\t", "\r") else x
    jours = [(lundi + dt.timedelta(days=i)).strftime("%a %d/%m") for i in range(7)]
    w.writerow(["Personne", "CH", "Chantier / motif", *jours, "Total", "Validé par"])
    for p in base.personnes(c):
        r = base.rhi(c, p["nom"], lundi, maintenant())
        v = r["validee"]
        for l in r["lignes"]:
            w.writerow([cellule(p["nom"]), l["ch"] or l["ch_impute"] or "", cellule(l["libelle"]),
                        *[str(x).replace(".", ",") for x in l["jours"]],
                        str(l["total"]).replace(".", ","),
                        cellule(f"{v['par']} le {v['le'][:10]}") if v else ""])
    nom = f"RHI-{lundi.isoformat()}.csv"
    return PlainTextResponse("﻿" + sortie.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.get("/api/affaires", dependencies=[Depends(acces_bureau)])
def api_affaires(c=Depends(db)):
    return base.affaires_pointees(c, maintenant())


@app.get("/api/affaires/{ch}", dependencies=[Depends(acces_bureau)])
def api_affaire(ch: str, c=Depends(db)):
    return base.point_affaire(c, ch.upper(), maintenant())


class Correction(BaseModel):
    ch: str | None = None
    motif: str | None = None
    libelle: str | None = None
    debut: str | None = None
    fin: str | None = None
    annule: int | None = None
    qui: str = "bureau"


@app.patch("/api/pointages/{pid}", dependencies=[Depends(acces_bureau)])
def api_corriger(pid: int, corr: Correction, c=Depends(db)):
    champs = {k: v for k, v in corr.model_dump().items() if v is not None and k != "qui"}
    try:
        return base.corriger(c, pid, corr.qui, **champs)
    except KeyError:
        raise HTTPException(404, "Pointage inconnu")
    except base.SemaineValidee as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


class Saisie(BaseModel):
    personne: str
    debut: str
    fin: str
    ch: str | None = None
    motif: str | None = None
    libelle: str = ""
    qui: str = "bureau"


@app.post("/api/pointages", dependencies=[Depends(acces_bureau)])
def api_saisir(s: Saisie, c=Depends(db)):
    try:
        pid = base.ajouter(c, s.personne.upper(), s.debut, s.fin, ch=s.ch, motif=s.motif,
                           libelle=s.libelle, qui=s.qui)
    except base.SemaineValidee as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": pid}


class Personne(BaseModel):
    actif: int | None = None
    equipe: str | None = None
    cout_horaire: float | None = None   # 0 efface le coût saisi
    interfast_user_id: int | None = None
    delier: bool = False


class NouvellePersonne(BaseModel):
    nom: str = Field(max_length=60)
    equipe: str = "atelier"


@app.post("/api/personnes", dependencies=[Depends(acces_bureau)])
def api_ajouter_personne(p: NouvellePersonne, c=Depends(db)):
    try:
        return base.ajouter_personne(c, p.nom, p.equipe, maintenant())
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/personnes/detail", dependencies=[Depends(acces_bureau)])
def api_personnes_detail(c=Depends(db)):
    return {"cout_defaut": base.cout_defaut(), "personnes": base.personnes_detail(c)}


@app.patch("/api/personnes/{nom}", dependencies=[Depends(acces_bureau)])
def api_personne(nom: str, p: Personne, c=Depends(db)):
    with c:
        if p.actif is not None:
            c.execute("UPDATE personnes SET actif=? WHERE nom=?", (p.actif, nom.upper()))
        if p.equipe in ("atelier", "pose"):
            c.execute("UPDATE personnes SET equipe=? WHERE nom=?", (p.equipe, nom.upper()))
        if p.delier:
            base.lier(c, nom.upper(), None)
        elif p.interfast_user_id is not None:
            try:
                base.lier(c, nom.upper(), p.interfast_user_id)
            except ValueError as e:
                raise HTTPException(422, str(e))
        if p.cout_horaire is not None:
            if p.cout_horaire < 0:
                raise HTTPException(422, "Un coût horaire est positif")
            c.execute("UPDATE personnes SET cout_horaire=? WHERE nom=?",
                      (p.cout_horaire or None, nom.upper()))
    return {"ok": True}


@app.get("/api/sauvegarde", dependencies=[Depends(acces_bureau)])
def api_sauvegarde(c=Depends(db)):
    """La base entière, à garder ailleurs que sur le serveur."""
    nom = f"rhi-{maintenant().strftime('%Y-%m-%d-%Hh%M')}.db"
    return Response(base.copie_complete(c), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{nom}"'})


@app.get("/api/interfast/outils", dependencies=[Depends(acces_bureau)])
async def api_interfast_outils():
    try:
        return {"ecriture": interfast.ECRITURE,
                "outils": await interfast.outils(getattr(app.state, "transport_interfast", None))}
    except interfast.InterFastIndisponible as e:
        raise HTTPException(503, str(e))


@app.post("/api/interfast/chantiers", dependencies=[Depends(acces_bureau)])
async def api_interfast_chantiers(c=Depends(db)):
    """Relit tous les chantiers d'InterFast (lecture seule) : CH, client, statut."""
    try:
        liste = await interfast.chantiers(getattr(app.state, "transport_interfast", None))
    except interfast.InterFastIndisponible as e:
        raise HTTPException(503, str(e))
    return base.importer_chantiers(c, liste)


@app.post("/api/interfast/utilisateurs", dependencies=[Depends(acces_bureau)])
async def api_interfast_utilisateurs(c=Depends(db)):
    """Relie les personnes de RHI aux utilisateurs InterFast (lecture seule)."""
    try:
        liste = await interfast.utilisateurs(getattr(app.state, "transport_interfast", None))
    except interfast.InterFastIndisponible as e:
        raise HTTPException(503, str(e))
    return base.importer_utilisateurs(c, liste)


@app.get("/api/interfast/utilisateurs", dependencies=[Depends(acces_bureau)])
def api_utilisateurs_interfast(c=Depends(db)):
    return base.utilisateurs_interfast(c)


@app.post("/api/interfast/montants", dependencies=[Depends(acces_bureau)])
async def api_interfast_montants(c=Depends(db)):
    """Relit le vendu HT des CH au planning ou pointés (lecture seule, un CH à la fois)."""
    t = getattr(app.state, "transport_interfast", None)
    try:
        lus = [await interfast.devis_de(ch, t) for ch in base.affaires_a_chiffrer(c)]
    except interfast.InterFastIndisponible as e:
        raise HTTPException(503, str(e))
    return base.importer_montants(c, lus)


@app.get("/api/marche", dependencies=[Depends(acces_bureau)])
def api_marche(jour: str | None = None, semaines: int = 4, c=Depends(db)):
    """La marche en avant : chaque pose des semaines à venir face à son amont."""
    j = _jour(jour)
    return base.marche(c, j, max(1, min(semaines, 12)))


@app.post("/api/marche/envoyer", dependencies=[Depends(acces_bureau)])
def api_marche_envoyer(c=Depends(db)):
    """Envoie la synthèse du jour tout de suite (le bouton du bureau)."""
    statut = marche_du_lundi(c, maintenant(), force=True)
    if statut.startswith("erreur"):
        raise HTTPException(502, statut)
    return {"statut": statut, "a": courrier.destinataires()}


@app.get("/api/marche/courrier", dependencies=[Depends(acces_bureau)])
def api_marche_courrier(c=Depends(db)):
    dernier = c.execute("SELECT * FROM courriers WHERE quoi='marche' ORDER BY jour DESC LIMIT 1").fetchone()
    return {"a": courrier.destinataires(), "smtp": bool(courrier.reglage()["host"] and courrier.reglage()["user"]),
            "dernier": dict(dernier) if dernier else None}


@app.get("/api/marche.md", dependencies=[Depends(acces_bureau)])
def api_marche_md(jour: str | None = None, c=Depends(db)):
    """La synthèse du lundi, en Markdown, à envoyer telle quelle."""
    j = _jour(jour)
    texte = base.synthese_md(base.marche(c, j))
    return PlainTextResponse(texte, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="marche-en-avant-{j.isoformat()}.md"'})


@app.get("/api/interfast/envois", dependencies=[Depends(acces_bureau)])
def api_envois(semaine: str | None = None, c=Depends(db)):
    """À blanc : ce qui partirait vers InterFast pour une semaine validée."""
    return base.envois(c, _lundi(semaine), maintenant()) | {"ecriture": interfast.ECRITURE}


ENVOI_EN_COURS = asyncio.Lock()


class Envoi(BaseModel):
    semaine: str
    cases: list[str] | None = None      # « CH00901|2026-09-28 » ; rien = toutes les prêtes


@app.post("/api/interfast/envois", dependencies=[Depends(acces_bureau)])
async def api_poser_cases(e: Envoi, c=Depends(db)):
    """Pose dans le planning InterFast les cases prêtes d'une semaine validée.

    Une à la fois, en série (le MCP se trompe sous les appels parallèles) ;
    chaque référence est gardée dès qu'elle arrive, si bien qu'une panne au
    milieu ne renvoie jamais deux fois la même case. Coupé tant que
    ECRITURE = False : 403, et rien n'est tenté."""
    if not interfast.ECRITURE:
        raise HTTPException(403, "Écriture InterFast coupée : rien n'est envoyé (docs/interfast.md)")
    # Un seul envoi à la fois, quel que soit le poste : un second clic
    # pendant un envoi de plusieurs minutes posait chaque case deux fois.
    if ENVOI_EN_COURS.locked():
        raise HTTPException(409, "Un envoi vers InterFast est déjà en cours : attendre qu'il finisse")
    async with ENVOI_EN_COURS:
        t = getattr(app.state, "transport_interfast", None)
        d = base.envois(c, _lundi(e.semaine), maintenant())
        voulues = [x for x in d["cases"] if x["etat"] == "prête" and (e.cases is None or x["id"] in e.cases)]
        posees, echecs = [], []
        for case in voulues:
            try:
                ref = await interfast.poser_case(case, t)
            except interfast.CaseSansReference as err:
                base.case_posee(c, case, base.A_VERIFIER)
                echecs.append({"id": case["id"], "erreur": str(err)})
                continue
            except interfast.InterFastIndisponible as err:
                echecs.append({"id": case["id"], "erreur": str(err)})
                continue
            base.case_posee(c, case, ref)
            posees.append({"id": case["id"], "ref": ref})
    return {"posees": posees, "echecs": echecs}


class CaseDuBureau(BaseModel):
    ch: str
    jour: str
    ref: str = ""


@app.post("/api/interfast/cases/completer", dependencies=[Depends(acces_bureau)])
def api_completer_case(k: CaseDuBureau, c=Depends(db)):
    """« Ajoutés dans InterFast » : les retardataires sont dans la case."""
    try:
        return {"pointages": base.completer_case(c, k.ch, k.jour)}
    except KeyError as err:
        raise HTTPException(404, str(err))


@app.post("/api/interfast/cases/reference", dependencies=[Depends(acces_bureau)])
def api_reference_case(k: CaseDuBureau, c=Depends(db)):
    """Trancher une case À VÉRIFIER : sa vraie référence, ou « pas créée »."""
    try:
        return base.reference_case(c, k.ch, k.jour, k.ref)
    except KeyError as err:
        raise HTTPException(404, str(err))
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.post("/api/interfast/suivi", dependencies=[Depends(acces_bureau)])
async def api_suivi(semaine: str, c=Depends(db)):
    """Relit dans InterFast (lecture seule) ce que chaque case posée a reçu
    à sa clôture : les heures de chaque technicien, face au RHI.

    La case se retrouve par les heures du jour de ses techniciens : chaque
    entrée donne l'id interne d'une intervention, qu'on traduit en IN…
    (une lecture par id, gardée pour le reste de la relecture). Une fois
    trouvé, l'id est gardé sur la case : les relectures suivantes vont
    droit à ses heures. Pas d'entrée : la case n'est pas encore terminée.
    Tout en série — le MCP se trompe sous les appels parallèles."""
    t = getattr(app.state, "transport_interfast", None)
    jours, refs = {}, {}
    terminees, a_terminer, illisibles = [], [], []
    try:
        for case in base.cases_posees(c, _lundi(semaine)):
            num, coupee = case["num"], False
            for uid in ([] if num else case["users"]):
                cle = (uid, case["jour"])
                if cle not in jours:
                    jours[cle] = await interfast.journee(uid, case["jour"], t)
                coupee = coupee or jours[cle][1]
                for e in jours[cle][0]:
                    n = e["intervention"]
                    if n not in refs:
                        refs[n] = await interfast.reference_de(n, t)
                    if refs[n] == case["ref"]:
                        num = n
                        break
                if num:
                    break
            if not num and coupee:
                # Introuvable dans des journées coupées : peut-être terminée,
                # au-delà de ce que le MCP laisse lire. On ne conclut pas.
                illisibles.append(case["ref"])
                continue
            entrees = await interfast.heures_intervention(num, t) if num else []
            base.enregistrer_suivi(c, case["ref"], num, entrees)
            (terminees if entrees else a_terminer).append(case["ref"])
    except interfast.InterFastIndisponible as err:
        raise HTTPException(503, str(err))
    d = base.envois(c, _lundi(semaine), maintenant())
    return {"terminees": terminees, "a_terminer": a_terminer, "illisibles": illisibles,
            "ecarts": [x["ref"] for x in d["cases"] if x["etat"] == "écart"]}


@app.get("/api/chantiers", dependencies=[Depends(acces_bureau)])
def api_chantiers(semaine: str | None = None, conduc: str | None = None, c=Depends(db)):
    return base.chantiers_semaine(c, _lundi(semaine), maintenant(), conduc or None)


class Controle(BaseModel):
    ch: str
    semaine: str
    qui: str = Field(max_length=60)


@app.post("/api/controles", dependencies=[Depends(acces_bureau)])
def api_controler(k: Controle, c=Depends(db)):
    try:
        return base.controler_ch(c, k.ch.upper(), _lundi(k.semaine), k.qui, maintenant())
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/controles", dependencies=[Depends(acces_bureau)])
def api_decontroler(ch: str, semaine: str, c=Depends(db)):
    try:
        base.decontroler_ch(c, ch.upper(), _lundi(semaine))
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


class Validation(BaseModel):
    personne: str
    semaine: str
    qui: str = "bureau"


@app.post("/api/validations", dependencies=[Depends(acces_bureau)])
def api_valider(v: Validation, c=Depends(db)):
    try:
        # L'heure de l'application, pas celle du système : le banc truque la
        # première, et un tampon pris sur la seconde changeait avec le jour réel.
        return base.valider(c, v.personne.upper(), _lundi(v.semaine), v.qui, maintenant())
    except ValueError as e:
        raise HTTPException(409, str(e))


class ValidationDeMasse(BaseModel):
    semaine: str
    qui: str


@app.post("/api/validations/toutes", dependencies=[Depends(acces_bureau)])
def api_valider_tout(v: ValidationDeMasse, c=Depends(db)):
    return base.valider_tout(c, _lundi(v.semaine), v.qui, maintenant())


@app.delete("/api/validations", dependencies=[Depends(acces_bureau)])
def api_devalider(personne: str, semaine: str, c=Depends(db)):
    try:
        base.devalider(c, personne.upper(), _lundi(semaine))
    except base.DejaDansInterFast as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


# ═══════════════════════ PAGES ═══════════════════════

@app.get("/")
def page_terrain():
    return FileResponse(PUBLIC / "index.html")


@app.get("/bureau")
def page_bureau():
    return FileResponse(PUBLIC / "bureau.html")


@app.get("/ecran")
def page_ecran():
    return FileResponse(PUBLIC / "ecran.html")


app.mount("/", StaticFiles(directory=PUBLIC), name="public")
