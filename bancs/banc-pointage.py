"""Une semaine de pointage jouée à travers l'API, horloge truquée.

Vérifie les promesses de la réunion du 29/09/2026 : rien ne bloque (changer
de chantier arrête le précédent, un CH inconnu passe), chef + binôme pointent
d'un geste, le RHI tombe juste au quart d'heure, le point d'affaire compare
au prévu du plan de charge, et le bureau corrige ce qui est douteux.
"""
import datetime as dt
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs import fabrique
from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402

heure = {"t": dt.datetime(2026, 9, 28, 7, 0)}
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)


def a(h, m=0, jour=28):
    heure["t"] = dt.datetime(2026, 9, jour, h, m)


# ── Import des plannings ──
fabrique.atelier(tmp / "ate.xlsx")
fabrique.pose(tmp / "pose.xlsx")
for f in ("ate.xlsx", "pose.xlsx"):
    r = c.post("/api/plannings", files={"fichier": (f, (tmp / f).read_bytes())})
    verif(r.status_code == 200, f"import {f} : {r.text}")
fabrique.bet(tmp / "bet.xlsx")
r = c.post("/api/plannings", files={"fichier": ("bet.xlsx", (tmp / "bet.xlsx").read_bytes())})
verif(r.status_code == 422 and "N° Affaire" in r.json()["detail"], "BET illisible refusé avec la raison")

verif([p["nom"] for p in c.get("/api/personnes?equipe=atelier").json()] == ["JEAN", "PAUL"], "atelier")
verif([p["nom"] for p in c.get("/api/personnes?equipe=pose").json()] == ["LUC", "MARC"], "pose")

m = c.get("/api/menu?personne=PAUL&jour=2026-09-28").json()
verif([x["ch"] for x in m["planning"]] == ["CH00901"], f"planning du jour de Paul : {m['planning']}")
verif(m["planning"][0]["chantier"] == "LES PINS", "nom du chantier depuis le backlog")
verif({x["ch"] for x in m["affaires"]} >= {"CH00901", "CH00902"}, "toutes les affaires proposées")
verif([x["code"] for x in m["motifs"]] == ["RANGEMENT", "ENTRETIEN", "FORMATION", "AUTRE"],
      f"les quatre motifs d'Alexis (30/09), rien d'autre : {m['motifs']}")

# ── Lundi : Paul ──
a(7, 0)
r = c.post("/api/demarrer", json={"personnes": ["paul"], "ch": "CH00901", "appareil": "tab-1"})
verif(r.status_code == 200, r.text)
a(10, 30)
# Il touche un autre chantier sans arrêter : le premier s'arrête tout seul.
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "ch 00902"})
enc = c.get("/api/en-cours?personne=PAUL").json()["pointages"]
verif(len(enc) == 1 and enc[0]["ch"] == "CH00902", "un seul pointage ouvert, le nouveau ; CH normalisé")
a(12, 0)
c.post("/api/demarrer", json={"personnes": ["PAUL"], "motif": "FORMATION"})
a(12, 15)
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00901"})
a(16, 0)
verif(c.post("/api/arreter", json={"personnes": ["PAUL"]}).json()["arretes"] == 1, "arrêt")
verif(c.post("/api/arreter", json={"personnes": ["PAUL"]}).json()["arretes"] == 0,
      "arrêter deux fois ne casse rien")
mh = c.get("/api/menu?personne=paul&jour=2026-09-28").json()["mes_heures"]
verif(mh == {"jour": 9.0, "semaine": 9.0}, f"la tablette montre au gars ce qu'il a pointé : {mh}")

# Un CH absent des plannings : accepté, signalé.
a(7, 0, jour=29)
r = c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00999"})
verif(r.status_code == 200, "CH inconnu accepté : jamais bloqué")
a(8, 0, jour=29)
c.post("/api/arreter", json={"personnes": ["PAUL"]})
verif(c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "GRILLE"}).status_code == 422,
      "un texte qui n'est pas un CH est refusé, avec la forme attendue")
verif(c.post("/api/demarrer", json={"personnes": ["PAUL"]}).status_code == 422, "ni CH ni motif")

