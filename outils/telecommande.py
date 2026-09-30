"""La télécommande : régler RHI sur Clever Cloud sans poste ni console.

Lancée par la chaîne GitHub (.github/workflows/telecommande.yml, bouton
« Run workflow »), avec les identifiants Clever déjà rangés dans les secrets
du dépôt. Née le 30/09/2026 : recopier les réglages du courrier d'une
console à l'autre, à la main, a coûté trois allers-retours pour une ligne
oubliée — une machine recopie sans oublier.

Le dépôt est PUBLIC, les journaux des runs aussi : cet outil n'écrit JAMAIS
une valeur. Il dit des noms (« SMTP_PASS : réglé »), jamais ce qu'il y a
derrière ; les valeurs qu'il manipule passent par l'environnement du
processus (`clever env import-vars`), pas par la ligne de commande, et sont
masquées dans le journal avant tout usage.

Gestes :
  etat       ce qui est réglé sur RHI (noms seulement), et ce qu'Ali Baba a
             pour le courrier
  courrier   recopie SMTP_* et MAIL_FROM d'Ali Baba vers RHI, puis redémarre
  redemarrer redémarre RHI (les variables ne s'appliquent qu'au redémarrage)
  nettoyer   retire de RHI les variables qu'il ne lit pas (le 30/09/2026, tout
             le réglage d'Ali Baba y avait été collé : sa clé Anthropic, ses
             clés InterFast des autres sociétés…) et remet en place la commande
             de lancement et le bucket de RHI s'ils ne sont plus les siens
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
CLEVER = os.environ.get("CLEVER", "clever")
ALIBABA = os.environ.get("ALIBABA", "app_fa770bf7-8ea1-4e5f-9312-1bd36e467cb5")
COURRIER = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_FROM")
ATTENDUES = ("RHI_CODE_TERRAIN", "RHI_CODE_BUREAU", "RHI_MARCHE_A",
             "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "INTERFAST_VIP")
FACULTATIVES = ("SMTP_PORT", "MAIL_FROM", "RHI_CH_DIVERS", "RHI_CH_FRAIS_GENERAUX",
                "RHI_COUT_HORAIRE", "RHI_ENTREPRISE", "RHI_DONNEES", "RHI_PRODUCTION")
# Ce que Clever lit pour lancer RHI (docs/deploiement.md, § 3). Pas des secrets.
LANCEMENT = {"CC_RUN_COMMAND": "uvicorn app:app --host 0.0.0.0 --port 9000", "CC_PYTHON_VERSION": "3.12"}
# Tout ce que RHI lit : le reste, sur RHI, ne sert à rien — et une clé qui ne
# sert à rien est une clé qui fuit pour rien.
UTILES = set(ATTENDUES) | set(FACULTATIVES) | set(LANCEMENT) | {"CC_FS_BUCKET"}


def conf() -> dict:
    """outils/clever.conf, la seule copie des identifiants de l'application."""
    return dict(re.findall(r"^([A-Z_]+)=(\S+)", (ICI / "clever.conf").read_text(), re.M))


def dire(texte: str = ""):
    print(texte, flush=True)
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a") as f:
            f.write(texte + "\n")


def masquer(valeur: str):
    """Demande à GitHub de cacher la valeur partout dans le journal."""
    if os.environ.get("GITHUB_ACTIONS"):
        for ligne in valeur.splitlines() or [valeur]:
            if ligne.strip():
                print(f"::add-mask::{ligne}", flush=True)


