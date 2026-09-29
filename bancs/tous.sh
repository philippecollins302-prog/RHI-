#!/bin/sh
# ═══ TOUS LES BANCS, ET UN VERDICT ═══
#
# Même règle qu'Ali Baba : sort en erreur au premier banc rouge, pour
# s'enchaîner avant un commit.
#
#   sh bancs/tous.sh && git commit …
#
cd "$(dirname "$0")/.." || exit 1
PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3
echec=0
for b in bancs/banc-*.py; do
  if PYTHONPATH=. "$PY" "$b" >/tmp/rhi-banc.log 2>&1; then
    tail -1 /tmp/rhi-banc.log
  else
    echo "❌ $b"
    tail -8 /tmp/rhi-banc.log | sed 's/^/     /'
    echec=1
  fi
done
if [ "$echec" = 0 ]; then echo "TOUS LES BANCS VERTS"; else echo "AU MOINS UN BANC ROUGE — rien ne part dans cet état"; fi
exit "$echec"
