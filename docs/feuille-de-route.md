# Feuille de route

Ordre proposé ; chaque étape a son banc avant d'être livrée.

## V1 — pointage serrurerie (fait, 29/09/2026)
Tablette atelier, téléphone pose (chef + binôme), RHI hebdomadaire par
personne, export Excel, corrections au bureau, point d'affaire réel face au
prévu du plan de charge, import des plannings ATE et POSE SER.

## V1.1 — mise en service
- Déploiement Clever Cloud (même rituel qu'Ali Baba : branche `prod`,
  bucket monté sur `/donnees`, `CC_RUN_COMMAND="uvicorn app:app --host
  0.0.0.0 --port 9000"`), codes `RHI_CODE_TERRAIN` / `RHI_CODE_BUREAU`.
- Réponses d'Alexis (`docs/questions-alexis.md`) intégrées.
- Sauvegarde nocturne de la base.

## V1.2 — InterFast
1. ~~Trouver les outils avec la vraie clé~~ — fait le 29/09/2026, voir
   `docs/interfast.md`.
2. ~~Liste des CH lue dans InterFast~~ — fait (lecture seule).
3. Décider le chemin des heures (A, B ou C dans `docs/interfast.md`), puis
   l'essayer sur une affaire de test avant `ECRITURE = True`.
4. Relier chaque personne de RHI à son utilisateur InterFast (id).
5. Montant vendu par CH (devis signés) et coût horaire : la rentabilité.

## V2 — menuiserie (Alfa)
Les plannings MEN n'ont pas la même forme (onglet par année côté pose, pas
de bande « N° AFFAIRE ») : lecteurs dédiés, clé `INTERFAST_ALFA`.

## Plus tard
- Écran d'atelier qui fait défiler pose / traitement (demande d'Alexis).
- Analyse de la marche en avant BET → fab → traitement → pose, chaque lundi
  à 7 h (reprise de l'agent de synthèse d'Alexis, en code et avec bancs :
  une date de fabrication future n'est jamais « réalisée »).
