"""outils/secrets-github.sh pose la vraie clé, quel que soit le format de clever-tools.

Né du premier déploiement refusé (30/09/2026) : la notice lisait ['token'] à
la racine de clever-tools.json, alors que clever-tools 4 range la session
dans une liste « profiles ». Un faux `gh` note ce qu'il reçoit ; aucun
secret réel n'est touché.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from bancs.outils import fin, verif

RACINE = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
recu = tmp / "recu"
faux = tmp / "gh"
faux.write_text(f'#!/bin/sh\nprintf "%s=" "$3" >> {recu}; cat >> {recu}; echo >> {recu}\n')
faux.chmod(0o755)
conf = tmp / "clever-tools.json"


def poser(contenu):
    conf.write_text(json.dumps(contenu))
    recu.write_text("")
    r = subprocess.run(["sh", str(RACINE / "outils/secrets-github.sh")], capture_output=True, text=True,
                       env=dict(os.environ, CLEVER_CONFIG=str(conf), GH=str(faux)))
    return r, recu.read_text()


# Le format réel du poste de Philippe (clever-tools 4.11) : ['version', 'profiles'].
r, vu = poser({"version": 1, "profiles": [{"alias": "default", "token": "jeton-v4", "secret": "secret-v4",
                                           "expirationDate": "2027-09-02"}]})
verif(r.returncode == 0 and vu == "CLEVER_TOKEN=jeton-v4\nCLEVER_SECRET=secret-v4\n",
      f"clever-tools 4 : la clé est dans profiles[0], c'est elle qui part {vu!r} {r.stderr}")
verif("jeton-v4" not in r.stdout + r.stderr and "secret-v4" not in r.stdout + r.stderr,
      "les valeurs ne s'affichent jamais")

r, vu = poser({"token": "jeton-ancien", "secret": "secret-ancien"})
verif(r.returncode == 0 and "CLEVER_TOKEN=jeton-ancien\n" in vu, "l'ancien format (à la racine) marche encore")

r, vu = poser({"token": " jeton-espace\n", "secret": "s"})
verif("CLEVER_TOKEN=jeton-espace\n" in vu, "ni espace ni retour à la ligne collés à la clé")

r, vu = poser({"version": 1, "profiles": [{"token": "a", "secret": "b"}, {"token": "c", "secret": "d"}]})
verif(r.returncode != 0 and vu == "" and "2 profils" in r.stderr,
      "deux profils : on ne devine pas, rien n'est posé")

r, vu = poser({"version": 1, "profiles": [{"token": "seul"}]})
verif(r.returncode != 0 and vu == "" and "secret" in r.stderr,
      "un secret manquant : rien n'est posé, pas même le jeton (jamais un jeton neuf avec un vieux secret)")

conf.unlink()
r = subprocess.run(["sh", str(RACINE / "outils/secrets-github.sh")], capture_output=True, text=True,
                   env=dict(os.environ, CLEVER_CONFIG=str(conf), GH=str(faux)))
verif(r.returncode == 1 and "clever login" in r.stderr, "pas de session : on dit quoi faire")

doc = (RACINE / "docs/deploiement.md").read_text()
verif("secrets-github.sh" in doc and "))['token']" not in doc,
      "la notice envoie vers l'outil, plus vers la commande qui lisait au mauvais endroit")

fin("banc-secrets")
