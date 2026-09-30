""".github/workflows/chaine.yml tient ses promesses — lues dans le fichier, pas supposées.

Une chaîne de déploiement ne se teste pas en vrai depuis un banc (elle
pousserait en production). On vérifie donc sa forme : chaque garde est
là, et aucune n'a été affaiblie par une retouche distraite.
"""
import re
from pathlib import Path

import yaml

from bancs.outils import fin, verif

RACINE = Path(__file__).resolve().parent.parent
texte = (RACINE / ".github/workflows/chaine.yml").read_text()
ch = yaml.safe_load(texte)
jobs = ch["jobs"]
verif(not (RACINE / ".github/workflows/bancs.yml").exists(), "une seule chaîne : l'ancien bancs.yml doublerait les bancs")

declencheurs = ch.get("on", ch.get(True))   # YAML 1.1 lit « on » comme True
verif("push" in declencheurs and "pull_request" in declencheurs, "les bancs sur toute poussée et toute PR")
verif("tous.sh" in str(jobs["bancs"]), "les bancs, c'est tous.sh — pas une liste à tenir")

d = jobs["deploiement"]
verif(d["needs"] == "bancs", "pas de déploiement sans bancs verts")
verif("refs/heads/main" in d["if"] and "push" in d["if"], "seule une poussée sur main déploie")
verif("[sans-deploiement]" in d["if"], "l'échappatoire [sans-deploiement] existe")
verif(d["concurrency"]["cancel-in-progress"] is False, "un déploiement en vol n'est JAMAIS annulé")
etapes = " ".join(str(e.get("run", "")) for e in d["steps"])
verif("verifier-deploiement.sh \"$GITHUB_SHA\"" in etapes, "le verdict : le site sert CE commit (pas un code de sortie)")
verif(etapes.index("clever deploy") < etapes.index("verifier-deploiement.sh"), "vérifié APRÈS le déploiement")
verif('-z "$CLEVER_TOKEN"' in etapes, "secrets absents : refus explicite, pas un clever qui échoue on ne sait où")
verif("secrets.CLEVER_TOKEN" in texte and not re.search(r"CLEVER_(TOKEN|SECRET)\s*[:=]\s*['\"]?[A-Za-z0-9]{12}", texte),
      "les identifiants viennent des secrets GitHub, jamais écrits en clair")
verif(d.get("outputs", {}).get("motif") and jobs["bancs"].get("outputs", {}).get("motif"),
      "chaque maillon rend son motif")
verif("GITHUB_STEP_SUMMARY" in str(jobs["bancs"]) and "GITHUB_STEP_SUMMARY" in etapes,
      "le motif s'écrit en tête du run (résumé), pas noyé dans le journal")

a = jobs["alerte"]
verif("always()" in a["if"] and a["needs"] == ["bancs", "deploiement"], "l'alerte passe même quand tout a échoué")
script = a["steps"][0]["run"]
verif("gh issue create" in script and "--assignee philippecollins302-prog" in script,
      "un échec ouvre une issue ASSIGNÉE — une alerte qui n'atteint personne ne sert à rien")
verif("gh issue close" in script and 'DEPLOIEMENT" = success' in script,
      "le retour au vert (déploiement vérifié) referme l'alerte tout seul")
verif("gh issue comment" in script, "un deuxième échec commente l'issue ouverte, n'en ouvre pas une pile")
# Injection : un motif contient du texte des bancs ; recollé par ${{ }} dans un
# script, un « $(…) » dedans s'exécuterait. Il passe par l'environnement.
for nom, job in jobs.items():
    for e in job["steps"]:
        verif("${{" not in str(e.get("run", "")), f"{nom} : aucune expression ${{{{ }}}} dans un script")

conf = (RACINE / "outils/clever.conf").read_text()
verif("APP_VIP=app_" in conf and "outils/clever.conf" in etapes, "l'application déployée vient de clever.conf, la seule copie")

fin("banc-chaine")
