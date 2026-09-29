"""La marche en avant : chaque pose à venir face à ses études et sa fabrication.

Le cas fondateur est celui de la synthèse manuelle du 28/09/2026, qui a
compté comme « réalisées » des fabrications datées du 06/10 : ici, une
fabrication n'est réalisée que si elle est datée d'AVANT le jour de
l'analyse. Planning fictif, construit case par case."""
import datetime as dt
import os
import tempfile
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient

from bancs import fabrique
from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "INTERFAST_VIP", "RHI_ENTREPRISE", "RHI_MARCHE_A",
          "SMTP_HOST", "SMTP_USER"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402

appli.app.state.chemin_base = tmp / "rhi.db"
appli.app.state.horloge = lambda: dt.datetime(2026, 9, 28, 7, 0)
c = TestClient(appli.app)
D = dt.date

# ── Atelier : plan de charge + planning FAB sur trois semaines ──
wb = openpyxl.Workbook()
pc = wb.active
pc.title = "plan de charge "
for i, t in enumerate(["N° Affaire", "Affaire", "Désignation", "Conduc.", "Prévisionnel h/h", "S - FAB",
                       "COMMENTAIRE"], start=1):
    pc.cell(5, i, t)
backlog = [
    ("CH00901", "FAIT AVANT", "GC", "AA", 10, "S38", ""),
    ("CH00902", "FAB FUTURE", "PORTAIL", "AA", 10, "S41", ""),          # le cas du 28/09
    ("CH00904", "FIGE", "PORTE", "AA", 10, "S38", "ATTENTE VALIDATION POUR FAB"),
    ("CH00905", "BLOQUE", "GRILLE", "AA", 10, "S40", "ATTENTE HAUTEUR POTEAUX"),
    ("CH00906", "SANS SEMAINE", "MC", "AA", 10, None, ""),
    ("CH00907", "STOCK", "GC", "AA", 10, "S05", ""),
    ("CH00909", "MULTI", "PERGOLA ALU", "AA", 10, "S38", ""),          # l'affaire a de l'amont…
    (None, "PAR NOM", "GC RAMPANT", "AA", 10, "S38", ""),               # ligne sans CH
    ("CH00910", "DEUX PIECES", "TOITURE", "AA", 10, "S38", ""),
    ("CH00912", "ANCIEN", "PERGOLA ALU", "AA", 10, "S27", ""),
]
for r, l in enumerate(backlog, start=6):
    for col, v in enumerate(l, start=1):
        pc.cell(r, col, v)
fab = wb.create_sheet("planning FAB")
fab["A2"] = "VIP PLUS"
debut = D(2026, 1, 26)                       # de fin janvier à mi-octobre, colonne par jour
jours = [debut + dt.timedelta(days=i) for i in range((D(2026, 10, 18) - debut).days)]
for i, j in enumerate(jours):
    fab.cell(2, 2 + i, dt.datetime.combine(j, dt.time()))
col = {j: 2 + i for i, j in enumerate(jours)}
fab.cell(3, col[D(2026, 9, 26)], "PAUL")     # un samedi : le nom de l'opérateur
fab.merge_cells(start_row=3, start_column=col[D(2026, 9, 26)], end_row=6, end_column=col[D(2026, 9, 27)])
for jour, ch in ((D(2026, 9, 15), "CH00901"), (D(2026, 10, 6), "CH00902"), (D(2026, 9, 16), "CH00904"),
                 (D(2026, 1, 28), "CH00907"), (D(2026, 9, 17), "CH00909"), (D(2026, 9, 18), "CH00910")):
    fab.cell(3, col[jour], "CHANTIER\nTRAVAUX")
    fab.cell(5, col[jour], ch)
fab.cell(3, col[D(2026, 9, 17)], "MULTI\nPERGOLA ALU")
fab.cell(3, col[D(2026, 9, 18)], "DEUX PIECES\nTOITURE")
fab.cell(3, col[D(2026, 10, 14)], "DEUX PIECES\nPORTE 2 VTX")                    # l'autre pièce, fabriquée APRÈS
fab.cell(3, col[D(2026, 7, 1)], "ANCIEN\nPERGOLA ALU")                          # fab d'avant les CH : pas de CH
fab.cell(3, col[D(2026, 7, 2)], "ANCIEN\nMAIN COURANTE")                        # même chantier, autre pièce
fab.cell(5, col[D(2026, 10, 14)], "CH00910")
tr = wb.create_sheet("planning TRAITEMENT")
for i, j in enumerate(jours):
    tr.cell(2, 2 + i, dt.datetime.combine(j, dt.time()))
