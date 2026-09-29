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
| `RHI_CODE_BUREAU` | le code du bureau (à choisir, différent) |
| `RHI_COUT_HORAIRE` | le taux horaire moyen chargé, en €/h (en attendant les coûts par personne) |
| `INTERFAST_VIP` | la clé InterFast de VIP Plus — **régénérée** dans InterFast avant la mise en production (l'ancienne a circulé en clair) |

`RHI_DONNEES` n'est pas à régler : `donnees/` est la valeur par défaut, et
c'est là que le bucket est monté.

## 4. Déployer, puis vérifier — un `git push` ne prouve rien

Le déploiement part à la poussée sur `prod` (règle du groupe : **on ne pousse
`prod` que quand Philippe dit « pousse »**). Ensuite, ouvrir
`https://<app>.cleverapps.io/api/sante` et lire :

```json
"base": {"dans_donnees": true, "journal": "delete", "inscriptible": true},
"cle_interfast": true,
"codes_acces": true
```

- `dans_donnees: false` → la base est sur le disque éphémère : **arrêter
  tout**, corriger le bucket, redéployer. Rien de saisi avant n'est gardé.
- `codes_acces: false` → l'application est ouverte à tous : poser les deux
  codes avant d'y envoyer qui que ce soit.

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
l'autre, et `/api/sante` affiche `"entreprise"`.

## 7. Sauvegardes

- Automatique : une copie cohérente par jour dans `donnees/sauvegardes/`,
  gardée 30 jours. Elle protège d'une erreur (import raté, correction de
  masse), **pas** de la perte du bucket.
- À la main : Bureau → Plannings → *Télécharger toute la base* — à faire
  chaque semaine, après la validation des RHI, et à garder ailleurs.
- Restaurer : arrêter l'application, remplacer `donnees/rhi.db` par la copie
  (même nom), redémarrer.
