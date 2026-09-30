#!/bin/sh
# ═══ POSER LES DEUX SECRETS DE LA CHAÎNE, SANS LES VOIR ═══
#
#   sh outils/secrets-github.sh
#
# Lit la session clever-tools du poste et la pose dans les secrets GitHub
# CLEVER_TOKEN / CLEVER_SECRET, de programme à programme : rien ne s'affiche,
# rien ne passe par un presse-papier ni par une conversation.
#
# Pourquoi un outil et plus une ligne de notice : la notice lisait
# `['token']` à la racine du fichier. clever-tools 4 range la session dans
# une liste `profiles` ; la commande a posé autre chose que la clé, et le
# premier déploiement a été refusé (« Your token is invalid », 30/09/2026).
# L'outil lit les deux formes, et refuse — sans rien poser — s'il ne trouve
# pas exactement un jeton et un secret.
set -eu
F=${CLEVER_CONFIG:-$HOME/.config/clever-cloud/clever-tools.json}
DEPOT=${DEPOT:-philippecollins302-prog/RHI-}
GH=${GH:-gh}

[ -f "$F" ] || { echo "pas de session clever-tools ($F) : lancer d'abord clever login" >&2; exit 1; }
command -v "$GH" >/dev/null 2>&1 || { echo "gh absent : brew install gh, puis gh auth login" >&2; exit 1; }

lire() {  # $1 = token | secret ; imprime la valeur sans retour à la ligne
  python3 - "$F" "$1" <<'PY'
import json, sys
chemin, champ = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(chemin))
except Exception as e:
    sys.exit(f"{chemin} illisible : {e}")
if "profiles" in d:                      # clever-tools 4 et suivants
    p = d["profiles"]
    if not isinstance(p, list) or len(p) != 1:
        sys.exit(f"{len(p) if isinstance(p, list) else '?'} profils Clever sur ce poste : "
                 "impossible de savoir lequel poser (clever logout, puis clever login)")
    d = p[0]
v = d.get(champ) if isinstance(d, dict) else None
if not isinstance(v, str) or not v.strip():
    sys.exit(f"champ « {champ} » introuvable dans {chemin} (champs vus : {sorted(d) if isinstance(d, dict) else '?'})")
sys.stdout.write(v.strip())
PY
}

# Les deux d'abord, la pose ensuite : jamais un jeton neuf avec un vieux secret.
T=$(lire token) || exit 1
S=$(lire secret) || exit 1
printf '%s' "$T" | "$GH" secret set CLEVER_TOKEN -R "$DEPOT"
printf '%s' "$S" | "$GH" secret set CLEVER_SECRET -R "$DEPOT"
echo "✅ CLEVER_TOKEN et CLEVER_SECRET posés sur $DEPOT (valeurs non affichées)"
