# Mettre RHI en ligne sur Clever Cloud

Même hébergement et mêmes réglages qu'Ali Baba (voir son
`docs/deploiement-clever-cloud.md`, qui a payé les leçons). Ce qui suit
demande des gestes humains dans la console Clever Cloud : ils ne se font pas
depuis le code.

## Le point qui compte

Clever Cloud détruit la machine à chaque déploiement : tout ce qui est écrit
sur son disque disparaît, **base comprise**. La base vit donc sur un
**FS Bucket** (disque réseau) monté sur `donnees/`. Deux conséquences :

- **SQLite en journal `delete`, jamais `wal`** : le WAL ne fonctionne pas sur
  un disque réseau. RHI est réglé ainsi ; `/api/sante` le montre.
- **Une seule instance.** Deux instances, ce sont deux processus qui
  écrivent dans la même base par le réseau.
- **Et donc `zero-downtime=false`** (30/09/2026) : le déploiement bleu/vert
  ferait tourner l'ancienne et la nouvelle en même temps, ce qui est
  exactement « deux instances » pendant le recouvrement. On paie 20 à 30
  secondes de coupure pour n'avoir qu'un seul écrivain — voir plus bas, et ne
  pas le remettre à `true`.

## L'application VIP Plus existe (29/09/2026)

Identifiant, organisation et adresse : **`outils/clever.conf`**, la seule
copie (installeur, vérification et chaîne la lisent). Créée à la console,
sans lien GitHub : c'est la chaîne ci-dessous qui déploie, pas Clever.

## La chaîne : main → bancs → déploiement → le site réel jugé

**`main` est la branche vivante, et elle déploie seule** (décision de
Philippe, 30/09/2026 : « oui, main déploie seule »). Ce qui y arrive et passe
les bancs part en production sans qu'on le redemande
(`.github/workflows/chaine.yml`, tenue par `banc-chaine`) :

1. toute poussée, toute PR : `sh bancs/tous.sh` ;
2. poussée sur `main`, bancs verts : `clever deploy` vers l'application de
   `clever.conf` — **un seul déploiement à la fois, celui en vol n'est jamais
   annulé** (GitHub n'en garde qu'un en attente : de trois poussées serrées,
   la deuxième est remplacée par la troisième) ;
3. puis `outils/verifier-deploiement.sh` interroge le site jusqu'à ce qu'il
   serve **ce commit** (`"version"` de `/api/sante`, posée par Clever dans
   `COMMIT_ID`) et se dise **prêt**. Dix minutes au plus ; sinon rouge. Un
   `clever deploy` « réussi » ne suffit pas : Ali Baba en a eu cinq de suite
   avec le site en 503 ;
4. un échec sur `main` ouvre une issue **assignée à Philippe** (étiquette
   `chaine-rouge`), un nouvel échec la commente, et le prochain déploiement
   vérifié la **referme tout seul**. Le motif est écrit en tête du run.

`[sans-deploiement]` dans le message de commit : bancs seuls (docs, bancs,
outils — rien de ce qui est servi). Une issue ouverte reste alors ouverte :
seul un déploiement vérifié dit que le site va bien.

Tout garde échoue fermé : secrets absents, site muet, JSON illisible, champ
`version` absent, ancien commit servi — tout cela est rouge, jamais « on
suppose que ça va ».

La chaîne demande deux secrets GitHub, `CLEVER_TOKEN` et `CLEVER_SECRET`,
pris dans la session `clever login` du poste :

    sh outils/secrets-github.sh

Sans eux, le premier déploiement est rouge et le dit. **Ne pas les recopier
à la main depuis `clever-tools.json`** : cette notice le faisait en lisant
`['token']` à la racine du fichier, alors que clever-tools 4 range la
session dans une liste `profiles`. Le premier déploiement a été refusé
(« Your token is invalid », 30/09/2026). L'outil lit les deux formes, pose
les deux secrets ensemble et n'affiche aucune valeur (`banc-secrets`).
Ils expirent avec la session Clever : la reposer à ce moment-là.

### Le déploiement coupe-t-il le service ? OUI, et c'est voulu

**OUI : 20 à 30 secondes de coupure à chaque déploiement.** Ce paragraphe
disait le contraire — « pas de coupure attendue » — et il avait cessé d'être
vrai le 30/09/2026, quand `zero-downtime` a été mis à **`false`** sur l'app de
production. Vérifié, pas supposé :

    clever config get zero-downtime --app <APP_VIP de outils/clever.conf>
    → false

