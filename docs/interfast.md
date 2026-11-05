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

**Depuis le 05/11/2026, RHI lit les comptes par l'API REST directe** :
`GET https://app.inter-fast.fr/v1/users?page=N&size=100`, clé dans l'en-tête
`X-API-KEY` (la même que celle du MCP ; mode éprouvé sur `/v1/orders`), page
par page jusqu'à une page incomplète, vide ou sans id nouveau, 20 pages au
plus, 20 s par page. La clé n'est ni dans l'adresse, ni dans un message.

Ce jour-là, des comptes créés le matin portaient des ids vers 31 869, les
anciens vers 23 722 : l'ancienne lecture balayait toute la plage entre les
deux (~8 000 lectures en série), le proxy coupait la requête (« ✗ » sans
message au bureau) et la lecture continuait côté serveur.

**Repli par le MCP**, seulement si la REST répond 401, 403, 404 ou un corps
illisible (un 429 ou un 5xx est dit tel quel : le repli n'y changerait rien).
Les comptes s'y lisent **un par un, en série** (`/v1/users/{id}`, 735
caractères). Les ids visibles dans la liste tronquée sont regroupés en
**grappes** (deux ids distants de plus de 24 sont dans deux lots différents) ;
chaque grappe est lue sur toute sa plage — la liste est triée par nom, des ids
« cachés » se trouvent entre les ids affichés — puis au-delà jusqu'à 12 absents
d'affilée. **300 lectures au plus pour tout le balayage** : au-delà, RHI
s'arrête et le dit. Chaque réponse est vérifiée (l'id rendu doit être l'id
demandé) et les 401/429/5xx sont retentés. Le MCP prend la clé dans son
adresse : httpx la journaliserait, elle est masquée (`***`).

La route `POST /api/interfast/utilisateurs` s'arrête à 90 s (504, avec la
raison), sous la coupure du proxy. `banc-comptes-interfast` tient tout cela.

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

