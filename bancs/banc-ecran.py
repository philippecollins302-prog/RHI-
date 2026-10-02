"""Les pages : chaque script annoncé existe, et tout contenu injecté passe par esc()."""
import re
from pathlib import Path

from bancs.outils import fin, verif

PUB = Path(__file__).resolve().parent.parent / "public"

for page in ("index.html", "bureau.html", "ecran.html"):  # mode-emploi.html : page sans script
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
carte = re.search(r"\(\{(\w+: .*?)\}\[vue\.onglet\]", bureau, re.S).group(1)
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
verif("url.pathname === '/'" in sw, "sw.js : hors ligne, seule la tablette retombe sur la page de la tablette")

# Le mode d'emploi ne promet que des gestes qui existent (règle d'Ali Baba).
guide = (PUB / "mode-emploi.html").read_text()
for onglet in ("Déposer les plannings", "Mes chantiers", "À vérifier", "RHI de la semaine",
               "Vers InterFast", "Personnes", "Qui pointe maintenant"):
    verif(onglet in guide and f">{onglet}<" in (PUB / "bureau.html").read_text(),
          f"mode d'emploi : l'onglet « {onglet} » existe au bureau")
for geste in ("J'arrête", "Valider la semaine", "Télécharger toute la base", "Hors affaire"):
    verif(geste in guide and any(geste in (PUB / f).read_text() for f in ("terrain.js", "bureau.js")),
          f"mode d'emploi : « {geste} » existe à l'écran")
# Retirés à la revue du 01/10/2026 (le point d'affaire vit dans InterFast, la
# marche en avant chez un agent à part) : le guide ne doit plus les promettre.
for parti in ("Point d'affaire", "Marche en avant"):
    verif(parti not in guide and f">{parti}<" not in (PUB / "bureau.html").read_text(),
          f"« {parti} » a quitté le bureau : ni onglet, ni promesse dans le guide")
verif("Rien n'y est envoyé" in guide, "le guide dit que l'envoi vers InterFast n'est pas branché")
for src in re.findall(r'src="([^"#:]+)"', guide):
    verif((PUB / src).exists(), f"mode d'emploi : la capture {src} est absente du disque")
    verif(src.startswith("aide/"), f"mode d'emploi : {src} hors du dossier des captures")
verif(all(re.search(r'<img [^>]*alt="[^"]+"', i) for i in re.findall(r"<img [^>]*>", guide)),
      "mode d'emploi : chaque capture dit ce qu'elle montre (alt)")

# L'attribut hidden ne cache rien si la feuille donne un display au même
# élément : le 30/09/2026, « button { display: inline-block } » (dessin Boost
# AO) a fait réapparaître « Changer de personne » sur l'écran des noms.
css = (PUB / "app.css").read_text()
verif(re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important", css),
      "app.css : [hidden] l'emporte sur tout display (sinon un bouton caché s'affiche)")

# Les motifs de secours de la tablette (appareil qui n'a jamais reçu de menu)
# sont une COPIE de base.MOTIFS : une copie dérive sans bruit. Le 30/09/2026,
# ENTRETIEN et FORMATION manquaient à la tablette hors ligne depuis leur ajout.
from rhi.base import MOTIFS  # noqa: E402
terrain = (PUB / "terrain.js").read_text()
secours = dict(re.findall(r"\{code: '(\w+)', libelle: '([^']*)'\}",
                          terrain[terrain.index("MOTIFS_SECOURS = ["):terrain.index("];", terrain.index("MOTIFS_SECOURS = ["))]))
verif(secours == MOTIFS, f"terrain.js MOTIFS_SECOURS ≠ base.MOTIFS : {set(MOTIFS) ^ set(secours) or 'libellés'}")

fin("banc-ecran")
