# RHI — Relevé Hebdomadaire Individuel · guide pour Claude Code

Pointage des heures **par affaire (CH)** pour VIP Plus (serrurerie) et Alfa
(menuiserie), Groupe Alma — **une instance par entreprise** (`RHI_ENTREPRISE`
= `VIP` ou `ALFA`) : même code, base et clé InterFast séparées, et chaque
instance refuse le planning de l'autre en le disant. Pourquoi pas une base
commune : deux comptes InterFast distincts, et des prénoms en commun entre
les deux plannings (ils se seraient confondus en silence). Né de la réunion du 29/09/2026 (Philippe, Alexis — responsable
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
- `rhi/lecture.py` — lit les plannings Excel : ATE et POSE SER (VIP), Planning
  ATELIER MEN et POSE MEN (Alfa, noms en colonne B, onglet par année).
  Cases fusionnées résolues, noms des opérateurs lus dans la colonne du
  samedi, colonnes du plan de charge repérées **par leur titre**.
- `rhi/base.py` — SQLite (`$RHI_DONNEES/rhi.db`) : personnes, affaires,
  planning importé, pointages ; le RHI et le point d'affaire.
- `rhi/interfast.py` — client MCP InterFast, **écriture coupée**
  (`ECRITURE = False`).
- `public/index.html` + `terrain.js` — la tablette de l'atelier / le
  téléphone du chef d'équipe de pose.
- `public/bureau.html` + `bureau.js` — RHI de la semaine (et sa validation),
  à vérifier, point d'affaire (heures et coût de main-d'œuvre), en ce
  moment, personnes (compte InterFast, coût horaire), dépôt des plannings.

## Règles de fond (décidées en réunion — ne pas les perdre)
- **Jamais bloqué.** Toucher un chantier arrête le précédent ; un CH absent
  des plannings est accepté et signalé ; un arrêt oublié reste ouvert et
  signalé. Tout ce qui est douteux se corrige **au bureau**, rien ne se
  refuse sur la tablette.
- **Jamais bloqué, même sans réseau.** Chaque geste de la tablette part
  dans une file gardée sur l'appareil (`rhi.file`), avec son heure, et se
  vide dès que le serveur répond ; un refus du serveur (4xx) n'est pas
  rejoué en boucle. Le service worker (`public/sw.js`, réseau d'abord)
  sert la page hors ligne ; tout fichier chargé par `index.html` doit être
  dans son `SHELL` (le banc d'écran le vérifie). Côté serveur, `quand` est
  l'heure du geste : au-delà de 72 h, refus (saisie au bureau) ; un geste
  rejoué dans le passé s'arrête là où le pointage suivant commence.
- **Les heures côté navigateur ne dépendent jamais du fuseau de
  l'appareil** : `maintenant_ms` pour l'écart d'horloge, `isoParis()` et
  `msDeParis()` pour convertir (banc-heures, quatre fuseaux et la nuit du
  changement d'heure). `new Date("2026-09-29T07:30:00")` est interdit : il
  lit l'heure dans le fuseau de l'appareil.
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
- **Une semaine validée est verrouillée** au bureau (corrections refusées,
  409) jusqu'à dévalidation ; la tablette, elle, n'est jamais bloquée. On ne
  valide pas une semaine qui a un pointage ouvert.
- **Coût horaire** : saisi au bureau > InterFast (s'il n'est pas à 0) >
  `RHI_COUT_HORAIRE`. Une personne sans coût est NOMMÉE dans le point
  d'affaire, jamais comptée à 0 en silence.
- **Le CH est la seule clé fiable.** Les noms de chantier varient d'un
  fichier à l'autre (LES CIGALES/LES CIGLAES, ABCD/ACBD).

## Marche en avant (bureau)
L'analyse du lundi d'Alexis (études → fab → pose), jusqu'ici faite à la main
par un agent sur les Excel, reprise en code (`base.marche`) parce que la
synthèse du 28/09/2026 comptait comme « réalisées » des fabrications futures.
Règles : une fab n'est **faite** que datée d'avant le jour de l'analyse ;
on juge chaque **pièce** (mots du libellé : PORTE, GRILLE, GC…), pas
l'affaire entière ; les lignes et cases **sans CH** (plannings d'avant les
CH) se rapprochent par le nom du chantier ET les mots de la pièce, jamais par
le nom seul ; « S11 » sans année = l'année la plus récente à moins de 8
semaines devant. Le BET se dépose pour cette analyse seulement (il ne pointe
pas). Les constats sont gardés par jour : « 3ᵉ analyse d'affilée ».

## InterFast — voir docs/interfast.md
- Les CH sont les **chantiers** InterFast (`rechercher_chantiers`, « Réf:
  CH00xxx ») : RHI les relit, en lecture seule (`POST /api/interfast/chantiers`,
  bouton au bureau). Les 36 CH des plannings y étaient tous (29/09/2026).
- L'API **n'écrit pas d'heures** : les timesheets ne se lisent qu'attachées à
  une intervention. `ECRITURE = False` tant que le chemin (A, B ou C dans
  docs/interfast.md) n'est pas décidé et essayé sur une affaire de test.
- Le MCP coupe ses réponses à ~4 000 caractères, ignore les paramètres
  d'`appeler_api` et se trompe sous les appels parallèles : les comptes se
  lisent un par un, en série (docs/interfast.md).
- Coût horaire des techniciens à 0 dans InterFast : aucune rentabilité
  possible là-bas tant qu'il n'est pas renseigné.
- Clé `INTERFAST_VIP` dans l'environnement **uniquement** — ce dépôt est
  PUBLIC. Depuis le dev : aucune écriture réelle. Les bancs utilisent un faux
  serveur (`httpx.MockTransport`, `app.state.transport_interfast`).

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

## Déploiement — voir docs/deploiement.md
Clever Cloud, organisation GROUP ALMA, FS Bucket monté sur `donnees/`,
**une seule instance**, SQLite en journal **`delete`** (le WAL ne marche pas
sur le bucket réseau). La branche `prod` déclenche le déploiement : on ne la
pousse **que quand Philippe dit « pousse »**. Après chaque déploiement, lire
`/api/sante` : un `git push` réussi ne prouve rien.

## Accès
`RHI_CODE_TERRAIN` (tablettes, téléphones) et `RHI_CODE_BUREAU` dans
l'environnement. Absents = ouvert (poste de dev uniquement). Le code est
demandé une fois par appareil et gardé.

## Suite (voir docs/feuille-de-route.md)
V2 menuiserie (Alfa) · lecture des CH depuis InterFast · envoi des heures
dans InterFast · écran d'atelier qui fait défiler pose / traitement ·
analyse de la marche en avant (BET → fab → traitement → pose) du lundi 7 h.
