# RHI — Relevé Hebdomadaire Individuel · guide pour Claude Code

Pointage des heures **par affaire (CH)** pour VIP Plus (serrurerie), Groupe
Alma. Né de la réunion du 29/09/2026 (Philippe, Alexis — responsable
serrurerie/menuiserie —, Serge qui développe). Tout est en **français** :
code commenté, commits narratifs, écrans, bancs. Même esprit qu'Ali Baba.

## Pourquoi
Aujourd'hui on est « incapable de faire un point d'affaire » : les feuilles
d'heures arrivent tard, à la main, et les chargés d'affaires estiment les
heures en cherchant le chantier au Ctrl+F dans le planning de pose. RHI fait
tomber chaque heure de l'atelier et de la pose sur son CH, au moment où elle
est faite.

## Ce qui est en place (V1)
- `app.py` — FastAPI. `uvicorn app:app --host 0.0.0.0 --port 9000`.
- `rhi/lecture.py` — lit les plannings Excel d'Alexis (ATE et POSE SER).
  Cases fusionnées résolues, noms des opérateurs lus dans la colonne du
  samedi, colonnes du plan de charge repérées **par leur titre**.
- `rhi/base.py` — SQLite (`$RHI_DONNEES/rhi.db`) : personnes, affaires,
  planning importé, pointages ; le RHI et le point d'affaire.
- `rhi/interfast.py` — client MCP InterFast, **écriture coupée**
  (`ECRITURE = False`).
- `public/index.html` + `terrain.js` — la tablette de l'atelier / le
  téléphone du chef d'équipe de pose.
- `public/bureau.html` + `bureau.js` — RHI de la semaine, à vérifier, point
  d'affaire, en ce moment, dépôt des plannings.

## Règles de fond (décidées en réunion — ne pas les perdre)
- **Jamais bloqué.** Toucher un chantier arrête le précédent ; un CH absent
  des plannings est accepté et signalé ; un arrêt oublié reste ouvert et
  signalé. Tout ce qui est douteux se corrige **au bureau**, rien ne se
  refuse sur la tablette.
- **Hyper simple.** Trois gestes : mon nom, mon chantier, « J'arrête ».
  Boutons pour des gants. À l'atelier la tablette revient aux noms après
  une minute sans geste (elle est partagée).
- **Le BET ne pointe pas** : il est en frais. Le fichier BET est refusé à
  l'import, avec la raison.
- **La pose pointe au téléphone du chef d'équipe**, pour lui et son binôme
  d'un seul geste. La tablette n'y survivrait pas.
- **Le temps perdu se mesure** : motifs hors affaire (attente matière,
  rangement, panne…) pointés comme une affaire.
- **Un arrêt oublié ne gonfle pas une affaire** : un pointage ouvert depuis
  plus de 10 h sort du point d'affaire (« en suspens ») jusqu'à correction.
- **Le CH est la seule clé fiable.** Les noms de chantier varient d'un
  fichier à l'autre (LES CIGALES/LES CIGLAES, ABCD/ACBD).

## InterFast — ce qui reste à apprendre
InterFast est la base de tout : les CH en viennent, les heures doivent y
retomber (« comme si j'étais allé sur le terrain » — une ligne
d'intervention : garde-corps, tel ouvrier, 45 minutes). Mais on ne connaît
pas encore **l'outil MCP qui liste les affaires** ni **celui qui pose des
heures sur un CH** : ceux d'Ali Baba visent un client, pas une affaire.
Premier geste avec la clé : `GET /api/interfast/outils` (bureau). Clé
`INTERFAST_VIP` dans l'environnement **uniquement** — ce dépôt est PUBLIC.
Depuis le dev : aucune écriture réelle.

## Données
- **Aucun vrai planning, aucun nom réel dans le dépôt** (il est public).
  Les bancs travaillent sur des classeurs fictifs de même forme
  (`bancs/fabrique.py`). `donnees/` et `*.xlsx` sont ignorés par git.

## Bancs — verts avant toute poussée
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt   # une fois
sh bancs/tous.sh && git commit …
```
`tous.sh` sort en erreur au premier banc rouge. Chaque fonctionnalité = son
banc ; un bug corrigé = le banc qui l'aurait attrapé. `banc-pointage.py`
joue une semaine entière à travers l'API avec une horloge truquée
(`app.state.horloge`).

## Accès
`RHI_CODE_TERRAIN` (tablettes, téléphones) et `RHI_CODE_BUREAU` dans
l'environnement. Absents = ouvert (poste de dev uniquement). Le code est
demandé une fois par appareil et gardé.

## Suite (voir docs/feuille-de-route.md)
V2 menuiserie (Alfa) · lecture des CH depuis InterFast · envoi des heures
dans InterFast · écran d'atelier qui fait défiler pose / traitement ·
analyse de la marche en avant (BET → fab → traitement → pose) du lundi 7 h.
