"""Le minimum pour qu'un banc parle : une vérification qui dit ce qu'elle attendait."""
import sys

_compte = {"ok": 0}


def verif(condition, message):
    if not condition:
        print("❌", message)
        sys.exit(1)
    _compte["ok"] += 1


def fin(nom):
    print(f"✅ {nom} — {_compte['ok']} vérifications")