- une **case par CH, par jour et par groupe d'heures identiques**
  (`base.envois`, décision de Serge, 05/11/2026) : ceux qui ont exactement
  le même temps travaillé ce jour-là sur ce CH partagent une case ; celui
  qui a 30 min de plus a la sienne. Heure de la case : le premier début du
  groupe ; durée : le temps travaillé (pauses du midi exclues) — 8:00 + 8 h
  → case 8:00–16:00 : le total et le coût sont justes, l'heure de fin est
  théorique (accepté). Titre « RHI · CH… · pointage » s'il n'y a qu'un
  groupe ce jour-là, « RHI · CH… · pointage · JD PM » (initiales du groupe)
  s'il y en a plusieurs ; l'anti-doublon cherche ce titre exact, groupe par
  groupe. Pourquoi : à la clôture, InterFast donne à CHAQUE technicien le
  créneau planifié de la case (voir plus bas) ; seuls ceux qui ont le même
  temps peuvent donc la partager. Une case posée avant les groupes garde
  toute l'équipe du jour (groupe vide en base) ;
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
  **Un seul envoi à la fois** : un second clic, ou un autre poste, reçoit un
  409. Un refus (« ❌ ») à la planification s'arrête avant la confirmation.
  **Depuis le 05/11/2026, le MCP exige un `action_id`** : le récapitulatif
  de `planifier_intervention` le donne (« appelez **confirmer_action** avec
  confirmation=true et action_id="…" »), `confirmer_action` le demande
  (`{"confirmation": bool, "action_id": str}`, les deux requis) et l'action
  **expire au bout de 10 minutes**. RHI le lit dans le récapitulatif ;
  absent (ou deux jetons différents), rien n'est confirmé et la case reste
  prête. C'est ce qui faisait échouer l'essai sur CH00066 ce jour-là.
  Chaque étape est journalisée (`rhi.interfast` : CH, jour, « action_id
  trouvé/absent », « référence IN… », « réponse sans référence », « refus »),
  sans la clé ni le client ni les techniciens (`banc-confirmer`).
  **La référence rendue a changé le même jour** : `confirmer_action` répond
  « ✅ **Intervention planifiée avec succès** **Référence:** 410 … », un
  simple numéro, plus « IN00410 ». RHI lit les deux (gras, espaces et
  deux-points variables) et garde `IN{n:05d}`, le format de `reference_de()`.
  Un « ✅ … avec succès » sans numéro reste « à vérifier ». Faute de le lire,
  l'essai CH00066 est passé « à vérifier », le bureau l'a renvoyé, et
  InterFast a reçu **deux** interventions identiques (409 et 410).
  **Anti-doublon, avant toute création** (premier envoi comme « la
  renvoyer ») : RHI cherche la case dans InterFast, **par l'API REST
  d'abord** — `GET /v1/events` (clé dans l'en-tête `X-API-KEY`, comme pour
  les comptes ; `start`, `end`, `page`, `count`, `archived=false` et
  `meeting=false` requis), filtrée sur le jour de la case (±1 jour, pour
  les fuseaux) et sur son chantier (`worksites` = l'id InterFast du
  chantier, celui que rend `rechercher_chantiers`), 50 par page, 10 pages
  au plus, 20 s par page. Réponse relevée le 05/11/2026 : `{"count":
  total, "items": [{"id", "title", "reference": "IN00410", "start",
  "worksite": {"id", "title"}, "users", …}]}`. **Repli** sur
  `consulter_planning` (technicien = le premier de la case) seulement si
  la REST répond 401, 403, 404 ou illisible ; un 429 ou un 5xx s'arrête là.
  RHI ne garde que les interventions dont le titre est exactement la
  description posée par RHI (« RHI · CH… · … ») et qui commencent, à Paris,
  le jour de la case. Une trouvée : rien n'est créé, sa référence (lue dans
  la REST, sinon par `reference_de`) et son id sont repris et la case est
  posée (journal : « case existante reprise »). Plusieurs : rien n'est
  créé, la case est « à vérifier » avec leurs références, pour supprimer
  les doublons dans InterFast. Aucune : création comme avant. **Recherche
  impossible** (réseau, réponse coupée ou illisible, aucun technicien) :
  rien n'est créé, la case reste prête — on échoue fermé.
  `consulter_planning` reçoit la **date** de la case et pas la semaine ISO :
  relevé le 05/11/2026, « 2027-W01 » y rend la semaine du 28/12 au 03/01,
  alors que « 2027-01-05 » rend bien le lundi 4 au dimanche 10. Une semaine
  vide y répond par une phrase (« Aucun événement planifié sur cette
  période. »), pas par du JSON (`banc-doublon`).
  **Les références d'intervention ne sont PAS uniques** (05/11/2026 :
  IN00410 est notre case CH00066 du 27/10 ET une visite de maintenance de
  2022 dans un lycée — `GET /v1/events?name=IN00410` rend les deux). RHI
  garde donc **l'id interne** de l'intervention à côté de la référence
  (`cases_interfast.num`) dès la pose ou la reprise, et toute relecture
  (heures, état) part de lui. Une case posée sans son id (l'essai
  CH00066) le retrouve à la relecture suivante par jour + chantier + titre
  (la référence départage deux cases RHI du même CH) ; sinon, comme avant,
  par les heures du jour de ses techniciens. « Elle existe : c'est cette
  référence » cherche la référence (`name=`) et retient l'intervention du
  jour et du chantier de la case ; aucune ou plusieurs : refus (409) avec
  la liste des interventions de cette référence. InterFast injoignable :
  503, rien n'est tranché. La relecture met la case à jour par (CH, jour),
  plus par sa référence.
  Une fois la confirmation partie, **tout ce qui n'est pas « IN… créée »
  est incertain** : pas de référence, « Aucune action » (un 502 rejoué
  après création répond ainsi), un délai dépassé. La case est alors
  marquée « À VÉRIFIER » et ne se renvoie pas. Le bureau regarde dans
  InterFast et tranche : « elle existe », avec sa référence IN…, ou « elle
  n'existe pas », et elle redevient prête. Répond 403 tant que
  `ECRITURE = False` ;
- une personne validée **après** la pose rend la case « à compléter » : on
  l'ajoute à la main dans InterFast, puis « C'est fait : ajoutés dans
  InterFast » rattache ses pointages à la case ;
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

Reste l'essai sur une affaire de test avant `ECRITURE = True`.

**Le mode essai** (30/09/2026) : sans toucher à l'interrupteur, l'écriture
est ouverte sur **l'affaire de test seulement** — CH00066 pour VIP Plus,
choisie par Alexis, réglable par `RHI_ECRITURE_ESSAI` (CH séparés par des
virgules ; vide = aucun). Toute autre case reste à blanc : le serveur la
refuse « hors essai », et `poser_case` refuse encore derrière lui. L'essai
se fait donc **en production, depuis le bureau**, par Alexis, sans poste de
dev ni clé à manipuler. Tenu par `banc-couts`.

