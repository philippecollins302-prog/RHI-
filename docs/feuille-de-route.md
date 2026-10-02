# Feuille de route

Ordre proposé ; chaque étape a son banc avant d'être livrée.

## V1 — pointage serrurerie (fait, 29/09/2026)
Tablette atelier, téléphone pose (chef + binôme), RHI hebdomadaire par
personne, export Excel, corrections au bureau, point d'affaire réel face au
prévu du plan de charge, import des plannings ATE et POSE SER.

## V1.1 — mise en service
- Procédure écrite : `docs/deploiement.md` (application GROUP ALMA, FS
  Bucket, variables, vérification par `/api/sante`), et en une commande :
  `sh outils/clever-installer.sh`. Reste une session `clever login`, les clés
  dans la console, et les deux secrets GitHub de la chaîne (`main` déploie seule).
- ~~Revue de sécurité avant Internet~~ — faite le 29/09/2026 : codes qui
  échouent fermés, frein aux codes faux, CSV sans formule, fichiers monstres
  refusés, santé publique muette, semaine validée non rouverte par un geste
  rejoué (`banc-securite`).
- ~~Sauvegarde~~ — faite : une copie par jour gardée 30 jours, et le
  téléchargement de la base au bureau.
- ~~Journal SQLite compatible avec le bucket réseau~~ — `delete`, pas `wal`.
- Réponses d'Alexis (`docs/questions-alexis.md`, 30/09/2026) :
  ~~motifs sur le CH des frais généraux, trajet dans le chantier~~ (fait) ;
  ~~CH DIVERS, ajout d'intérimaires~~ (fait, reste à créer le CH DIVERS dans
  InterFast) ; ~~validation par chargé d'affaires puis par le responsable
  de BU~~ (fait, `banc-controles`) ; ~~le reste à faire estimé au point
  d'affaire~~ (fait, `banc-reste`) ; ~~pliage, débit, plasma toujours sur
  un CH~~ (déjà ainsi : sans CH, seuls les quatre motifs sont admis) ;
  ~~transfert des heures du CH DIVERS~~ (une correction du CH depuis
  « À vérifier », tracée, qui rouvre le contrôle du chargé).

## V1.2 — InterFast
1. ~~Trouver les outils avec la vraie clé~~ — fait le 29/09/2026, voir
   `docs/interfast.md`.
2. ~~Liste des CH lue dans InterFast~~ — fait (lecture seule).
3. ~~Décider le chemin des heures~~ — des cases dans le planning InterFast,
   terminées puis validées là-bas (29/09/2026). Écrit et tenu par un banc :
   pose, relecture des heures reçues à la clôture (écarts au RHI), verrou
   de dévalidation. Reste l'essai sur une
   affaire de test avant `ECRITURE = True`.
4. Relier chaque personne de RHI à son utilisateur InterFast (id).
5. ~~Montant vendu par CH et coût horaire~~ — fait : vendu HT lu dans les
   devis signés/payés dont le titre porte le CH (9 CH sur 33 le 29/09/2026 :
   la plupart des devis ne portent pas leur CH — à faire corriger à la
   saisie), coût horaire par personne, part de main-d'œuvre dans le vendu.

## V1.3 — la revue du 01/10/2026 (fait, 02/10/2026)
Première revue de l'app par la direction de VIP Plus et le responsable de BU.
Ce qui a été demandé, et ce qui en a été fait :

- **La pause du matin est payée** : on ne l'arrête pas. Seuls la coupure du
  midi et le soir passent par « J'arrête » (manuel et écrans).
- **Les plannings se mettent à jour tout seuls** : RHI relit toutes les 5 min
  les liens de `RHI_PLANNINGS_URL` (`rhi/depot_auto.py`, `banc-depot-auto`).
  Un fichier inchangé n'est pas relu ; un lien qui renvoie une page web au
  lieu du fichier est signalé avec son remède. Le lien n'est jamais stocké
  ni affiché. **Reste** : poser les liens de téléchargement direct des deux
  plannings sur Clever — il faut savoir où vivent les Excel (OneDrive,
  SharePoint, Drive).