**Pourquoi on a choisi la coupure.** Le bleu/vert (`zero-downtime=true`, le
réglage par défaut) fait tourner l'ancienne et la nouvelle instance en même
temps pendant le recouvrement : **deux processus qui écrivent le même fichier
SQLite posé sur un disque réseau**, ce que SQLite ne peut pas tenir — le
verrouillage ne traverse pas le réseau. Ce n'est pas une inquiétude théorique :
c'est exactement la configuration qui, sur Ali Baba, a fait passer la base de
1 anomalie à 24 en une matinée de cinq déploiements, puis mis toute l'équipe
dehors le lendemain matin. RHI avait le même réglage, avec la même base sur le
même genre de bucket.

Donc **20 à 30 secondes de coupure contre un seul écrivain** : sur une base
posée sur un disque réseau, ce n'est pas un arbitrage, c'est la seule option
tenable. **NE PAS remettre `zero-downtime` à `true`.**

- La coupure ne fait rien perdre au terrain : un 503 laisse le geste dans la
  file de la tablette (`banc-file`), il repart au retour. C'est précisément ce
  pour quoi la file a été écrite.
- Si la nouvelle instance ne démarre pas, `outils/verifier-deploiement.sh` voit
  que le site ne sert pas CE commit et sort rouge.
- Ce qu'il reste à mesurer, et qui n'est qu'un chiffre : la durée réelle du 503
  au prochain déploiement. L'écrire ici à la place de « 20 à 30 secondes », qui
  est la valeur constatée sur Ali Baba, pas sur RHI.

### À la main, en secours

Si la chaîne est en panne (secrets expirés, GitHub indisponible) :

    . outils/clever.conf
    clever link "$APP_VIP" --org "$ORGA" --alias rhi
    clever deploy --alias rhi
    sh outils/verifier-deploiement.sh "$(git rev-parse HEAD)"

La vérification juge le site, pas le code de sortie : il doit servir CE
commit et se dire prêt. Elle échoue fermée : 503, JSON illisible, ancien
commit, pas de version, tout est rouge, avec le motif en tête.

## 0. En une commande (étapes 1 à 3)