tr.cell(3, col[D(2026, 9, 29)], "FAIT AVANT - CH00901/DEVIS1234")            # jusqu'au 02/10, pose le 01/10
tr.merge_cells(start_row=3, start_column=col[D(2026, 9, 29)], end_row=3, end_column=col[D(2026, 10, 2)])
tr.cell(4, col[D(2026, 9, 21)], "STOCK - CHCH00907/DEVIS")                   # fini avant la pose : rien à dire
tr.cell(5, col[D(2026, 9, 29)], "FAIT AVANT - CH00901/DEVIS1234")            # la même, écrite deux fois
tr.merge_cells(start_row=5, start_column=col[D(2026, 9, 29)], end_row=5, end_column=col[D(2026, 10, 2)])
tr.cell(6, col[D(2026, 10, 7)], "FAB FUTURE - CH00902/DEVIS")                # part après la pose du 05/10 : autre pièce
wb.save(tmp / "ate.xlsx")

# ── Pose : septembre et octobre ──
wb = openpyxl.Workbook()
poses = {"SEPTEMBRE 2026": [], "OCTOBRE 2026": [(1, "FAIT AVANT", "CH00901"), (5, "FAB FUTURE", "CH00902"),
                                                  (2, "RIEN NULLE PART", "CH00903"), (6, "FIGE", "CH00904"),
                                                  (13, "BLOQUE", "CH00905"), (14, "SANS SEMAINE", "CH00906"),
                                                  (15, "STOCK", "CH00907"), (20, "ETUDE", "CH00908"),
                                                  (7, "SANS NUMERO", None), (8, "MULTI\nPORTES (X5)", "CH00909"),
                                                  (9, "PAR NOM\nGC RAMPANT", "CH00911"),
                                                  (12, "DEUX PIECES\nTOITURE", "CH00910"),
                                                  (16, "ANCIEN\nPERGOLA (X66)", "CH00912"),
                                                  (19, "ANCIEN\nPORTAIL", "CH00912")]}
for i, (onglet, liste) in enumerate(poses.items()):
    ws = wb.active if i == 0 else wb.create_sheet()
    ws.title = onglet
    for j in range(1, 31):
        ws.cell(2, 1 + j, j)
    ws["A4"], ws["A5"], ws["A6"] = "EQUIPE LUC & MARC", "N° AFFAIRE", "POSE IMPERATIVE"
    # une équipe par pose, pour des lignes indépendantes
    for k, (jour, chantier, ch) in enumerate(liste):
        base_r = 4 + 4 * k
        ws.cell(base_r, 1, f"EQUIPE P{k} & Q{k}")
        ws.cell(base_r + 1, 1, "N° AFFAIRE")
        ws.cell(base_r + 2, 1, "POSE IMPERATIVE")
        ws.cell(base_r, 1 + jour, chantier if "\n" in chantier else f"{chantier}\nPOSE")
        if ch:
            ws.cell(base_r + 1, 1 + jour, ch)
wb.save(tmp / "pose.xlsx")

# ── BET ──
fabrique.bet_complet(tmp / "bet.xlsx", [
    ("CH00908", "GC POUR FAB", "12,13/10/2026", "planifié", "EN ATTENTE FT EQUIPEMENT"),
    ("CH00904", "PORTE POUR FAB", dt.datetime(2026, 9, 10), "terminé", "EN ATTENTE VALIDATION"),
    ("CH00910", "PORTE 2 VTX POUR FAB", "11/10/2026", "planifié", "EN ATTENTE FT"),   # l'autre pièce
])

for f in ("ate.xlsx", "pose.xlsx", "bet.xlsx"):
    r = c.post("/api/plannings", files={"fichier": (f, (tmp / f).read_bytes())})
    verif(r.status_code == 200, f"import {f} : {r.text}")

m = c.get("/api/marche?jour=2026-09-28").json()
par = {l["libelle"].split(" / ")[0]: l for l in m["lignes"]}
verif(len(par) == 13, f"treize poses dans les 4 semaines : {sorted(par)}")