# ── Pose : le chef pointe pour lui et son binôme, et oublie d'arrêter ──
a(7, 30)
c.post("/api/demarrer", json={"personnes": ["LUC", "MARC"], "ch": "CH00901"})
verif(len(c.get("/api/en-cours").json()["pointages"]) == 2, "deux personnes, un geste")

# ── L'écran du mur ──
e = c.get("/api/ecran?jour=2026-09-28").json()
at = {p["nom"]: p for p in e["atelier"]}
verif(set(at) == {"JEAN", "PAUL"}, "l'atelier seulement sur la vue atelier")
verif(at["PAUL"]["prevu"][0]["ch"] == "CH00901", "le prévu du jour de Paul")
verif(at["PAUL"]["en_cours"] is None, "Paul est arrêté à 16 h")
verif([j["jour"] for j in e["pose"]] == ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"],
      "la pose, du lundi au vendredi")
lundi_pose = e["pose"][0]["equipes"]
verif(len(lundi_pose) == 1 and lundi_pose[0]["personnes"] == ["LUC", "MARC"] and lundi_pose[0]["ch"] == ["CH00901"],
      f"une équipe, deux noms, un CH : {lundi_pose}")
verif(e["pose"][2]["equipes"] == [], "mercredi : CP, personne en pose")
verif(any(p["en_cours"] for p in e["atelier"]) is False, "")

# ── Mardi soir, le bureau lit le RHI ──
a(18, 0, jour=29)
rhi = c.get("/api/rhi?personne=PAUL&semaine=2026-09-30").json()
verif(rhi["lundi"] == "2026-09-28", "n'importe quel jour ramène au lundi")
r0 = rhi["releves"][0]
lignes = {l["ch"] or l["motif"]: l for l in r0["lignes"]}
verif(lignes["CH00901"]["jours"][0] == 7.25, f"lundi CH00901 = 3h30 + 3h45 : {lignes['CH00901']}")
verif(lignes["CH00902"]["total"] == 1.5, "CH00902 = 1h30")
verif(lignes["FORMATION"]["total"] == 0.25, "hors affaire 15 min")
verif(lignes["CH00999"]["jours"][1] == 1.0, "mardi, CH inconnu 1h")
verif(r0["total"] == 10.0 and r0["hors_affaire"] == 0.25, f"total {r0['total']}")
verif(r0["par_jour"][:2] == [9.0, 1.0], "par jour")
verif(r0["lignes"][-1]["ch"] is None, "le hors-affaire en fin de tableau")
douteux = [p for p in r0["pointages"] if p["alertes"]]
verif(len(douteux) == 1 and "absent des plannings" in douteux[0]["alertes"][0], "CH inconnu signalé")

luc = c.get("/api/rhi?personne=LUC&semaine=2026-09-28").json()["releves"][0]
oubli = luc["pointages"][0]
verif(oubli["fin"] is None and any("oublié" in x for x in oubli["alertes"]),
      "pointage ouvert depuis 34 h : signalé, pas refusé")

# Correction au bureau : l'arrêt oublié de Luc devient 16 h.
r = c.patch(f"/api/pointages/{oubli['id']}", json={"fin": "2026-09-28T16:00", "qui": "Alexis"})
verif(r.status_code == 200 and r.json()["corrige"].startswith("Alexis"), "correction tracée")
luc = c.get("/api/rhi?personne=LUC&semaine=2026-09-28").json()["releves"][0]
verif(luc["total"] == 8.5 and luc["a_verifier"] == 0, f"après correction : {luc['total']}")
verif(c.patch("/api/pointages/9999", json={"fin": "2026-09-28T16:00"}).status_code == 404, "inconnu")

# Saisie a posteriori depuis une feuille papier.
r = c.post("/api/pointages", json={"personne": "jean", "ch": "CH00902",
                                   "debut": "2026-09-29T07:00", "fin": "2026-09-29T15:00"})
verif(r.status_code == 200, r.text)

