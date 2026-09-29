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
3. Décider le chemin des heures (A, B ou C dans `docs/interfast.md`), puis
   l'essayer sur une affaire de test avant `ECRITURE = True`.
4. Relier chaque personne de RHI à son utilisateur InterFast (id).
5. ~~Montant vendu par CH et coût horaire~~ — fait : vendu HT lu dans les
   devis signés/payés dont le titre porte le CH (9 CH sur 33 le 29/09/2026 :
   la plupart des devis ne portent pas leur CH — à faire corriger à la
   saisie), coût horaire par personne, part de main-d'œuvre dans le vendu.

## V2 — menuiserie (Alfa)
Les plannings MEN n'ont pas la même forme (onglet par année côté pose, pas
de bande « N° AFFAIRE ») : lecteurs dédiés, clé `INTERFAST_ALFA`.

## Plus tard
- ~~Écran d'atelier qui fait défiler atelier / pose~~ — fait (`/ecran`).
  Reste le planning TRAITEMENT (départs en traitement de surface) à y ajouter.
- Analyse de la marche en avant BET → fab → traitement → pose, chaque lundi
  à 7 h (reprise de l'agent de synthèse d'Alexis, en code et avec bancs :
  une date de fabrication future n'est jamais « réalisée »).
