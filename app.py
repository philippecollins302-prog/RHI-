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


class Arret(BaseModel):
    personnes: list[str]


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
    return {"maintenant": maintenant().isoformat(), "pointages": base.en_cours(c, personne)}


@app.post("/api/demarrer", dependencies=[Depends(acces_terrain)])
def api_demarrer(d: Demarrage, c=Depends(db)):
    ch = (d.ch or "").strip().upper() or None
    if ch and not lecture.codes_ch(ch):
        raise HTTPException(422, "Un CH s'écrit CH suivi de 5 chiffres (CH00901)")
    if ch:
        ch = lecture.codes_ch(ch)[0]
    try:
        ids = base.demarrer(c, [p.strip().upper() for p in d.personnes if p.strip()],
                            maintenant(), ch=ch, motif=d.motif, libelle=d.libelle,
                            appareil=d.appareil)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ids": ids, "pointages": base.en_cours(c)}


@app.post("/api/arreter", dependencies=[Depends(acces_terrain)])
def api_arreter(a: Arret, c=Depends(db)):
    n = base.arreter(c, [p.strip().upper() for p in a.personnes], maintenant())
    return {"arretes": n}


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
    w.writerow(["Personne", "CH", "Chantier / motif", *jours, "Total"])
    for p in base.personnes(c):
        r = base.rhi(c, p["nom"], lundi, maintenant())
        for l in r["lignes"]:
            w.writerow([p["nom"], l["ch"] or "", l["libelle"],
                        *[str(x).replace(".", ",") for x in l["jours"]],
                        str(l["total"]).replace(".", ",")])
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
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"id": pid}


class Personne(BaseModel):
    actif: int | None = None
    equipe: str | None = None


@app.patch("/api/personnes/{nom}", dependencies=[Depends(acces_bureau)])
def api_personne(nom: str, p: Personne, c=Depends(db)):
    with c:
        if p.actif is not None:
            c.execute("UPDATE personnes SET actif=? WHERE nom=?", (p.actif, nom.upper()))
        if p.equipe in ("atelier", "pose"):
            c.execute("UPDATE personnes SET equipe=? WHERE nom=?", (p.equipe, nom.upper()))
    return {"ok": True}


@app.get("/api/interfast/outils", dependencies=[Depends(acces_bureau)])
async def api_interfast_outils():
    try:
        return {"ecriture": interfast.ECRITURE, "outils": await interfast.outils()}
    except interfast.InterFastIndisponible as e:
        raise HTTPException(503, str(e))


# ═══════════════════════ PAGES ═══════════════════════

@app.get("/")
def page_terrain():
    return FileResponse(PUBLIC / "index.html")


@app.get("/bureau")
def page_bureau():
    return FileResponse(PUBLIC / "bureau.html")


app.mount("/", StaticFiles(directory=PUBLIC), name="public")
