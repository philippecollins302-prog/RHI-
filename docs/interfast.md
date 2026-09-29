# InterFast — ce que la clé a appris, et la décision qui reste

*Exploration en lecture seule du MCP InterFast avec la clé VIP Plus, le
29/09/2026. Rien n'a été écrit dans InterFast.*

## Ce qui est acquis

**Les CH sont les chantiers d'InterFast.** L'outil `rechercher_chantiers`
rend chaque chantier avec sa référence (`Réf: CH00xxx`), son titre, son
client, son statut (En cours / Non démarré / Terminé) et ses dates : 348
chantiers ce jour-là. **Les 36 CH trouvés dans les plannings d'Alexis
existent tous dans InterFast** — le CH est bien la clé commune. RHI les relit
désormais (bureau → Plannings → « Relire les chantiers InterFast ») : la
tablette affiche le client, cherche aussi dans le titre InterFast, et ne
propose plus un chantier terminé.

Réserve : les statuts ne sont pas tenus à jour partout (un chantier en pleine
fabrication peut être « Non démarré »). C'est pourquoi le planning du jour
reste toujours proposé, quel que soit le statut InterFast.

**Les ouvriers existent dans InterFast**, comme utilisateurs *technicien* de
l'agence « Serrurerie » (et « Grand compte » pour certains). Deux constats :
- aucun ne s'est jamais connecté ;
- leur **coût horaire est à 0 €** : tant qu'il n'est pas renseigné, InterFast
  ne peut chiffrer aucune rentabilité, quelle que soit la façon dont les
  heures y tombent.

**Les limites du MCP, apprises en lisant les comptes** :
- toute réponse est **coupée vers 4 000 caractères** (« … (tronqué) ») ;
- `appeler_api` **ne transmet aucun paramètre** de requête (`page`, `size`,
  `name` sont ignorés) : la liste `/v1/users` s'arrête donc au 7e compte ;
- sous des appels **en parallèle**, il rend des 404 pour des comptes qui
  existent (réponses mélangées), et parfois des 401 passagers.

RHI lit donc les comptes **un par un, en série** (`/v1/users/{id}`, 735
caractères), sur toute la plage d'ids visibles puis au-delà jusqu'à 12 absents
d'affilée — la liste est triée par nom, les ids « cachés » se trouvent entre
les ids affichés. Une minute pour 47 comptes. Chaque réponse est vérifiée
(l'id rendu doit être l'id demandé) et les 401/429/5xx sont retentés.

