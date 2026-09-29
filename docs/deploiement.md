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

## L'application VIP Plus existe (29/09/2026)

| | |
|---|---|
| Application | `app_a5509cc0-71a5-49d4-b201-ca1941713f22` |
| Organisation | GROUP ALMA (`orga_b3f4776d-f719-4c57-afbb-628b175dff3a`) |
| Adresse par défaut | `https://app-a5509cc0-71a5-49d4-b201-ca1941713f22.cleverapps.io` |

Créée depuis la console, sans lien GitHub : rien ne se déploie tout seul. Le
29/09 au soir, l'adresse répondait 503 — normal, aucun code n'y était encore
poussé. Pour y relier un poste (et que `outils/clever-installer.sh` la
reconnaisse au lieu d'en créer une autre) :

    clever link app_a5509cc0-71a5-49d4-b201-ca1941713f22 --alias rhi

Déployer — **seulement quand Philippe dit « pousse »** :

    clever deploy --alias rhi
    clever activity --alias rhi        # OK ou FAIL : un push ne prouve rien
    curl -s https://app-a5509cc0-71a5-49d4-b201-ca1941713f22.cleverapps.io/api/sante

## 0. En une commande (étapes 1 à 3)

Depuis un poste où `clever login` a été fait (ou avec `CLEVER_TOKEN` /
`CLEVER_SECRET` dans l'environnement) :

    sh outils/clever-installer.sh          # VIP Plus → application « rhi »
    sh outils/clever-installer.sh alfa     # Alfa     → application « rhi-alfa »

Il crée l'application dans GROUP ALMA, à Paris, une seule instance, le FS
Bucket relié et monté sur `donnees/`, les variables de base, et tire deux
codes d'accès au hasard — **affichés une seule fois : les noter**. Relançable
sans dégâts : il ne recrée rien et ne remplace jamais des codes déjà posés.
Il ne déploie pas (on attend « pousse ») et ne pose ni clé InterFast ni mot de
passe SMTP : ceux-là passent par la console, jamais par une ligne de
commande. Un banc (`banc-installer`) le joue contre un faux `clever`.

Les étapes 1 à 3 ci-dessous décrivent les mêmes gestes à la main.

## 1. Créer l'application

Console → organisation **GROUP ALMA** (pas l'espace personnel) → *Create* →
*an application* → **Python**.

- Nom : `rhi` · Région : **Paris** (le bucket doit être dans la même) ·
  Taille : `XS` · **1 instance minimum, 1 maximum**.
- Relier au dépôt GitHub `philippecollins302-prog/RHI-`, branche **`prod`**.

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
| `RHI_MARCHE_A` | destinataires de la marche en avant du lundi 7 h (adresses séparées par des virgules) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | le serveur de courrier, mêmes noms que dans Ali Baba ; absent = rien ne part |
| `INTERFAST_VIP` | la clé InterFast de VIP Plus — **régénérée** dans InterFast avant la mise en production (l'ancienne a circulé en clair) |

`RHI_DONNEES` n'est pas à régler : `donnees/` est la valeur par défaut, et
c'est là que le bucket est monté.

## 4. Déployer, puis vérifier — un `git push` ne prouve rien

Le déploiement part à la poussée sur `prod` (règle du groupe : **on ne pousse
`prod` que quand Philippe dit « pousse »**). Ensuite, deux lectures.

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
