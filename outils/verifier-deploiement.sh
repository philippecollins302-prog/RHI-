#!/bin/sh
# ═══ LE DÉPLOIEMENT A-T-IL VRAIMENT MARCHÉ ? ═══
#
#   sh outils/verifier-deploiement.sh <commit attendu> [adresse] [délai en s]
#
# Un code de sortie de `clever deploy` ne prouve rien : le 01/09/2026, sur Ali
# Baba, cinq déploiements ont « réussi » en laissant le site en 503. On juge
# donc le site lui-même, jusqu'à ce qu'il réponde :
#   - /api/sante en 200, du JSON lisible ;
#   - "version" = le commit qu'on vient de pousser (pas l'ancien qui tourne encore) ;
#   - "pret": true (base sur le bucket, journal delete, codes réglés).
#
# ÉCHOUE FERMÉ : tout ce qui n'est pas lu comme bon — pas de réponse, 503,
# JSON illisible, champ absent, autre version — compte comme un échec. La
# dernière chose vue est imprimée en tête, c'est le motif de l'alerte.
set -u
ATTENDU=${1:-}
[ -n "$ATTENDU" ] || { echo "MOTIF : aucun commit attendu donné à la vérification" >&2; exit 2; }
. "$(dirname "$0")/clever.conf"
URL=${2:-$URL_VIP}
DELAI=${3:-600}
PAS=${PAS:-10}

fin=$(( $(date +%s) + DELAI ))
vu="rien encore"
while :; do
  corps=$(curl -sS -m 15 -w '\n%{http_code}' "$URL/api/sante" 2>&1)
  code=$(printf '%s' "$corps" | tail -n 1)
  json=$(printf '%s' "$corps" | sed '$d')
  if [ "$code" = 200 ]; then
    vu=$(printf '%s' "$json" | python3 -c '
import json, sys
attendu = sys.argv[1]
try:
    s = json.load(sys.stdin)
except Exception:
    print("réponse 200 mais pas du JSON"); sys.exit()
v, p, c = s.get("version"), s.get("pret"), s.get("codes")
if v != attendu:
    print(f"version servie {v!r}, attendue {attendu!r} : l ancien code tourne encore (ou COMMIT_ID absent)")
elif p is not True:
    print(f"bonne version, mais pas prête (pret={p!r}, codes={c!r}) : lire /api/sante/detail")
else:
    print("OK")
' "$ATTENDU" 2>&1)
    [ -n "$vu" ] || vu="vérificateur muet sur une réponse 200"
    [ "$vu" = OK ] && { echo "✅ $URL sert $ATTENDU, et se dit prêt"; exit 0; }
  else
    vu="HTTP ${code:-aucune réponse} sur $URL/api/sante"
  fi
  [ "$(date +%s)" -ge "$fin" ] && break
  sleep "$PAS"
done
echo "MOTIF : après ${DELAI}s, $vu" >&2
exit 1
