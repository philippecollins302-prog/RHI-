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
1. `GET /api/interfast/outils` avec la vraie clé : trouver l'outil qui
   liste les affaires et celui qui pose des heures sur un CH.
2. Liste des CH lue dans InterFast (plus seulement dans les plannings).
3. Envoi des heures validées au bureau, sur une affaire de test d'abord,
   puis `ECRITURE = True`. Chaque pointage garde la référence InterFast
   créée (colonne `interfast`) : jamais deux envois.

## V2 — menuiserie (Alfa)
Les plannings MEN n'ont pas la même forme (onglet par année côté pose, pas
de bande « N° AFFAIRE ») : lecteurs dédiés, clé `INTERFAST_ALFA`.

## Plus tard
- Écran d'atelier qui fait défiler pose / traitement (demande d'Alexis).
- Analyse de la marche en avant BET → fab → traitement → pose, chaque lundi
  à 7 h (reprise de l'agent de synthèse d'Alexis, en code et avec bancs :
  une date de fabrication future n'est jamais « réalisée »).