**Déroulé de l'essai** (une seule case, un jour calme) :

1. Dans InterFast, vérifier que CH00066 a un client, et relier dans RHI
   (onglet *Personnes*) les deux techniciens de l'essai à leur compte.
2. Au bureau, saisir pour eux un pointage sur CH00066 (*À vérifier* →
   « Ajouter un pointage oublié »), contrôler le CH (*Mes chantiers*), puis
   valider leurs deux semaines.
3. *Vers InterFast* → **Essai : poser cette case dans InterFast**, sur la
   case de CH00066 — la seule qui porte ce bouton.
4. Vérifier dans le planning InterFast la date, l'heure, la durée, les deux
   techniciens et le chantier.
5. Terminer la case dans InterFast en recopiant les heures affichées par RHI,
   en en faussant exprès une de 30 min. Puis valider les feuilles de temps.
6. **Relire les heures reçues par InterFast** : RHI doit montrer la case
   « écart » sur le bon technicien.
7. Regarder la marge réelle du chantier dans InterFast : a-t-elle bougé ? Si
   non, le coût horaire de ces techniciens est sans doute à 0 €.
8. Consigner ici ce qui a été vu. Si tout est juste : `ECRITURE = True`
   (une ligne dans `rhi/interfast.py`), et toutes les affaires peuvent partir.

Trois choses à y vérifier :

1. la case se crée sur le bon chantier, avec son groupe ;
2. elle se termine avec les heures de chacun (RHI la termine lui-même) ;
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

Conséquence pour le chemin A (29/09/2026) : RHI pouvait **poser les cases**,
mais « terminer » et « valider » restaient des clics dans InterFast.

### Terminer : la route existe (relevé du 05/11/2026)

Le bouton « Terminer » de l'application web InterFast (intervention de test
IN00416, id 2099387, CH00122) envoie **`PUT
https://app.inter-fast.fr/v1/intervention/{id}/finished`**, et rien d'autre.
Sonde avec la clé API le même jour (intervention de test IN00417, id
2099608, CH00122, à supprimer à la main) :

- **corps vide, en-tête `X-API-KEY`** : 200. Après :
  `finished=true`, `lifecycleState="completed"`, `finishDate` et
  `finishedBy` renseignés (`GET /v1/intervention/{id}`) ;
- **un second appel** répond 200 sans rien changer (`finishDate` inchangée) :
  réessayer est sans danger ;
- **aucune heure n'est saisie** à la clôture : avant, `GET
  /v1/interventions/{id}/timesheets` rend `[]` ; après, il rend, pour
  **chaque technicien**, le créneau planifié de la case (`startHour`,
  `endHour`, `breakTime` 0, `totalWorkedTime` = durée) ;
- les heures valorisées dans la marge du chantier sont celles des
  interventions **terminées** (CH00066 : 2 × 2 h × 38 € = 152,00 €).

D'où le **découpage par groupe d'heures identiques** (plus haut) et la
**clôture automatique** (décision de Serge) : juste après une pose réussie,
référence ET id connus, RHI appelle `PUT /finished` sur l'id, puis relit
l'intervention ; `finished=true` → la case est « terminée », et ses heures
reçues sont relues aussitôt (chacun le créneau de sa case : pas d'écart
fantôme). Échec de la clôture → la case reste « posée », avec le bouton
**« Terminer dans InterFast »** pour réessayer
(`POST /api/interfast/cases/terminer`). Une case **reprise** par
l'anti-doublon et pas encore terminée est terminée de la même façon ; déjà
terminée dans InterFast, elle est marquée sans second appel. **Jamais de
clôture sans id certain** (pose sans id retrouvé : pas de bouton, 409 ; la
relecture retrouvera l'id), ni hors de l'écriture permise (l'essai).
Journal de chaque étape (`rhi.interfast` : « terminer CH… id … :
terminée / refus HTTP … / sans réponse »), sans la clé.
`banc-cases-terminees` tient le tout.

Reste un clic dans InterFast : **valider la feuille de temps** de chacun
(Équipe → la fiche → Feuilles de temps).

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