# ── Point d'affaire ──
pa = c.get("/api/affaires/CH00901").json()
verif(pa["heures_prevues"] == 56.0, "prévu = somme des lignes du plan de charge (40 + 16)")
verif(pa["heures_reelles"] == 7.25 + 8.5, f"réel = Paul + Luc, sans l'oubli de Marc : {pa['heures_reelles']}")
verif(pa["heures_en_suspens"] == 34.5, "l'arrêt oublié de Marc (34 h 30) est à part, pas dans le réel")
marc = c.get("/api/rhi?personne=MARC&semaine=2026-09-28").json()["releves"][0]["pointages"][0]
c.patch(f"/api/pointages/{marc['id']}", json={"fin": "2026-09-28T16:00"})
pa = c.get("/api/affaires/CH00901").json()
verif(pa["heures_reelles"] == 7.25 + 8.5 + 8.5 and pa["heures_en_suspens"] == 0, "corrigé : il rentre")
verif(pa["par_personne"]["PAUL"] == 7.25, "par personne")
verif(set(pa["par_personne"]) == {"PAUL", "LUC", "MARC"}, "atelier et pose sur la même affaire")
verif(pa["par_semaine"] == {"2026-S40": pa["heures_reelles"]}, "par semaine ISO")
liste = c.get("/api/affaires").json()
verif(any(x["ch"] == "CH00999" and x["source"] == "tablette" for x in liste),
      "le CH saisi à la main apparaît, marqué « tablette »")

# ── Annulation ──
pid = r0["pointages"][0]["id"]
c.patch(f"/api/pointages/{pid}", json={"annule": 1})
r0 = c.get("/api/rhi?personne=PAUL&semaine=2026-09-28").json()["releves"][0]
verif(r0["total"] == 6.5, f"un pointage annulé ne compte plus : {r0['total']}")

# ── CSV ──
t = c.get("/api/rhi.csv?semaine=2026-09-28")
verif(t.status_code == 200 and t.text.startswith("﻿Personne;CH"), "CSV lisible par Excel (BOM, ;)")
verif("PAUL;CH00901" in t.text and ",25" in t.text, "virgule décimale française")

# ── Réimporter le planning ne touche pas aux heures ──
c.post("/api/plannings", files={"fichier": ("ate.xlsx", (tmp / "ate.xlsx").read_bytes())})
verif(c.get("/api/rhi?personne=PAUL&semaine=2026-09-28").json()["releves"][0]["total"] == 6.5,
      "import sans effet sur les pointages")

# ── Au planning, rien pointé ; le temps perdu ──
heure["t"] = dt.datetime(2026, 10, 3, 12, 0)
d = c.get("/api/rhi?semaine=2026-09-28").json()
vus = {(o["personne"], o["jour"]) for o in d["oublis"]}
verif(vus == {("LUC", "2026-09-29"), ("MARC", "2026-09-29"), ("PAUL", "2026-09-30"),
              ("PAUL", "2026-10-01"), ("PAUL", "2026-10-02")},
      f"les journées au planning sans aucun pointage : {sorted(vus)}")
luc = [o for o in d["oublis"] if o["personne"] == "LUC"][0]
verif(luc["prevu"] == [{"ch": "CH00901", "libelle": "LES PINS / GARDE-CORPS"}] and luc["origine"] == "pose",
      "on dit ce qui était prévu, pour le saisir d'un geste")
c.post("/api/pointages", json={"personne": "MARC", "ch": "CH00901", "debut": "2026-09-29T07:00",
                               "fin": "2026-09-29T09:00"})
c.patch("/api/personnes/PAUL", json={"actif": 0})
d = c.get("/api/rhi?semaine=2026-09-28").json()
verif({(o["personne"], o["jour"]) for o in d["oublis"]} == {("LUC", "2026-09-29")},
      "un seul pointage dans la journée suffit ; une personne désactivée n'est plus attendue")
c.patch("/api/personnes/PAUL", json={"actif": 1})
heure["t"] = dt.datetime(2026, 9, 30, 10, 0)
d = c.get("/api/rhi?semaine=2026-09-28").json()
verif(("PAUL", "2026-09-30") not in {(o["personne"], o["jour"]) for o in d["oublis"]},
      "aujourd'hui n'est pas fini : pas encore un oubli")