def niveau(nom):
    return par[nom]["niveau"]


def textes(nom):
    return " | ".join(x["texte"] for x in par[nom]["constats"])


verif(niveau("FAIT AVANT") == "orange" and "traitement de surface" in textes("FAIT AVANT") and "02/10" in textes("FAIT AVANT"),
      f"fab le 15/09, mais en traitement jusqu'au 02/10 pour une pose le 01/10 — {textes('FAIT AVANT')}")
verif("traitement" not in textes("STOCK"), "un traitement fini avant la pose ne dit rien (et « CHCH00907 » se lit)")
verif(textes("FAIT AVANT").count("traitement de surface") == 1, "le même envoi écrit deux fois : un seul constat")
verif("traitement" not in textes("FAB FUTURE"), "un envoi qui part après la pose concerne une autre pièce : silence")
e = c.get("/api/ecran?jour=2026-09-28").json()
verif([t["ch"] for t in e["traitement"]] == ["CH00901"], f"l'écran montre les envois de la semaine : {e['traitement']}")
verif(niveau("FAB FUTURE") == "rouge" and "06/10" in textes("FAB FUTURE"),
      f"LE CAS DU 28/09 : fab le 06/10 n'est PAS réalisée, et elle tombe après la pose du 05/10 — {textes('FAB FUTURE')}")
verif(niveau("RIEN NULLE PART") == "rouge" and "Aucune trace" in textes("RIEN NULLE PART"),
      "rien nulle part et pose dans 4 jours : rouge (orange au-delà de 7 jours)")
verif(niveau("FIGE") == "gris" and "à nettoyer" in textes("FIGE"),
      f"« ATTENTE VALIDATION » alors que la fab est faite : commentaire à nettoyer, pas une alerte — {textes('FIGE')}")
verif(any("BET" in x["texte"] for x in par["FIGE"]["constats"]), "idem pour le commentaire BET resté affiché")
verif(niveau("BLOQUE") == "orange" and "ATTENTE HAUTEUR POTEAUX" in textes("BLOQUE"), "commentaire bloquant, pas de fab")
verif(niveau("SANS SEMAINE") == "orange" and "sans semaine" in textes("SANS SEMAINE"), "trou de suivi")
verif(niveau("STOCK") == "gris" and "4 mois" in textes("STOCK"), f"fab en janvier, pose en octobre — {textes('STOCK')}")
verif(niveau("ETUDE") == "orange" and "3 semaines" in textes("ETUDE") and "FT EQUIPEMENT" in textes("ETUDE"),
      f"étude finie le 13/10 pour une pose le 20/10 : sous le délai de 3 semaines — {textes('ETUDE')}")
verif(niveau("SANS NUMERO") == "orange" and "sans N° d'affaire" in textes("SANS NUMERO"), "pose sans CH")
verif(niveau("MULTI") == "orange" and "PORTES (X5)" in textes("MULTI"),
      f"LE CAS ASSAS : la pergola est faite, les portes n'ont aucune trace — {textes('MULTI')}")
verif("par le nom" in textes("PAR NOM") and "Aucune trace" not in textes("PAR NOM"),
      f"LE CAS LUNAS : ligne du plan de charge sans CH, rapprochée par le nom — {textes('PAR NOM')}")
verif(niveau("PAR NOM") == "orange" and "S38 (passée)" in textes("PAR NOM"),
      "… et jugée comme les autres : S38 passée sans trace au planning FAB")
verif(niveau("DEUX PIECES") == "vert",
      f"LE CAS POLYGONE : la porte fabriquée après, et son étude en attente, ne font pas "
      f"une alerte sur la pose de la toiture — {textes('DEUX PIECES')}")
ancien = [l for l in m["lignes"] if l["libelle"].startswith("ANCIEN")]
pergola = [l for l in ancien if "PERGOLA" in l["libelle"]][0]
portail = [l for l in ancien if "PORTAIL" in l["libelle"]][0]
verif(pergola["niveau"] == "vert" and any("cases sans CH" in x["texte"] for x in pergola["constats"]),
      f"LE CAS PERGOLA : fab de juillet sans CH, retrouvée par le nom et la pièce — {pergola['constats']}")
