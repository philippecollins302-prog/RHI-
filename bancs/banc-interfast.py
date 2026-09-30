"""InterFast, joué par un FAUX serveur : aucun banc ne parle au vrai.

Le texte rendu imite, à la ligne près, la réponse réelle de
rechercher_chantiers relevée le 29/09/2026 (noms et CH inventés)."""
import datetime as dt
import json
import os
import tempfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from bancs.outils import fin, verif

tmp = Path(tempfile.mkdtemp())
os.environ["RHI_DONNEES"] = str(tmp)
os.environ["INTERFAST_VIP"] = "cle-de-banc"
for k in ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU"):
    os.environ.pop(k, None)

import app as appli  # noqa: E402
from rhi import interfast  # noqa: E402

PAGES = [
    """Page 1/2 — 3 chantiers au total

• [501] M-1 — RESIDENCE DES PINS (Réf: CH00901)
  Statut: En cours | Client: BAILLEUR SUD
  Adresse: 1 rue des Pins, 34000 Montpellier
  Période: début 01/09/2026 → fin prévue 30/11/2026

• [502] Port de plaisance (Réf: CH00902)
  Statut: Terminé | Client: COMMUNE DU PORT
  Adresse: Quai, 34000 Sète
""",
    """Page 2/2 — 3 chantiers au total

• [503] Nouvelle école (Réf: CH00903)
  Statut: Non démarré | Client: VILLE
""",
]
# Forme relevée le 29/09/2026 ; espaces fines insécables dans les montants.
DEVIS = {"CH00901": """Page 1/1 — 4 devis au total

• [aaaaaaaa-0000-0000-0000-000000000001] Import Optima - CH00901 (Réf: D0100)
  Statut: Signé
  Client: BAILLEUR SUD
  Montant: HT: 12\u202f500,50 € | TTC: 15\u202f000,60 €
  Créé le: 03/09/2026

• [aaaaaaaa-0000-0000-0000-000000000002] Import Optima - CH00901 avenant (Réf: D0101)
  Statut: Payé
  Client: BAILLEUR SUD
  Montant: HT: 1 000,00 € | TTC: 1 200,00 €

• [aaaaaaaa-0000-0000-0000-000000000003] Import Optima - CH00901 (Sans référence)
  Statut: Annulé
  Montant: HT: 99 999,00 € | TTC: 1,00 €

• [aaaaaaaa-0000-0000-0000-000000000004] Autre chantier du même client (Réf: D0102)
  Statut: Signé
  Montant: HT: 50 000,00 € | TTC: 60 000,00 €
""", "CH00903": """Page 1/1 — 1 devis au total

• [aaaaaaaa-0000-0000-0000-000000000005] Import Optima - CH00903 (Réf: D0200)
  Statut: Envoyé
  Montant: HT: 8 000,00 € | TTC: 9 600,00 €
"""}
appels = []


def repondre(requete: httpx.Request) -> httpx.Response:
    corps = json.loads(requete.content)
    appels.append(corps)
    verif("apiKey=cle-de-banc" in str(requete.url), "la clé part dans l'URL, comme le veut InterFast")
    if corps["method"] == "tools/list":
        res = {"tools": [{"name": "rechercher_chantiers", "description": "Rechercher des chantiers"}]}
    elif corps["params"]["name"] == "rechercher_devis":
        ch = corps["params"]["arguments"]["recherche"]
        res = {"content": [{"type": "text", "text": DEVIS.get(ch, "Aucun devis trouvé pour ces critères.")}]}
    else:
        verif(corps["params"]["name"] == "rechercher_chantiers", "seuls des outils de lecture")
        res = {"content": [{"type": "text", "text": PAGES[corps["params"]["arguments"]["page"]]}]}
    return httpx.Response(200, text="event: message\ndata: " + json.dumps({"result": res}) + "\n\n")


appli.app.state.transport_interfast = httpx.MockTransport(repondre)
appli.app.state.chemin_base = tmp / "rhi.db"
appli.app.state.horloge = lambda: dt.datetime(2026, 9, 29, 8, 0)
c = TestClient(appli.app)

# ── Lecture du texte ──
f = interfast.lire_chantiers(PAGES[0])
verif(f == [{"id": 501, "titre": "M-1 — RESIDENCE DES PINS", "ch": "CH00901",
             "statut": "En cours", "client": "BAILLEUR SUD"},
            {"id": 502, "titre": "Port de plaisance", "ch": "CH00902",
             "statut": "Terminé", "client": "COMMUNE DU PORT"}], f"fiches : {f}")

# Une affaire pointée à la tablette avant la synchronisation.
c.post("/api/demarrer", json={"personnes": ["PAUL"], "ch": "CH00903"})

# ── Synchronisation ──
r = c.post("/api/interfast/chantiers")
verif(r.status_code == 200, r.text)
verif(r.json()["chantiers"] == 3, "les deux pages lues")
verif(r.json()["absents_d_interfast"] == [], "aucun CH orphelin")
verif([a["params"]["arguments"]["page"] for a in appels] == [0, 1], "pagination suivie jusqu'au bout")
verif(all(a["params"]["arguments"]["taille"] == 20 for a in appels), "20 par page, le maximum")

pa = c.get("/api/affaires").json()
m = c.get("/api/menu?personne=PAUL&jour=2026-09-29").json()
chs = {a["ch"]: a for a in m["affaires"]}
verif("CH00902" not in chs, "un chantier terminé dans InterFast n'est plus proposé")
verif(chs["CH00901"]["client"] == "BAILLEUR SUD", "client InterFast sur la tablette")
verif(chs["CH00903"]["chantier"] == "Nouvelle école", "nom vide complété par le titre InterFast")

# Le CH tapé à la main est confirmé par InterFast : il ne doit plus être signalé.
rhi = c.get("/api/rhi?personne=PAUL&semaine=2026-09-28").json()["releves"][0]
verif(not any("absent des plannings" in a for p in rhi["pointages"] for a in p["alertes"]),
      "CH saisi à la main, puis trouvé dans InterFast : plus d'alerte")

# ── Vendu HT, par les devis ──
verif(interfast.montant("454\u202f256,92") == 454256.92, "espace fine et virgule")
verif(interfast.montant("1.234,50") == 1234.5, "point des milliers")
verif(interfast.montant("1234.50") == 1234.5, "point décimal")
c.post("/api/demarrer", json={"personnes": ["JEAN"], "ch": "CH00901"})   # seuls les CH pointés ou au planning sont lus
r = c.post("/api/interfast/montants").json()
verif(r["lus"] == 2, "CH00902, terminé et jamais pointé, n'est pas relu")
verif(r["avec_vendu"] == 1 and sorted(r["sans_devis_signe"]) == ["CH00903"], f"un CH chiffré : {r}")
pa = c.get("/api/affaires/CH00901").json()
verif(pa["vendu_ht"] == 13500.5, f"signé + payé, sans l'annulé ni le devis d'un autre CH : {pa['vendu_ht']}")
verif(pa["devis_refs"] == "D0100, D0101", "les références gardées pour vérifier")
verif(c.get("/api/affaires/CH00903").json()["vendu_ht"] is None, "devis seulement envoyé : non trouvé, pas 0 €")

# ── Liste des outils ──
r = c.get("/api/interfast/outils")
verif(r.status_code == 200 and r.json()["outils"][0]["nom"] == "rechercher_chantiers", "outils listés")
verif(r.json()["ecriture"] is False, "l'écriture reste coupée")

fin("banc-interfast")