Depuis un poste où `clever login` a été fait (ou avec `CLEVER_TOKEN` /
`CLEVER_SECRET` dans l'environnement) :

    sh outils/clever-installer.sh          # VIP Plus → application « rhi »
    sh outils/clever-installer.sh alfa     # Alfa     → application « rhi-alfa »

Il crée l'application dans GROUP ALMA, à Paris, une seule instance, le FS
Bucket relié et monté sur `donnees/`, les variables de base, et tire deux
codes d'accès au hasard — **affichés une seule fois : les noter**. Relançable
sans dégâts : il ne recrée rien et ne remplace jamais des codes déjà posés.
Il ne déploie pas (c'est le travail de la chaîne) et ne pose ni clé InterFast ni mot de
passe SMTP : ceux-là passent par la console, jamais par une ligne de
commande. Un banc (`banc-installer`) le joue contre un faux `clever`.

Les étapes 1 à 3 ci-dessous décrivent les mêmes gestes à la main.

## 1. Créer l'application

Console → organisation **GROUP ALMA** (pas l'espace personnel) → *Create* →
*an application* → **Python**.

- Nom : `rhi` · Région : **Paris** (le bucket doit être dans la même) ·
  Taille : `XS` · **1 instance minimum, 1 maximum**.
- **Ne pas** relier au dépôt GitHub : c'est la chaîne (Actions) qui déploie,
  après les bancs. Un lien GitHub de Clever déploierait sans eux.

## 2. Créer le FS Bucket

*Create* → *an add-on* → **FS Bucket**, même organisation, même région,
relié à l'application `rhi`. Noter son hôte
(`bucket-…-fsbucket.services.clever-cloud.com`).

## 3. Les variables d'environnement

| Variable | Valeur |
|---|---|
| `CC_RUN_COMMAND` | `uvicorn app:app --host 0.0.0.0 --port 9000` (le 8080 est au nginx de Clever) |
| `CC_PYTHON_VERSION` | `3.12` |
| `CC_FS_BUCKET` | `/donnees:bucket-…-fsbucket.services.clever-cloud.com` |
| `RHI_CODE_TERRAIN` | le code des tablettes et téléphones (à choisir) |
| `RHI_CODE_BUREAU` | le code du bureau : différent, **12 caractères au moins** |
| `RHI_COUT_HORAIRE` | le taux horaire moyen chargé, en €/h (en attendant les coûts par personne) |
| `RHI_MARCHE_A` | destinataires de la synthèse marche en avant (adresses séparées par des virgules) — l'envoi du lundi est éteint depuis la revue du 01/10 : la marche en avant part chez un agent à part |
| `RHI_PLANNINGS_URL` | liens de **téléchargement direct** des plannings ATE et POSE (séparés par des virgules ou des retours à la ligne) : RHI les relit tout seul ; vide = dépôt à la main |
| `RHI_PLANNINGS_MINUTES` | tous les combien RHI relit ces liens (5 par défaut) |
| `RHI_HEURES_JOUR` | la journée normale, du lundi au vendredi (`8,8,8,8,7` par défaut) : base des écarts du RHI |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | le serveur de courrier, mêmes noms que dans Ali Baba ; absent = rien ne part |
| `INTERFAST_VIP` | la clé InterFast de VIP Plus — **régénérée** dans InterFast avant la mise en production (l'ancienne a circulé en clair) |

`RHI_DONNEES` n'est pas à régler : `donnees/` est la valeur par défaut, et
c'est là que le bucket est monté.

## 4. Vérifier — un `git push` ne prouve rien

La chaîne vérifie toute seule après chaque déploiement. Pour regarder soi-même,
deux lectures.

Publique — elle ne dit que « prêt » ou non, pour ne rien apprendre à un
visiteur :

    curl -s https://<app>.cleverapps.io/api/sante
    {"ok": true, "heure": "…", "pret": true, "codes": "ok"}

Le détail, avec le code bureau :

    curl -s -H "X-RHI-Code: <code bureau>" https://<app>.cleverapps.io/api/sante/detail

```json
"base": {"dans_donnees": true, "journal": "delete", "inscriptible": true},
"cle_interfast": true,
"codes_acces": "ok"
```

- `pret: false` → lire le détail avant d'envoyer qui que ce soit.
- `dans_donnees: false` → la base est sur le disque éphémère : **arrêter
  tout**, corriger le bucket, redéployer. Rien de saisi avant n'est gardé.
- `codes: "à régler"` → l'application est **fermée** (503 « Accès fermé,
  réglage incomplet : … ») : les codes échouent fermés. Il manque un code, les
  deux sont identiques, ou le code bureau fait moins de 12 caractères. Le
  message dit lequel.

Dix codes faux en une minute depuis la même adresse bloquent cette adresse
une minute (429) : une tablette qui insiste avec un vieux code, après un
changement de code, s'arrête d'elle-même. Les refus sont dans
`clever logs` (« code … refusé depuis … »).

Puis `clever activity --app <id>` (le déploiement est-il OK ?) et
`clever logs --app <id> --since 5m`.

## 5. Premier lundi

1. Bureau → **Plannings** : déposer le planning ATE et le planning POSE SER.
2. Bureau → **Plannings** : *Relire les chantiers InterFast*, puis *Relire
   les montants vendus*.
3. Bureau → **Personnes** : *Relire les comptes InterFast* ; trancher les
   prénoms ambigus ; saisir les coûts horaires connus ; décocher ceux qui ne
   pointent pas (sous-traitants, libellés d'équipe).
4. Chaque tablette et chaque téléphone : ouvrir l'adresse, choisir
   *atelier* ou *pose*, entrer le code une fois. Sur la tablette, « Ajouter à
   l'écran d'accueil » : elle s'ouvre alors comme une application, même sans
   réseau.
5. L'écran du mur : ouvrir `/ecran` en plein écran (F11), code terrain.

## 6. La menuiserie (Alfa) : une deuxième application

Même code, **autre application** Clever Cloud (`rhi-alfa`), **autre FS
Bucket**, et deux variables qui changent :

| Variable | Valeur |
|---|---|
| `RHI_ENTREPRISE` | `ALFA` |
| `INTERFAST_ALFA` | la clé InterFast d'Alfa (à la place de `INTERFAST_VIP`) |

Codes d'accès propres à Alfa. Chaque instance refuse les plannings de
l'autre, et `/api/sante/detail` affiche `"entreprise"`.

## 7. Sauvegardes

- Automatique : une copie cohérente par jour dans `donnees/sauvegardes/`,
  gardée 30 jours. Elle protège d'une erreur (import raté, correction de
  masse), **pas** de la perte du bucket.
- À la main : Bureau → Plannings → *Télécharger toute la base* — à faire
  chaque semaine, après la validation des RHI, et à garder ailleurs.
- Restaurer : arrêter l'application, remplacer `donnees/rhi.db` par la copie
  (même nom), redémarrer.
