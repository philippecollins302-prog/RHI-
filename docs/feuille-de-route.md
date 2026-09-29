# Feuille de route

Ordre proposé ; chaque étape a son banc avant d'être livrée.

## V1 — pointage serrurerie (fait, 29/09/2026)
Tablette atelier, téléphone pose (chef + binôme), RHI hebdomadaire par
personne, export Excel, corrections au bureau, point d'affaire réel face au
prévu du plan de charge, import des plannings ATE et POSE SER.

## V1.1 — mise en service
- Procédure écrite : `docs/deploiement.md` (application GROUP ALMA, FS
  Bucket, variables, vérification par `/api/sante`). Reste les gestes dans la
  console Clever Cloud, et le « pousse » de Philippe pour la branche `prod`.
- ~~Sauvegarde~~ — faite : une copie par jour gardée 30 jours, et le
  téléchargement de la base au bureau.
- ~~Journal SQLite compatible avec le bucket réseau~~ — `delete`, pas `wal`.
- Réponses d'Alexis (`docs/questions-alexis.md`) à intégrer.

## V1.2 — InterFast
1. ~~Trouver les outils avec la vraie clé~~ — fait le 29/09/2026, voir
   `docs/interfast.md`.
2. ~~Liste des CH lue dans InterFast~~ — fait (lecture seule).
3. ~~Décider le chemin des heures~~ — des cases dans le planning InterFast,
   terminées puis validées là-bas (29/09/2026). Écrit et tenu par un banc :
   pose, relecture des ✅, verrou de dévalidation. Reste l'essai sur une
   affaire de test avant `ECRITURE = True`.
4. Relier chaque personne de RHI à son utilisateur InterFast (id).
5. ~~Montant vendu par CH et coût horaire~~ — fait : vendu HT lu dans les
   devis signés/payés dont le titre porte le CH (9 CH sur 33 le 29/09/2026 :
   la plupart des devis ne portent pas leur CH — à faire corriger à la
   saisie), coût horaire par personne, part de main-d'œuvre dans le vendu.

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
- ~~Écran d'atelier qui fait défiler atelier / pose~~ — fait (`/ecran`).
  Reste le planning TRAITEMENT (départs en traitement de surface) à y ajouter.
- ~~Analyse de la marche en avant BET → fab → pose~~ — faite (bureau →
  *Marche en avant*), en code et avec bancs : une date de fabrication future
  n'est jamais « réalisée ». Reste : l'envoi automatique du lundi 7 h (mail),
  et le planning TRAITEMENT dans la chaîne.
