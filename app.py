"""RHI — le pointage des heures par affaire, pour VIP Plus (serrurerie).

    uvicorn app:app --host 0.0.0.0 --port 9000

Deux écrans :
  /         la tablette de l'atelier ou le téléphone du chef d'équipe de pose :
            je choisis mon nom, je touche mon chantier, le chrono tourne ;
  /bureau   le RHI de chacun (lundi matin), le point d'affaire, l'import des
            plannings, les corrections.
"""
import csv
import datetime as dt
import io
import os
import tempfile
import time
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rhi import base, interfast, lecture

PUBLIC = Path(__file__).parent / "public"

app = FastAPI(title="RHI")
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

def _codes(*noms):
    return {os.getenv(n) for n in noms if os.getenv(n)}


def acces_terrain(x_rhi_code: str = Header(default="")):
    codes = _codes("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU")
    if codes and x_rhi_code not in codes:
        raise HTTPException(401, "Code d'accès")


def acces_bureau(x_rhi_code: str = Header(default="")):
    codes = _codes("RHI_CODE_BUREAU")
    if codes and x_rhi_code not in codes:
        raise HTTPException(401, "Code bureau")


def _lundi(texte: str | None) -> dt.date:
    d = dt.date.fromisoformat(texte) if texte else maintenant().date()
    return d - dt.timedelta(days=d.weekday())


# ═══════════════════════ TERRAIN ═══════════════════════

class Demarrage(BaseModel):
    personnes: list[str]
    ch: str | None = None
    motif: str | None = None
    libelle: str = ""
    appareil: str = ""
    quand: str | None = None   # heure du geste, si pointé hors ligne


class Arret(BaseModel):
    personnes: list[str]
    quand: str | None = None


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


@app.get("/api/sante")
def sante():
    return {"ok": True, "heure": maintenant().isoformat(), "interfast_ecriture": interfast.ECRITURE}


@app.get("/api/personnes", dependencies=[Depends(acces_terrain)])
def api_personnes(equipe: str | None = None, c=Depends(db)):
    return base.personnes(c, equipe)


@app.get("/api/menu", dependencies=[Depends(acces_terrain)])
def api_menu(personne: str, jour: str | None = None, c=Depends(db)):
    j = dt.date.fromisoformat(jour) if jour else maintenant().date()
    return base.menu(c, personne, j)


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
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ids": ids, "pointages": base.en_cours(c)}


@app.post("/api/arreter", dependencies=[Depends(acces_terrain)])
def api_arreter(a: Arret, c=Depends(db)):
    n = base.arreter(c, [p.strip().upper() for p in a.personnes], _quand(a.quand))
    return {"arretes": n}


@app.get("/api/ecran", dependencies=[Depends(acces_terrain)])
def api_ecran(jour: str | None = None, c=Depends(db)):
    j = dt.date.fromisoformat(jour) if jour else maintenant().date()
    return base.ecran(c, j) | {"maintenant_ms": int(time.time() * 1000)}


# ═══════════════════════ BUREAU ═══════════════════════

@app.post("/api/plannings", dependencies=[Depends(acces_bureau)])
async def api_plannings(fichier: UploadFile = File(...), c=Depends(db)):
    """Dépôt d'un planning Excel : atelier ou pose de la serrurerie."""
    contenu = await fichier.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as t:
        t.write(contenu)
        t.flush()
        try:
            donnees = lecture.lire(t.name)
        except lecture.FichierInattendu as e:
            raise HTTPException(422, str(e))
    res = base.importer(c, donnees)
    res["fichier"] = fichier.filename
    return res


@app.get("/api/rhi", dependencies=[Depends(acces_bureau)])
def api_rhi(personne: str | None = None, semaine: str | None = None, c=Depends(db)):
    lundi = _lundi(semaine)
    noms = [personne] if personne else [p["nom"] for p in base.personnes(c)]
    releves = [base.rhi(c, n, lundi, maintenant()) for n in noms]
    return {"lundi": lundi.isoformat(), "releves": releves}


@app.get("/api/rhi.csv", dependencies=[Depends(acces_bureau)])
def api_rhi_csv(semaine: str | None = None, c=Depends(db)):
    """Le RHI de toute l'équipe, à ouvrir dans Excel (séparateur « ; »)."""
    lundi = _lundi(semaine)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=";")
    jours = [(lundi + dt.timedelta(days=i)).strftime("%a %d/%m") for i in range(7)]
    w.writerow(["Personne", "CH", "Chantier / motif", *jours, "Total", "Validé par"])
    for p in base.personnes(c):
        r = base.rhi(c, p["nom"], lundi, maintenant())
        v = r["validee"]
        for l in r["lignes"]:
            w.writerow([p["nom"], l["ch"] or "", l["libelle"],
                        *[str(x).replace(".", ",") for x in l["jours"]],
                        str(l["total"]).replace(".", ","),
                        f"{v['par']} le {v['le'][:10]}" if v else ""])
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


class Validation(BaseModel):
    personne: str
    semaine: str
    qui: str = "bureau"


@app.post("/api/validations", dependencies=[Depends(acces_bureau)])
def api_valider(v: Validation, c=Depends(db)):
    try:
        return base.valider(c, v.personne.upper(), _lundi(v.semaine), v.qui)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/validations", dependencies=[Depends(acces_bureau)])
def api_devalider(personne: str, semaine: str, c=Depends(db)):
    base.devalider(c, personne.upper(), _lundi(semaine))
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
