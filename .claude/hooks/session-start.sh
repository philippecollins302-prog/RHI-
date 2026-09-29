#!/bin/bash
# Claude Code sur le web démarre dans un conteneur neuf : on y refait le
# .venv que bancs/tous.sh et .claude/launch.json supposent présent.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"
PY=$(command -v python3.12 || command -v python3)
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet -r requirements.txt
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
echo "session-start : prêt. Bancs : sh bancs/tous.sh"