- **La grille du responsable de BU** : RHI de la semaine montre toutes les
  personnes × tous les jours, quel que soit le chantier, face à la journée
  normale (`RHI_HEURES_JOUR`, 8-8-8-8-7) ; heures sup en ambre, jour vide en
  rouge, écart de la semaine (`base.controle_semaine`, `banc-semaine`).
- **Point d'affaire retiré** du bureau : il se lit dans InterFast, où les
  heures tombent sur les comptes des chantiers. L'API reste, sans écran.
- **Marche en avant retirée** du bureau : elle part chez un agent à part.
  L'envoi du lundi est éteint pour de bon (plus de tâche de fond).
- **Vers InterFast** : dit clairement que les heures vont sur les comptes
  des chantiers ; la case de planning n'est que la porte d'entrée.
- **Intérimaires** : les RH les ajoutent dans Personnes (déjà là, dit au manuel).
- **« En ce moment »** devient **« Qui pointe maintenant »**, avec une phrase
  qui dit à quoi il sert.
- **L'écran du mur = le planning de la semaine, comme l'Excel** : une ligne
  par gars (atelier) ou par équipe (pose), une colonne par jour, chantier, CH,
  conducteur et **les couleurs de l'Excel** (lues dans le fichier, thème et
  teintes compris : `lecture.couleur`).
- **Pose** : l'équipe par défaut, mais le chef peut partir seul ou ajouter
  quelqu'un d'une autre équipe (atelier, intérimaire, binôme d'une autre équipe).
- **Trajet** : du dépôt, on pointe en partant ; de chez soi, en arrivant sur
  le chantier.
- **Téléphones perso facultatifs** : le pointage qui fait foi est sur le
  téléphone de l'entreprise.
- **Essai** : sur l'affaire de test CH00066, avec les poseurs d'abord.

## V2 — menuiserie (Alfa)
- ~~Lecteurs des plannings MEN~~ — faits (atelier : noms en colonne B ;
  pose : onglet par année, équipes séparées par un retour à la ligne).
- ~~Une instance par entreprise~~ — `RHI_ENTREPRISE=ALFA`, clé
  `INTERFAST_ALFA` (docs/deploiement.md §6).
- Reste : la clé InterFast d'Alfa pour relire ses chantiers et ses comptes ;
  le CH n'arrive que depuis peu dans ses plannings (102 cases sur 776 à
  l'atelier, 187 sur 1 717 en pose le 29/09/2026) — le reste se pointe par
  la recherche sur la tablette.

## Plus tard
- ~~Écran d'atelier qui fait défiler atelier / pose / traitement~~ — fait
  (`/ecran`), devenu le planning de la semaine le 02/10/2026.
- **Vu à la revue du 01/10, pour plus tard** : contrôle GPS du lieu de
  pointage ; un assistant qui signale les heures anormales (oubli d'arrêt,
  semaine trop courte ou trop longue) avant le lundi ; un lien avec Silae
  pour la paie. Rien de commencé : chacun demande d'abord une décision
  (données personnelles pour le GPS, accès Silae).
- ~~Analyse de la marche en avant BET → fab → pose~~ — faite, puis retirée
  du bureau à la revue du 01/10 (elle part chez un agent à part), en code et avec bancs : une date de fabrication future
  n'est jamais « réalisée », et le traitement de surface est dans la chaîne.
  L'envoi automatique du lundi 7 h est écrit et tenu par un banc, mais
  **volontairement éteint** (décision de Philippe, 30/09/2026) : Ali Baba
  n'a en réalité aucun réglage SMTP à recopier — cette ligne annonçait
  l'inverse —, et une boîte d'envoi se crée au nom d'une personne. La
  synthèse reste accessible par l'API (`/api/marche`). `RHI_MARCHE_A` est réglé ; pour allumer l'envoi, il suffira
  de `SMTP_HOST`, `SMTP_PORT` (587, STARTTLS), `SMTP_USER`, `SMTP_PASS` et
  `MAIL_FROM` sur Clever, puis du geste « etat » de la télécommande.
