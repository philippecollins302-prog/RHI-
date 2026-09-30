#!/bin/sh
# ═══ METTRE RHI SUR CLEVER CLOUD, EN UNE COMMANDE ═══
#
#   sh outils/clever-installer.sh            # VIP Plus : application « rhi »
#   sh outils/clever-installer.sh alfa       # Alfa     : application « rhi-alfa »
#
# Fait, dans l'organisation GROUP ALMA, région Paris, tout ce que
# docs/deploiement.md décrit en clics : l'application Python, le FS Bucket
# relié et monté sur donnees/, les variables, une seule instance, et deux
# codes d'accès tirés au hasard (affichés UNE fois, jamais écrits dans le
# dépôt — le dépôt est public).
#
# Ce qu'il ne fait PAS, exprès :
#   - déployer. C'est le travail de la chaîne (.github/workflows/chaine.yml) :
#     une poussée sur main, bancs verts, puis le site vérifié ;
#   - poser les clés InterFast et le mot de passe SMTP : ils ne passent que
#     par la console Clever, jamais par une ligne de commande qui finit dans
#     un historique.
#
# Prérequis : clever-tools (npm i -g clever-tools) et une session ouverte —
# `clever login` sur le poste, ou CLEVER_TOKEN / CLEVER_SECRET dans
# l'environnement. Relançable : ce qui existe déjà n'est pas refait, et des
# codes déjà posés ne sont jamais remplacés.
set -eu

. "$(dirname "$0")/clever.conf"                    # ORGA, REGION, APP_VIP : une seule copie
QUI=${1:-vip}
case "$QUI" in
  vip)  NOM=rhi;      ENTREPRISE=VIP ;;
  alfa) NOM=rhi-alfa; ENTREPRISE=ALFA ;;
  *) echo "Usage : sh outils/clever-installer.sh [vip|alfa]" >&2; exit 2 ;;
esac
CLEVER=${CLEVER:-clever}
cd "${RHI_DEPOT:-$(dirname "$0")/..}"

command -v "$CLEVER" >/dev/null 2>&1 || {
  echo "clever-tools absent : npm i -g clever-tools, puis clever login" >&2; exit 1; }

etape() { printf '\n── %s\n' "$1"; }

# Une application par entreprise, dans le même dépôt : chacune son alias.
etape "Application $NOM (Python, $REGION, GROUP ALMA)"
if [ -f .clever.json ] && grep -q "\"alias\": *\"$NOM\"" .clever.json; then
  echo "déjà liée ici : rien à créer"
elif [ "$QUI" = vip ] && [ -n "${APP_VIP:-}" ]; then
  # Elle existe déjà (créée à la console) : la relier, surtout pas en créer une seconde.
  "$CLEVER" link "$APP_VIP" --org "$ORGA" --alias "$NOM"
else
  "$CLEVER" create --type python --org "$ORGA" --region "$REGION" --alias "$NOM" "$NOM"
fi
C() { "$CLEVER" "$@" --alias "$NOM"; }

etape "Une seule instance (deux processus sur une base SQLite réseau = casse)"
C scale --flavor XS --min-instances 1 --max-instances 1

etape "FS Bucket $NOM-donnees, relié"
if C env | grep -q '^BUCKET_HOST='; then
  echo "déjà relié : rien à créer"
else
  "$CLEVER" addon create fs-bucket "$NOM-donnees" --yes --org "$ORGA" --region "$REGION" --link "$NOM"
fi
HOTE=$(C env | sed -n 's/^BUCKET_HOST=//p' | tr -d "\"'" | head -1)
[ -n "$HOTE" ] || { echo "BUCKET_HOST introuvable après la création du bucket : voir la console" >&2; exit 1; }

etape "Variables"
C env set CC_RUN_COMMAND "uvicorn app:app --host 0.0.0.0 --port 9000"
C env set CC_PYTHON_VERSION "3.12"
C env set CC_FS_BUCKET "/donnees:$HOTE"
C env set RHI_ENTREPRISE "$ENTREPRISE"

etape "Codes d'accès"
if C env | grep -q '^RHI_CODE_BUREAU='; then
  echo "déjà posés : gardés tels quels (les tablettes les connaissent)"
else
  # Terrain : tapé une fois par tablette, donc court et sans ambiguïté.
  # Bureau : 20 caractères, bien au-delà des 12 exigés en production.
  TERRAIN=$(python3 -c "import secrets; print(''.join(secrets.choice('abcdefghjkmnpqrstuvwxyz23456789') for _ in range(8)))")
  BUREAU=$(python3 -c "import secrets; print(secrets.token_urlsafe(15))")
  C env set RHI_CODE_TERRAIN "$TERRAIN"
  C env set RHI_CODE_BUREAU "$BUREAU"
  cat <<FIN

  ┌──────────────────────────────────────────────────────────────
  │ À NOTER MAINTENANT — ils ne s'afficheront plus :
  │   code terrain (tablettes, téléphones) : $TERRAIN
  │   code bureau                           : $BUREAU
  │ Ils restent lisibles dans la console Clever (Variables).
  └──────────────────────────────────────────────────────────────
FIN
fi

CLE=INTERFAST_$ENTREPRISE
cat <<FIN

── Reste à faire à la main, dans la console Clever → $NOM → Variables :
   $CLE        la clé InterFast (RÉGÉNÉRÉE : l'ancienne a circulé en clair)
   RHI_COUT_HORAIRE     le taux horaire moyen chargé
   RHI_MARCHE_A         les destinataires de la marche du lundi
   SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS MAIL_FROM   comme dans Ali Baba

── Le déploiement, c'est la chaîne (poussée sur main). En secours, à la main :
   $CLEVER deploy --alias $NOM
   $CLEVER activity --alias $NOM      # le déploiement est-il OK ?
   sh outils/verifier-deploiement.sh "\$(git rev-parse HEAD)"
FIN
