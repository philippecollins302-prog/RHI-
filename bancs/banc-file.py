"""La file des gestes de la tablette, jouée sous node avec la VRAIE fonction vider().

Un geste gardé hors ligne ne doit se perdre que sur un vrai refus du
serveur (409, 422). Avant le 29/09/2026, tout code HTTP le retirait de la
file : un 503 pendant un redéploiement Clever, un 429 du frein aux codes
faux, et le chantier du matin disparaissait sans bruit.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from bancs.outils import fin, verif

code = (Path(__file__).resolve().parent.parent / "public/terrain.js").read_text()
m = re.search(r"let enCoursDeVidage = false;\nasync function vider\(\) \{.*?\n\}\n", code, re.S)
verif(m, "vider() introuvable dans terrain.js")

if not shutil.which("node"):
    print("✅ banc-file — node absent, rien à jouer (0 vérification)")
    raise SystemExit(0)


def jouer(reponses: list) -> dict:
    """Une file de trois gestes ; le serveur répond `reponses` dans l'ordre (null = accepté)."""
    js = """
const stock = {'rhi.file': JSON.stringify([{chemin: '/a'}, {chemin: '/b'}, {chemin: '/c'}])};
const lireJson = (k, d) => stock[k] ? JSON.parse(stock[k]) : d;
const enAttente = () => lireJson('rhi.file', []);
const ecrire = (k, v) => { stock[k] = v; };
const dits = []; const dire = t => dits.push(t); const bandeau = () => {};
const reponses = %s;
async function api() {
  const r = reponses.shift();
  if (r === undefined || r === null) return {};
  if (r === 'reseau') throw new TypeError('Failed to fetch');
  const e = new Error('refus ' + r); e.http = r; throw e;
}
%s
vider().then(() => console.log(JSON.stringify({reste: lireJson('rhi.file', []).length, dits})));
""" % (json.dumps(reponses), m.group(0))
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True)
    verif(r.returncode == 0, f"node : {r.stderr}")
    return json.loads(r.stdout)


verif(jouer([None, None, None])["reste"] == 0, "réseau revenu : la file se vide")
verif(jouer(["reseau"])["reste"] == 3, "toujours pas de réseau : tout reste")
verif(jouer([503])["reste"] == 3, "503 pendant un redéploiement : le geste reste, il repartira")
verif(jouer([502])["reste"] == 3, "502 du proxy : pareil")
verif(jouer([429])["reste"] == 3, "429 (codes faux) : le geste reste")
verif(jouer([401])["reste"] == 3, "401 (code à ressaisir) : le geste reste")
r = jouer([None, 409, None])
verif(r["reste"] == 0 and any("409" in d for d in r["dits"]),
      "409 (semaine validée) : ce geste-là est retiré, en le disant, et la file continue")
verif(jouer([422, "reseau"])["reste"] == 2, "422 : refus définitif, retiré — sinon il bloquerait la file à jamais")

fin("banc-file")
