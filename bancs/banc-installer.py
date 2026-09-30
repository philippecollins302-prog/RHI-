"""outils/clever-installer.sh joué contre un faux `clever`, qui note tout.

Le vrai touche l'organisation GROUP ALMA : un banc ne doit jamais pouvoir
créer quoi que ce soit chez Clever. Le faux tient un petit état (bucket
relié ? variables posées ?) pour vérifier que le script est relançable sans
dégâts — surtout sans remplacer des codes que les tablettes connaissent.
"""
import os
import subprocess
import tempfile
from pathlib import Path

from bancs.outils import fin, verif

RACINE = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
journal, etat = tmp / "appels.log", tmp / "env"
etat.write_text("")
faux = tmp / "clever"
faux.write_text(f"""#!/bin/sh
echo "$*" >> {journal}
case "$1 $2" in
  "env set") grep -v "^$3=" {etat} > {etat}.n; echo "$3=$4" >> {etat}.n; mv {etat}.n {etat} ;;
  "env --alias") cat {etat} ;;
  "addon create") echo "BUCKET_HOST=bucket-123-fsbucket.services.clever-cloud.com" >> {etat} ;;
  "create --type") printf '{{"apps": [{{"alias": "%s"}}]}}' "$(echo "$*" | sed 's/.* //')" > .clever.json ;;
  link*) printf '{{"apps": [{{"alias": "%s"}}]}}' "$(echo "$*" | sed 's/.*--alias //')" > .clever.json ;;
esac
""")
faux.chmod(0o755)
env = dict(os.environ, CLEVER=str(faux), RHI_DEPOT=str(tmp))


def installer(*args):
    return subprocess.run(["sh", str(RACINE / "outils/clever-installer.sh"), *args],
                          capture_output=True, text=True, env=env)


r = installer()
verif(r.returncode == 0, f"première installation : {r.stderr}")
appels = journal.read_text()
verif("link app_a5509cc0-71a5-49d4-b201-ca1941713f22 --org orga_b3f4776d-f719-4c57-afbb-628b175dff3a" in appels
      and "create --type" not in appels,
      "VIP existe déjà (console, 29/09) : reliée, surtout pas recréée en double")
verif("--min-instances 1 --max-instances 1" in appels, "une seule instance")
verif("addon create fs-bucket rhi-donnees" in appels and "--link rhi" in appels, "le bucket, relié")
variables = dict(l.split("=", 1) for l in etat.read_text().splitlines())
verif(variables["CC_FS_BUCKET"] == "/donnees:bucket-123-fsbucket.services.clever-cloud.com",
      "le bucket monté sur donnees/, là où la base vit")
verif(variables["CC_RUN_COMMAND"] == "uvicorn app:app --host 0.0.0.0 --port 9000", "port 9000 (le 8080 est au nginx)")
verif(variables["RHI_ENTREPRISE"] == "VIP", "instance VIP par défaut")
t, b = variables["RHI_CODE_TERRAIN"], variables["RHI_CODE_BUREAU"]
verif(len(t) == 8 and len(b) >= 12 and t != b, "deux codes tirés au hasard, bureau d'au moins 12 caractères")
verif(t in r.stdout and b in r.stdout, "affichés une fois pour être notés")
verif(not any(l.startswith("deploy") for l in appels.splitlines()),
      "aucun déploiement : il attend « pousse »")
verif(not any("INTERFAST" in l or "SMTP_PASS" in l for l in appels.splitlines()),
      "aucune clé ni mot de passe en ligne de commande")

r = installer()
verif(r.returncode == 0, f"relancé : {r.stderr}")
appels2 = journal.read_text()[len(appels):]
verif("create --type" not in appels2 and "addon create" not in appels2, "relancé : rien n'est recréé")
v2 = dict(l.split("=", 1) for l in etat.read_text().splitlines())
verif(v2["RHI_CODE_TERRAIN"] == t and v2["RHI_CODE_BUREAU"] == b and t not in r.stdout,
      "relancé : les codes connus des tablettes sont gardés")

verif(installer("menuiserie").returncode == 2, "entreprise inconnue : refusé")
(tmp / ".clever.json").unlink()
r = installer("alfa")
verif(r.returncode == 0 and "create --type python --org orga_b3f4776d-f719-4c57-afbb-628b175dff3a --region par"
      in journal.read_text() and "RHI_ENTREPRISE=ALFA" in etat.read_text(),
      f"Alfa n'existe pas encore : créée dans GROUP ALMA, à Paris — pas dans l'espace personnel {r.stderr}")
r = subprocess.run(["sh", str(RACINE / "outils/clever-installer.sh")], capture_output=True, text=True,
                   env=dict(env, CLEVER="clever-absent-du-poste"))
verif(r.returncode == 1 and "npm i -g clever-tools" in r.stderr, "sans clever-tools : on dit comment l'avoir")

fin("banc-installer")
