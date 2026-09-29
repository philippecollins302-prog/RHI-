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

Question à poser au support InterFast : *« Existe-t-il un moyen, par l'API ou
le MCP, d'enregistrer du temps passé (timesheet) sur un chantier ou une
intervention ? »*

## Sécurité

La clé donne accès à tout le compte (clients, devis, factures) et le MCP sait
écrire (devis, clients, interventions). Elle ne va que dans l'environnement
Clever Cloud (`INTERFAST_VIP`), jamais dans ce dépôt public. Elle a circulé
en clair dans une conversation le 29/09/2026 : la régénérer dans InterFast
au moment de la mise en production est une précaution raisonnable.
