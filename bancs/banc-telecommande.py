"""La télécommande Clever (outils/telecommande.py) : elle règle RHI sans
jamais écrire une valeur — le dépôt est public, les journaux des runs aussi.

Un faux `clever` tient deux applications aux valeurs piégées ; le banc
vérifie qu'aucune n'apparaît dans la sortie ni sur une ligne de commande,
que la recopie du courrier passe par l'environnement, et qu'elle refuse
de recopier un réglage incomplet."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from bancs.outils import fin, verif

RACINE = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
journal = tmp / "appels.jsonl"
etat_apps = tmp / "apps.json"
ALIBABA = "app_alibaba_de_banc"
RHI = [l.split("=", 1)[1].split()[0] for l in (RACINE / "outils/clever.conf").read_text().splitlines()
       if l.startswith("APP_VIP=")][0]
SECRETS = {"SMTP_HOST": "smtp.piege-hote.fr", "SMTP_PORT": "587", "SMTP_USER": "piege-utilisateur@x.fr",
           "SMTP_PASS": "-piege-MotDePasse!42", "MAIL_FROM": "piege-expediteur@x.fr"}

faux = tmp / "clever"
faux.write_text(f"""#!{sys.executable}
import json, os, sys
a = sys.argv[1:]
apps = json.load(open({str(etat_apps)!r}))
env_vus = {{k: os.environ[k] for k in {list(SECRETS)!r} if k in os.environ}}
open({str(journal)!r}, "a").write(json.dumps({{"argv": a, "env": env_vus}}) + "\\n")
app = a[a.index("--app") + 1]
if a[0] == "env" and len(a) > 1 and a[1] == "import-vars":
    for n in a[2].split(","):
        apps[app][n] = os.environ.get(n, "")
    json.dump(apps, open({str(etat_apps)!r}, "w"))
    print("Your environment variables have been successfully saved")
elif a[0] == "env":
    print(json.dumps({{"env": [{{"name": k, "value": v}} for k, v in apps[app].items()]}}))
elif a[0] == "restart":
    print("Restarting")
else:
    sys.exit(3)
""")
faux.chmod(0o755)


def lancer(geste, apps, github=False):
    etat_apps.write_text(json.dumps(apps))
    journal.write_text("")
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY")}
    env.update(CLEVER=str(faux), ALIBABA=ALIBABA)
    if github:
        env.update(GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(tmp / "resume.md"))
    r = subprocess.run([sys.executable, str(RACINE / "outils/telecommande.py"), geste],
                       capture_output=True, text=True, env=env)
    appels = [json.loads(l) for l in journal.read_text().splitlines()]
    return r, appels, json.loads(etat_apps.read_text())


def fuite(texte, sauf_masques=False):
    lignes = [l for l in texte.splitlines() if not (sauf_masques and l.startswith("::add-mask::"))]
    return [s for n, s in SECRETS.items() if n != "SMTP_PORT" and any(s in l for l in lignes)]


apps = {ALIBABA: dict(SECRETS, AUTRE_CLE_ALIBABA="piege-autre"),
        RHI: {"RHI_CODE_BUREAU": "piege-code", "RHI_MARCHE_A": "piege@alexis.fr", "RHI_DONNEES": "/donnees"}}

# ── État : des noms, jamais de valeurs ──
r, appels, _ = lancer("etat", apps)
verif(r.returncode == 0, f"état lu : {r.stderr}")
verif("`SMTP_HOST` : MANQUANT" in r.stdout and "`RHI_CODE_BUREAU` : réglé" in r.stdout,
      "l'état dit ce qui manque et ce qui est réglé")
verif(not fuite(r.stdout) and "piege-code" not in r.stdout and "piege@alexis.fr" not in r.stdout
      and "piege-autre" not in r.stdout, "aucune valeur dans la sortie de l'état")
verif(all(a["argv"][0] == "env" for a in appels), "l'état ne fait que lire")

# ── Courrier : recopié par l'environnement, pas par la ligne de commande ──
r, appels, apres = lancer("courrier", apps, github=True)
verif(r.returncode == 0, f"courrier recopié : {r.stdout} {r.stderr}")
verif(all(apres[RHI].get(n) == v for n, v in SECRETS.items()), "les cinq réglages du courrier sont sur RHI")
verif(apres[RHI]["RHI_CODE_BUREAU"] == "piege-code", "les autres réglages de RHI sont intacts")
verif("AUTRE_CLE_ALIBABA" not in apres[RHI], "rien d'autre d'Ali Baba n'est recopié")
verif(not any(s in " ".join(a["argv"]) for a in appels for s in SECRETS.values() if s != "587"),
      "aucune valeur sur une ligne de commande (visible dans ps)")
imp = [a for a in appels if a["argv"][:2] == ["env", "import-vars"]]
verif(len(imp) == 1 and imp[0]["argv"][imp[0]["argv"].index("--app") + 1] == RHI,
      "une seule écriture, et sur RHI — jamais sur Ali Baba")
verif(any(a["argv"][0] == "restart" and RHI in a["argv"] for a in appels),
      "RHI redémarre : sans quoi les variables ne s'appliquent pas")
verif(not fuite(r.stdout, sauf_masques=True), "aucune valeur dans le journal hors demandes de masquage")
verif(all(f"::add-mask::{s}" in r.stdout for n, s in SECRETS.items()),
      "chaque valeur recopiée est masquée dans le journal GitHub")
resume = (tmp / "resume.md").read_text()
verif("Recopiés" in resume and not fuite(resume), "le résumé du run dit ce qui est fait, sans valeur")

# ── Réglage incomplet chez Ali Baba : refus, rien d'écrit ──
incomplet = {ALIBABA: {k: v for k, v in SECRETS.items() if k != "SMTP_PASS"}, RHI: {}}
r, appels, apres = lancer("courrier", incomplet)
verif(r.returncode != 0 and "SMTP_PASS" in r.stderr + r.stdout, "sans mot de passe chez Ali Baba : refus motivé")
verif(not any(a["argv"][:2] == ["env", "import-vars"] for a in appels) and apres[RHI] == {},
      "rien d'écrit sur RHI")

r, _, _ = lancer("detruire", apps)
verif(r.returncode != 0, "geste inconnu : refusé")

# ── Le bouton GitHub existe, et seulement à la main ──
wf = (RACINE / ".github/workflows/telecommande.yml").read_text()
verif("workflow_dispatch" in wf and "push:" not in wf and "pull_request" not in wf,
      "la télécommande ne part que sur un clic, jamais sur une poussée")
verif("outils/telecommande.py" in wf and "secrets.CLEVER_TOKEN" in wf, "elle lance l'outil avec les secrets du dépôt")

fin("banc-telecommande")
