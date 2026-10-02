"""Le contrôle de la semaine du responsable de BU (revue avec Alexis, 01/10/2026).

« Il me faudrait la liste de tous les gars : lundi pointé 8 h, mardi 8 h.
Si je vois 9 h, je sais qu'il y en a un qui a tapé plus. » Une ligne par
personne active — même sans une heure —, chaque journée jugée face à la
journée normale (8 h du lundi au jeudi, 7 h le vendredi : 39 h)."""
import datetime as dt
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "RHI_HEURES_JOUR"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402
from rhi import base  # noqa: E402

heure = {"t": dt.datetime(2026, 10, 1, 18, 0)}   # jeudi soir : lun, mar, mer écoulés
appli.app.state.horloge = lambda: heure["t"]
appli.app.state.chemin_base = tmp / "rhi.db"
c = TestClient(appli.app)
db = base.connexion(tmp / "rhi.db")
t = lambda j, h, m=0: dt.datetime(2026, 9, j, h, m) if j > 9 else dt.datetime(2026, 10, j, h, m)  # noqa: E731
with db:
    for n, e in (("PAUL", "atelier"), ("JEAN", "atelier"), ("LUC", "pose"), ("ZOE", "atelier")):
        db.execute("INSERT INTO personnes(nom, equipe) VALUES (?,?)", (n, e))
    db.execute("INSERT INTO affaires(ch, chantier, source, maj) VALUES ('CH00901','LES PINS','planning','')")
    # ZOE est au planning mercredi, et n'a rien pointé.
    db.execute("""INSERT INTO planning(personne, jour, ch, libelle, origine)
                  VALUES ('ZOE','2026-09-30','CH00901','LES PINS','atelier')""")

# PAUL : trois journées justes (pause comprise, coupure du midi arrêtée).
for j in (28, 29, 30):
    base.demarrer(db, ["PAUL"], t(j, 7), ch="CH00901")
    base.arreter(db, ["PAUL"], t(j, 12))
    base.demarrer(db, ["PAUL"], t(j, 13), ch="CH00901")
    base.arreter(db, ["PAUL"], t(j, 16))
# JEAN : 9 h lundi, 6 h mardi, rien mercredi.
base.demarrer(db, ["JEAN"], t(28, 7), ch="CH00901"); base.arreter(db, ["JEAN"], t(28, 16))
base.demarrer(db, ["JEAN"], t(29, 7), ch="CH00901"); base.arreter(db, ["JEAN"], t(29, 13))
# LUC : pointe en ce moment, jeudi.
base.demarrer(db, ["LUC"], t(1, 7), ch="CH00901")

d = c.get("/api/rhi?semaine=2026-09-28").json()
co = d["controle"]
verif(co["reference"][:5] == [8, 8, 8, 8, 7] and co["semaine"] == 39, f"journée normale par défaut : {co['reference']}")
lignes = {l["personne"]: l for l in co["lignes"]}
verif(set(lignes) == {"PAUL", "JEAN", "LUC", "ZOE"}, "tous les gars actifs, même sans une heure (ZOE)")
p = lignes["PAUL"]
verif([j["etat"] for j in p["jours"][:3]] == ["ok"] * 3 and p["ecart"] == 0 and p["juste"],
      f"PAUL : trois journées de 8 h, rien à redire : {p}")
verif(p["jours"][3]["etat"] == "aujourdhui" and p["jours"][4]["etat"] == "a_venir",
      "jeudi pas fini, vendredi à venir : ni l'un ni l'autre n'est jugé")
j = lignes["JEAN"]
verif([x["etat"] for x in j["jours"][:3]] == ["plus", "moins", "rien"], f"JEAN : 9 h en plus, 6 h en moins, rien : {j['jours'][:3]}")
verif(j["ecart"] == -9 and not j["juste"], f"JEAN : 15 h sur 24 attendues, −9 h : {j['ecart']}")
verif(lignes["ZOE"]["jours"][2]["etat"] == "manque", "ZOE : prévue au planning mercredi, rien pointé → manque")
verif(lignes["ZOE"]["jours"][0]["etat"] == "rien", "ZOE lundi : ni planning ni pointage → rien (à voir quand même)")
verif(lignes["LUC"]["en_cours"], "LUC pointe en ce moment : signalé")
verif([l["equipe"] for l in co["lignes"]] == sorted(l["equipe"] for l in co["lignes"]), "rangés par équipe")

# Un pointage resté ouvert depuis mardi n'invente pas 50 heures dans la grille.
base.demarrer(db, ["ZOE"], t(29, 7), ch="CH00901")
z = {l["personne"]: l for l in c.get("/api/rhi?semaine=2026-09-28").json()["controle"]["lignes"]}["ZOE"]
verif(z["a_verifier"] >= 1, f"ZOE : un arrêt oublié est signalé à vérifier : {z}")

# Le samedi travaillé apparaît et compte en plus.
heure["t"] = dt.datetime(2026, 10, 5, 9, 0)
base.demarrer(db, ["PAUL"], dt.datetime(2026, 10, 3, 8), ch="CH00901")
base.arreter(db, ["PAUL"], dt.datetime(2026, 10, 3, 12))
p = {l["personne"]: l for l in c.get("/api/rhi?semaine=2026-09-28").json()["controle"]["lignes"]}["PAUL"]
verif(p["jours"][5]["etat"] == "plus" and p["jours"][5]["heures"] == 4, f"samedi : 4 h en plus : {p['jours'][5]}")

# La journée normale se règle ; une valeur folle ne casse pas le contrôle.
os.environ["RHI_HEURES_JOUR"] = "7;7;7;7;7,5"
verif(base.heures_reference()[:5] == [7, 7, 7, 7, 7.5], f"réglage à la demi-heure : {base.heures_reference()}")
os.environ["RHI_HEURES_JOUR"] = "huit"
verif(base.heures_reference()[:5] == [8, 8, 8, 8, 7], "réglage illisible : la valeur par défaut")
os.environ.pop("RHI_HEURES_JOUR")

fin("banc-semaine")
