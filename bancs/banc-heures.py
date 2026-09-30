"""Les heures de Paris côté navigateur, quel que soit le fuseau de l'appareil.

Né du 29/09/2026 : une tablette réglée en UTC calculait un écart d'horloge
de deux heures, ses gestes hors ligne tombaient « dans le futur » et le
serveur les ramenait tous à l'heure de réception. On exécute les fonctions
de commun.js sous node, dans quatre fuseaux, y compris un jour de
changement d'heure."""
import json
import os
import shutil
import subprocess
from pathlib import Path

from bancs.outils import fin, verif

PUB = Path(__file__).resolve().parent.parent / "public"
if not shutil.which("node"):
    print("✅ banc-heures — node absent, banc sauté (la CI l'a)")
    raise SystemExit(0)

SCRIPT = (PUB / "commun.js").read_text() + """
const cas = [
  ['2026-09-29T07:30:00', Date.UTC(2026, 8, 29, 5, 30)],   // été : UTC+2
  ['2026-12-01T07:30:00', Date.UTC(2026, 11, 1, 6, 30)],   // hiver : UTC+1
  ['2026-10-25T01:30:00', Date.UTC(2026, 9, 24, 23, 30)],  // nuit du passage à l'heure d'hiver
];
console.log(JSON.stringify(cas.map(([iso, ms]) => [msDeParis(iso) === ms, isoParis(ms) === iso, iso])));
"""
# commun.js touche au DOM seulement à l'appel : on neutralise document.
SCRIPT = "globalThis.document = {querySelector: () => null};\n" + SCRIPT

for fuseau in ("UTC", "Europe/Paris", "America/New_York", "Asia/Tokyo"):
    sortie = subprocess.run(["node", "-e", SCRIPT], capture_output=True, text=True,
                            env=dict(os.environ, TZ=fuseau))
    verif(sortie.returncode == 0, f"node ({fuseau}) : {sortie.stderr[-300:]}")
    for aller, retour, iso in json.loads(sortie.stdout):
        verif(aller, f"{fuseau} : msDeParis({iso}) faux")
        verif(retour, f"{fuseau} : isoParis → {iso} faux")

fin("banc-heures")