verif(portail["niveau"] != "vert", "… mais le nom seul ne suffit pas : le portail n'est pas « fait » par la main courante")
verif(m["lignes"][0]["niveau"] == "rouge", "les rouges d'abord")
verif(all(x["consecutifs"] == 1 for l in m["lignes"] for x in l["constats"] if x["niveau"] != "vert"),
      "première analyse : chaque constat compte 1")

# Une semaine plus tard, les mêmes constats comptent deux analyses consécutives ;
# celui qui s'est résolu ne compte plus.
appli.app.state.horloge = lambda: dt.datetime(2026, 9, 30, 7, 0)
m2 = c.get("/api/marche?jour=2026-09-30").json()
bloque = [l for l in m2["lignes"] if l["libelle"].startswith("BLOQUE")][0]
verif(bloque["constats"][0]["consecutifs"] == 2, f"deuxième constat identique d'affilée : {bloque['constats'][0]}")
verif(m2["bet_charge"] and m2["bet_a_jour_au"] == "2026-10-13", "le BET chargé, et jusqu'où il va")

# ── La synthèse en Markdown ──
md = c.get("/api/marche.md?jour=2026-09-30")
verif(md.status_code == 200 and "attachment" in md.headers["content-disposition"], "téléchargeable")
t = md.text
verif(t.startswith("# Marche en avant — semaine du 30/09"), "titre daté")
verif("## Risques prioritaires" in t and "## À surveiller" in t and "## BET" in t,
      "les rubriques des synthèses d'Alexis")
verif(t.index("## Risques prioritaires") < t.index("## À surveiller") < t.index("## À confirmer ou nettoyer"),
      "dans l'ordre de gravité")
verif("FAB FUTURE" in t and "2ᵉ analyse d'affilée" in t, "les constats et leur répétition")
verif("planifié jusqu'au 13/10" in t, "l'état du BET")

# ── Le lundi 7 h, par courrier ──
from rhi import courrier  # noqa: E402
postes = []
courrier.transport = lambda dests, sujet, texte, nom, piece: postes.append((dests, sujet, nom, piece)) or "envoye"
base_ = appli.base.connexion(appli.app.state.chemin_base)
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 5, 8, 0)) == "sans destinataire",
      "sans RHI_MARCHE_A : rien ne part, et c'est noté")
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 5, 9, 0)) is None, "noté : pas retenté toutes les heures")
os.environ["RHI_MARCHE_A"] = "alexis@exemple.fr, philippe@exemple.fr"
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 12, 6, 30)) is None, "pas avant 7 h")
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 13, 8, 0)) is None, "pas un mardi")
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 12, 7, 5)) == "envoye", "lundi 7 h : part")
dests, sujet, nom, piece = postes[0]
verif(dests == ["alexis@exemple.fr", "philippe@exemple.fr"] and sujet == "Marche en avant — 12/10/2026"
      and nom == "marche-en-avant-2026-10-12.md", f"à qui, quoi : {postes[0][:3]}")
verif(piece.decode().startswith("# Marche en avant — semaine du 12/10"), "la synthèse du jour, en pièce jointe")
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 12, 8, 5)) is None and len(postes) == 1,
      "une fois par lundi")
courrier.transport = lambda *a: "erreur: serveur injoignable"
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 19, 7, 0)).startswith("erreur"), "une erreur est dite")
courrier.transport = lambda *a: postes.append(a) or "envoye"
verif(appli.marche_du_lundi(base_, dt.datetime(2026, 10, 19, 8, 0)) == "envoye", "une erreur se retente l'heure suivante")
r = c.post("/api/marche/envoyer")
verif(r.status_code == 200 and r.json()["statut"] == "envoye", "le bouton du bureau, n'importe quel jour")
co = c.get("/api/marche/courrier").json()
verif(co["a"] == ["alexis@exemple.fr", "philippe@exemple.fr"] and co["smtp"] is False and co["dernier"]["statut"] == "envoye",
      f"le bureau voit à qui et le dernier envoi : {co}")
verif(c.get("/api/sante/detail").json()["courrier"] == {"smtp": False, "destinataires": 2}, "la santé dit si le courrier est réglé")
courrier.transport = courrier._smtp
verif(courrier.envoyer("x", "y", "z.md", b"") == "simule", "SMTP non réglé : simulé, jamais posté")
os.environ.pop("RHI_MARCHE_A")

fin("banc-marche")