def clever(*args, env=None) -> str:
    r = subprocess.run([CLEVER, *args], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        # La sortie d'erreur de clever ne porte pas de valeur de variable ;
        # on n'en garde que la fin, qui dit pourquoi.
        raise SystemExit(f"❌ clever {args[0]} {args[1] if len(args) > 1 else ''} a échoué : "
                         + (r.stderr.strip() or r.stdout.strip()).splitlines()[-1][:200])
    return r.stdout


def lire(app: str) -> dict:
    return json.loads(clever("env", "--app", app, "--format", "json"))


def variables(app: str) -> dict:
    """Les variables posées à la main sur une application : {nom: valeur}."""
    return {v["name"]: v.get("value") or "" for v in lire(app).get("env", [])}


def bucket_attendu(app: str) -> str:
    """/donnees:<hôte du FS Bucket relié à CETTE application>, ou '' sans bucket."""
    for addon in lire(app).get("fromAddons", []):
        for v in addon.get("env") or []:
            if v.get("name") == "BUCKET_HOST" and v.get("value"):
                return "/donnees:" + v["value"]
    return ""


def diagnostic(rhi: str, v: dict) -> dict:
    """Ce qui ne va pas dans les réglages de RHI, sans jamais dire une valeur
    secrète (la commande de lancement n'en est pas une : elle est dans la doc)."""
    a = variables(ALIBABA)
    bucket = bucket_attendu(rhi)
    d = {"inutiles": sorted(n for n in v if n not in UTILES),
         "lancement": {n: attendu for n, attendu in LANCEMENT.items() if v.get(n) != attendu},
         "bucket": bool(bucket) and v.get("CC_FS_BUCKET") != bucket, "bucket_valeur": bucket,
         "bucket_alibaba": bool(v.get("CC_FS_BUCKET")) and v.get("CC_FS_BUCKET") == a.get("CC_FS_BUCKET")}
    return d


def etat(rhi: str) -> dict:
    v = variables(rhi)
    dire("### Réglages de RHI")
    for nom in ATTENDUES:
        dire(f"- {'✅' if v.get(nom) else '❌'} `{nom}` : {'réglé' if v.get(nom) else 'MANQUANT'}")
    for nom in FACULTATIVES:
        if nom in v:
            dire(f"- ✅ `{nom}` : {'réglé' if v[nom] else 'vide'}")
    d = diagnostic(rhi, v)
    dire("### Lancement")
    for n, attendu in LANCEMENT.items():
        dire(f"- {'✅' if n not in d['lancement'] else '❌'} `{n}` : "
             + ("conforme" if n not in d["lancement"] else f"« {v.get(n, '')} », attendu « {attendu} »"))
    dire(f"- {'❌' if d['bucket'] else '✅'} `CC_FS_BUCKET` : "
         + ("le bucket d'ALI BABA" if d["bucket_alibaba"] else "pas celui de RHI" if d["bucket"]
            else "le bucket de RHI" if d["bucket_valeur"] else "aucun bucket relié à RHI trouvé"))
    if d["inutiles"]:
        dire(f"- ⚠️ inutiles à RHI (geste « nettoyer ») : {', '.join(f'`{n}`' for n in d['inutiles'])}")
    a = variables(ALIBABA)
    dire("### Courrier chez Ali Baba")
    dire(", ".join(f"`{n}` {'✅' if a.get(n) else '❌'}" for n in COURRIER))
    return v


def courrier(rhi: str):
    a = variables(ALIBABA)
    manque = [n for n in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS") if not a.get(n)]
    if manque:
        raise SystemExit(f"❌ Ali Baba n'a pas {', '.join(manque)} : rien à recopier. "
                         "Il faut un compte d'envoi (voir docs/deploiement.md).")
    noms = [n for n in COURRIER if a.get(n)]
    env = dict(os.environ)
    for n in noms:
        masquer(a[n])
        env[n] = a[n]
    clever("env", "import-vars", ",".join(noms), "--app", rhi, env=env)
    dire(f"✅ Recopiés d'Ali Baba vers RHI : {', '.join(f'`{n}`' for n in noms)}")
    redemarrer(rhi)


def nettoyer(rhi: str):
    d = diagnostic(rhi, variables(rhi))
    for n in d["inutiles"]:
        clever("env", "rm", n, "--app", rhi)
    if d["inutiles"]:
        dire(f"🧹 Retirés de RHI : {', '.join(f'`{n}`' for n in d['inutiles'])}")
    for n, attendu in d["lancement"].items():
        clever("env", "set", n, attendu, "--app", rhi)
        dire(f"✅ `{n}` remis à « {attendu} »")
    if d["bucket"]:
        masquer(d["bucket_valeur"])
        clever("env", "import-vars", "CC_FS_BUCKET", "--app", rhi,
               env=dict(os.environ, CC_FS_BUCKET=d["bucket_valeur"]))
        dire("✅ `CC_FS_BUCKET` remis sur le bucket de RHI")
    if d["lancement"] or d["bucket"]:
        redemarrer(rhi)
    elif not d["inutiles"]:
        dire("Rien à nettoyer.")


def redemarrer(rhi: str):
    clever("restart", "--app", rhi, "--quiet")
    dire("🔄 RHI redémarre : les variables s'appliquent au redémarrage (une à deux minutes).")


if __name__ == "__main__":
    geste = sys.argv[1] if len(sys.argv) > 1 else "etat"
    gestes = {"etat": etat, "courrier": courrier, "redemarrer": redemarrer, "nettoyer": nettoyer}
    if geste not in gestes:
        raise SystemExit(f"geste inconnu : {geste} ({', '.join(gestes)})")
    rhi = conf()["APP_VIP"]
    gestes[geste](rhi)
    if geste != "etat":
        etat(rhi)
