"""Les pages : chaque script annoncé existe, et tout contenu injecté passe par esc()."""
import re
from pathlib import Path

from bancs.outils import fin, verif

PUB = Path(__file__).resolve().parent.parent / "public"

for page in ("index.html", "bureau.html"):
    html = (PUB / page).read_text()
    for src in re.findall(r'(?:src|href)="([^"#:]+)"', html):
        verif((PUB / src).exists(), f"{page} charge {src}, absent du disque")
    verif(html.index("commun.js") < html.index("terrain.js" if page == "index.html" else "bureau.js"),
          f"{page} : commun.js d'abord (il définit $, esc, api)")

for js in ("terrain.js", "bureau.js"):
    code = (PUB / js).read_text()
    # Toute interpolation ${…} dans un gabarit HTML doit être échappée, sauf
    # les nombres et les fragments déjà construits (listes .map().join()).
    for m in re.finditer(r"\$\{([^{}]+)\}", code):
        expr = m.group(1).strip()
        sure = (expr.startswith(("esc(", "heures(", "duree(")) or "?" in expr or ".map(" in expr
                or re.fullmatch(r"[\w.]+\.(length|id|total|a_verifier|personnes|affectations)", expr)
                or re.fullmatch(r"p\.id|p|cl|j|RETOUR_MS|chemin|vue\.semaine", expr)  # vue.semaine : une date AAAA-MM-JJ
                or expr in ("choixSemaine()", "vides.length ? '' : ''"))
        verif(sure, f"{js} : « ${{{expr}}} » injecté sans esc()")

fin("banc-ecran")