Ce que la relecture a montré le 29/09/2026 : 5 personnes des plannings reliées
d'office, 1 prénom porté par deux comptes (le bureau tranche dans l'onglet
Personnes), **3 opérateurs du planning atelier archivés dans InterFast**, et
**9 noms des plannings sans aucun compte** (dont des intérimaires et des
libellés d'équipe). Liste nominative : onglet Personnes, pas ce dépôt public.

**Le vendu par CH** : l'API ne relie pas un devis à un chantier, mais les
devis importés d'Optima portent le CH dans leur titre (« Import Optima -
CH00045 »). RHI additionne les devis *signés* ou *payés* dont le titre porte
le CH. Le 29/09/2026 : 13 des 33 CH des plannings ont au moins un devis ainsi
titré, 9 un devis signé. Les autres affichent « — », jamais 0 € : **pour
chiffrer toutes les affaires, il faut que le CH figure dans le titre du
devis** (ou qu'InterFast expose le lien devis → chantier).

## Ce que l'API ne permet pas

**Aucune écriture d'heures.** Les feuilles de temps (*timesheets*) existent,
mais seulement **en lecture** et **attachées à une intervention** :

- `GET /v1/interventions/{id}/timesheets` (et `/aggregated`)
- `GET /v1/users/{userId}/timesheets/{année}/{mois}/{jour}/interventions`

Elles sont remplies par l'application mobile InterFast des techniciens
(démarrer / arrêter sur une intervention). L'API générique (`appeler_api`)
n'expose aucun POST de temps.

Forme relevée le 29/09/2026, sur une intervention terminée :

```
{"startHour": "2026-09-28T06:30:00.000Z", "endHour": "2026-09-28T08:15:00.000Z",
 "breakTime": 0, "totalWorkedTime": 105, "user": "23709"}
```

Les heures sont en UTC et les durées en minutes. La version par jour
ajoute `cost` (73,5 € pour 105 min : ce technicien-là a un coût horaire,
42 €/h), `interventionId` et l'intervention entière. Aucun champ ne dit si
la feuille de temps est validée.

## Les trois chemins possibles — à décider

| | Chemin | Pour | Contre |
|---|---|---|---|
| **A** | RHI pointe ; chaque jour (ou chaque semaine, après validation du bureau), RHI **crée une intervention** sur le chantier via `planifier_intervention` : client, chantier, date, heure de début, durée réelle, technicien, description (« Fab garde-corps »). | Les heures tombent sur l'affaire, visibles dans InterFast, sans rien changer pour les gars. | Ce sont des interventions *planifiées*, pas des temps pointés : il faut vérifier que le point d'affaire InterFast les compte. Le planning InterFast se remplit de lignes « passées ». Chaque écriture exige une confirmation (automatisable, comme dans Ali Baba). |
| **B** | Les gars pointent **dans l'appli InterFast** elle-même, sur des interventions créées à l'avance. | Les vraies *timesheets* InterFast, sans double outil. | Une intervention à créer par tâche et par personne ; l'appli est pensée pour un technicien avec son téléphone, pas pour une tablette partagée à l'atelier ; contraire au « hyper simple » demandé. |
| **C** | RHI reste la source des heures ; le **point d'affaire se fait dans RHI** (réel face au prévu, par CH), InterFast fournit les CH, les montants vendus (devis) et les coûts. Export Excel pour la compta. | Aucun risque d'écriture ; disponible tout de suite. | Les heures ne sont pas dans InterFast : deux endroits à regarder. |

**Recommandation** : démarrer en **C** (c'est ce que fait déjà la V1), et
essayer **A sur une affaire de test** avec une personne d'InterFast ou dans
leur documentation, pour savoir si une intervention planifiée compte dans le
point d'affaire InterFast. Si oui, brancher A en fin de semaine, après la
validation du RHI par le bureau : une écriture par personne, par CH et par
jour, avec la référence gardée dans `pointages.interfast` pour ne jamais
envoyer deux fois.

**En place (29/09/2026), écriture toujours coupée** — bureau → *Vers
InterFast* :

- une **case par CH et par jour**, avec toute l'équipe qui a pointé ce CH ce
  jour-là (`base.envois`) : de la première arrivée au dernier départ,
  techniciens par leur nom InterFast ;
- sous chaque case, **ce qu'il faudra saisir en la terminant** dans
  InterFast, par technicien : début, fin, pause (qui comprend le temps passé
  sur un autre CH entre deux morceaux) ;
- une case n'est **prête** que si tous ceux qui l'ont pointée ont leur RHI
  **validé**. Elle est **bloquée** dans quatre cas : CH inconnu d'InterFast,
  chantier sans client, aucun technicien relié, ou un pointage de plus de
  12 h / à cheval sur deux jours. Un technicien sans compte ne bloque pas :
  il est nommé, pour être ajouté à la main ;
- **Poser** (`POST /api/interfast/envois`) : `planifier_intervention` puis
  `confirmer_action`, une case à la fois. La référence IN… est gardée sur la
  case (`cases_interfast`) et sur chaque pointage, donc jamais deux envois.
  Un refus (« ❌ ») s'arrête avant la confirmation. Une confirmation sans
  référence est marquée « À VÉRIFIER » et n'est pas renvoyée. Répond 403 tant
  que `ECRITURE = False` ;
- **Relire** (`POST /api/interfast/suivi`), en lecture seule : ce que
  chaque case posée a **reçu à sa clôture**, technicien par technicien, face
  au RHI. Un écart de plus de 15 min est signalé : c'est une saisie à
  reprendre dans InterFast. La case se retrouve par les heures du jour de ses
  techniciens, qui donnent l'id interne de chaque intervention (1819630),
  traduit en IN… par `/v1/intervention/{id}`. L'id est ensuite gardé
  (`cases_interfast.num`), et les relectures suivantes vont droit à
  `/v1/interventions/{id}/timesheets`. Limite : la coupure du MCP ne laisse
  lire que les **deux premières** interventions d'une journée. Une case
  introuvable dans une journée coupée est dite « illisible », pas « à
  terminer » ;
- une semaine dont une case est posée **ne se dévalide plus** (409) : une
  correction faite ensuite n'arriverait jamais dans InterFast. On corrige
  d'abord la case dans InterFast.

Reste l'essai sur une affaire de test, avec Philippe, avant `ECRITURE = True`.
Trois choses à y vérifier :

1. la case se crée sur le bon chantier, avec toute l'équipe ;
2. elle se termine avec les heures de chacun ;
3. après validation de la feuille de temps, la marge réelle du chantier
   bouge.

### Comment InterFast le fait « en classique » (centre d'aide, 29/09/2026)

Décision de Philippe : les heures arrivent **comme des cases dans le planning,
qu'on valide ensuite**. Selon le centre d'aide InterFast, le chemin
habituel est le suivant :

1. **Le bureau planifie** une intervention sur le chantier : c'est la case
   dans le planning (« Planifier une intervention »). Elle peut porter
   plusieurs techniciens.
2. **Le technicien la termine** dans l'appli mobile (« Terminer
   l'intervention »). Il saisit son heure de début, son heure de fin et sa
   pause (« Date et heures pour [Technicien] ») et signe le rapport. Sur
   l'app web, il faut « Générer le rapport ». Une intervention terminée
   porte un ✅ dans le planning.
3. Ces heures deviennent une **feuille de temps**. Elle apparaît **en
   orange** tant qu'elle n'est pas validée (Équipe → Voir la fiche →
   Feuilles de temps) : le bureau clique dessus puis sur « **Valider** » ou
   « Refuser ».
4. Les heures validées, multipliées par le **coût horaire** de la fiche
   (Feuilles de temps → coût horaire), alimentent la **marge réelle** du
   chantier. Tant que ce coût est à 0 € (c'est le cas au 29/09), la marge
   réelle ne voit pas la main-d'œuvre.

Ce que l'API permet, vérifié avec `explorer_api` le 29/09/2026 :

- **l'étape 1 seulement.** On peut créer la case avec
  `planifier_intervention` (plusieurs techniciens, date, heure, durée) puis
  `confirmer_action`, et la déplacer tant qu'elle n'est pas terminée avec
  `replanifier_intervention`.
- **Pas les étapes 2 et 3.** Aucun endpoint ne permet de terminer une
  intervention, d'écrire une feuille de temps ou de la valider : tous les
  chemins `timesheets` sont en GET, et une recherche sur `finish` ou
  `status` ne renvoie rien d'utile (`/v1/processing-statuses` est vide).

Conséquence pour le chemin A : RHI peut **poser les cases** d'une semaine
validée, avec les bonnes heures, sur le bon CH et avec les bons
techniciens. Mais **« terminer » et « valider » restent des clics dans
InterFast** : le technicien termine, ou le bureau depuis l'app web, puis le
bureau valide la feuille de temps. Pour que ces clics restent peu nombreux,
mieux vaut **une case par CH et par jour, avec toute l'équipe dessus**,
plutôt qu'une case par personne : le rapport d'intervention porte déjà les
heures de chaque technicien séparément. À confirmer sur une affaire de
test : une case planifiée mais non terminée ne compte **pas** dans la marge
réelle, puisque seules les feuilles de temps y entrent.

Sources : [Suivre les heures et la rentabilité d'un chantier](https://help.inter-fast.co/fr/articles/11654458-suivre-les-heures-et-la-rentabilite-d-un-chantier),
[Remplir un rapport d'intervention (App Web)](https://help.inter-fast.co/fr/articles/12890091-remplir-modifier-un-rapport-d-intervention-app-web),
[Gérer un chantier](https://help.inter-fast.co/fr/articles/13223632-guide-complet-gerer-un-chantier-dans-interfast),
[Feuilles de temps – suivi des heures](https://aide.inter-fast.fr/fr/article/feuilles-de-temps-suivi-des-heures-atwpd6/).

Question à poser au support InterFast : *« Existe-t-il un moyen, par l'API ou
le MCP, d'enregistrer du temps passé (timesheet) sur un chantier ou une
intervention ? »*

## Sécurité

La clé donne accès à tout le compte (clients, devis, factures) et le MCP sait
écrire (devis, clients, interventions). Elle ne va que dans l'environnement
Clever Cloud (`INTERFAST_VIP`), jamais dans ce dépôt public. Elle a circulé
en clair dans une conversation le 29/09/2026 : la régénérer dans InterFast
au moment de la mise en production est une précaution raisonnable.
