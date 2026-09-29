"""Les pages : chaque script annoncé existe, et tout contenu injecté passe par esc()."""
import re
from pathlib import Path

from bancs.outils import fin, verif

PUB = Path(__file__).resolve().parent.parent / "public"

for page in ("index.html", "bureau.html", "ecran.html"):
    html = (PUB / page).read_text()
    for src in re.findall(r'(?:src|href)="([^"#:]+)"', html):
        verif((PUB / src).exists(), f"{page} charge {src}, absent du disque")
    verif(html.index("commun.js") < html.index({"index.html": "terrain.js", "bureau.html": "bureau.js",
                                               "ecran.html": "ecran.js"}[page]),
          f"{page} : commun.js d'abord (il définit $, esc, api)")

for js in ("terrain.js", "bureau.js", "ecran.js"):
    code = (PUB / js).read_text()
    # Toute interpolation ${…} dans un gabarit HTML doit être échappée, sauf
    # les nombres et les fragments déjà construits (listes .map().join()).
    for m in re.finditer(r"\$\{([^{}]+)\}", code):
        expr = m.group(1).strip()
        sure = (expr.startswith(("esc(", "heures(", "duree(", "euros(", "options(")) or "?" in expr or ".map(" in expr
                or re.fullmatch(r"[\w.]+\.(length|id|total|a_verifier|personnes|affectations)", expr)
                or re.fullmatch(r"p\.id|p|cl|j|RETOUR_MS|chemin|vue\.semaine", expr)  # vue.semaine : une date AAAA-MM-JJ
                or expr in ("choixSemaine()", "vides.length ? '' : ''"))
        verif(sure, f"{js} : « ${{{expr}}} » injecté sans esc()")

# euros() est déclarée sûre ci-dessus : elle doit vraiment échapper.
bureau = (PUB / "bureau.js").read_text()
verif("return esc(Number(v).toLocaleString" in bureau, "euros() passe par esc()")
verif("`<option value=\"${esc(u.id)}\"" in bureau and "${esc(u.prenom)} ${esc(u.nom)}" in bureau,
      "options() échappe chaque compte InterFast")

# Chaque onglet appelé par afficher() doit être déclaré AU NIVEAU DU FICHIER :
# le 29/09/2026, ongletPersonnes s'était glissé dans un gestionnaire de clic
# et l'onglet RHI plantait (« ongletPersonnes is not defined »).
carte = re.search(r"\(\{(rhi: .*?)\}\[vue\.onglet\]", bureau, re.S).group(1)
for fonction in re.findall(r":\s*(\w+)", carte):
    verif(re.search(rf"^async function {fonction}\(", bureau, re.M),
          f"bureau.js : {fonction} doit être déclarée au niveau du fichier")
verif(bureau.rstrip().endswith("afficher();"), "bureau.js se termine par l'appel de démarrage")

# La coquille hors ligne doit contenir tout ce que la page de la tablette charge.
sw = (PUB / "sw.js").read_text()
coquille = set(re.findall(r"'(/[^']*)'", re.search(r"SHELL = \[(.*?)\]", sw).group(1)))
index = (PUB / "index.html").read_text()
for src in re.findall(r'(?:src|href)="([^"#:]+)"', index):
    verif("/" + src in coquille, f"sw.js : {src} manque à la coquille hors ligne")
verif("/" in coquille, "sw.js : la page elle-même est dans la coquille")
verif("startsWith('/api/')" in sw, "sw.js : l'API ne passe jamais par le cache")

fin("banc-ecran")