verif(c.get("/api/rhi?personne=LUC&semaine=2026-09-28").json()["oublis"][0]["personne"] == "LUC",
      "le RHI d'une personne ne montre que ses oublis")
tp = d["temps_perdu"]
verif(tp["motifs"] == [{"code": "FORMATION", "libelle": "Formation", "heures": 0.25,
                        "qui": [["PAUL", 0.25]]}] and tp["hors_affaire"] == 0.25,
      f"le temps perdu, par motif et par personne : {tp}")
verif(tp["part"] == round(100 * 0.25 / tp["total"]), "sa part dans les heures de la semaine")
c.post("/api/pointages", json={"personne": "JEAN", "motif": "RANGEMENT", "debut": "2026-09-29T16:00:00",
                               "fin": "2026-09-29T16:00:20"})
verif([m["code"] for m in c.get("/api/rhi?semaine=2026-09-28").json()["temps_perdu"]["motifs"]]
      == ["FORMATION"], "vingt secondes de « rangement » : un doigt qui a glissé, pas du temps perdu")
p0 = c.get("/api/rhi?personne=PAUL&semaine=2026-09-28").json()["releves"][0]["pointages"]
verif(any(x["motif_libelle"] == "Formation" for x in p0), "le motif en clair, pour la feuille imprimée")

# ── Valider d'un geste ce qui n'a rien à regarder ──
# Premier étage d'abord : chaque chargé d'affaires contrôle ses chantiers.
for ch, qui in (("CH00901", "AA"), ("CH00902", "BB")):
    verif(c.post("/api/controles", json={"ch": ch, "semaine": "2026-09-28", "qui": qui}).status_code == 200,
          f"{qui} contrôle {ch}")
r = c.post("/api/validations/toutes", json={"semaine": "2026-09-28", "qui": "Alexis"}).json()
verif(r["valides"] == ["JEAN", "MARC"], f"les relevés propres sont validés : {r}")
verif(r["ecartes"] == [{"personne": "LUC", "raisons": ["journée au planning sans pointage"]},
                       {"personne": "PAUL", "raisons": ["CH saisi à la main, absent des plannings"]}],
      "les autres sont mis de côté, avec la raison — le geste de masse ne valide que ce qu'on n'aurait pas corrigé")
verif(c.get("/api/rhi?personne=JEAN&semaine=2026-09-28").json()["releves"][0]["validee"]["par"] == "Alexis",
      "signé du nom de qui a validé")
r = c.post("/api/validations/toutes", json={"semaine": "2026-09-28", "qui": "Alexis"}).json()
verif(r["valides"] == [], "rejoué : rien de validé deux fois")
for n in ("JEAN", "MARC"):
    c.delete(f"/api/validations?personne={n}&semaine=2026-09-28")

# ── Codes d'accès ──
os.environ["RHI_CODE_TERRAIN"] = "atelier"
os.environ["RHI_CODE_BUREAU"] = "bureau"
verif(c.get("/api/personnes").status_code == 401, "sans code : refusé")
verif(c.get("/api/personnes", headers={"X-RHI-Code": "atelier"}).status_code == 200, "code terrain")
verif(c.get("/api/rhi", headers={"X-RHI-Code": "atelier"}).status_code == 401, "le terrain ne lit pas le RHI")
verif(c.get("/api/rhi", headers={"X-RHI-Code": "bureau"}).status_code == 200, "le bureau, si")
verif(c.get("/api/personnes", headers={"X-RHI-Code": "bureau"}).status_code == 200, "le bureau voit le terrain")
verif(c.get("/api/sante").status_code == 200, "santé sans code")

# ── InterFast : coupé, et il le dit ──
verif(c.get("/api/sante/detail", headers={"X-RHI-Code": "bureau"}).json()["interfast_ecriture"] is False, "écriture InterFast coupée")
r = c.get("/api/interfast/outils", headers={"X-RHI-Code": "bureau"})
verif(r.status_code == 503 and "INTERFAST_VIP" in r.json()["detail"], "sans clé : 503 qui nomme la clé")

fin("banc-pointage")
