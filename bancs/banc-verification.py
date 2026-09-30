"""outils/verifier-deploiement.sh contre un faux site local : il échoue FERMÉ.

Le seul « vert » admis : 200, JSON, la version du commit poussé, et prêt.
Tout le reste — ancien code encore servi, 503, JSON illisible, pas de
réponse du tout — est un échec, avec un motif qui dit ce qui a été vu.
"""
import http.server
import json
import subprocess
import threading
from pathlib import Path

from bancs.outils import fin, verif

RACINE = Path(__file__).resolve().parent.parent
reponses: list = []


class Faux(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code, corps = reponses.pop(0) if len(reponses) > 1 else reponses[0]
        self.send_response(code)
        self.end_headers()
        self.wfile.write(corps.encode())

    def log_message(self, *a):
        pass


serveur = http.server.HTTPServer(("127.0.0.1", 0), Faux)
threading.Thread(target=serveur.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{serveur.server_port}"


def verifier(suite, url=URL, attendu="c0ffee"):
    reponses[:] = suite
    return subprocess.run(["sh", str(RACINE / "outils/verifier-deploiement.sh"), attendu, url, "3"],
                          capture_output=True, text=True, env={"PAS": "1", "PATH": "/usr/bin:/bin"})


def sante(version="c0ffee", pret=True):
    return (200, json.dumps({"ok": True, "pret": pret, "codes": "ok" if pret else "à régler", "version": version}))


r = verifier([sante()])
verif(r.returncode == 0 and "c0ffee" in r.stdout, f"bonne version, prête : vert {r.stderr}")
r = verifier([(503, "Error 503"), sante("ancien"), sante()])
verif(r.returncode == 0, "503 puis l'ancien code pendant la bascule, puis le bon : vert (on attend, on ne conclut pas trop tôt)")
r = verifier([sante("ancien")])
verif(r.returncode == 1 and "l ancien code tourne encore" in r.stderr and r.stderr.startswith("MOTIF"),
      "« déployé » mais l'ancien code répond toujours : ROUGE, et le motif le dit")
r = verifier([sante(pret=False)])
verif(r.returncode == 1 and "pas prête" in r.stderr, "bonne version mais codes non réglés : rouge")
r = verifier([(503, "Error 503")])
verif(r.returncode == 1 and "HTTP 503" in r.stderr, "503 jusqu'au bout : rouge (le 01/09 d'Ali Baba)")
r = verifier([(200, "<html>page de garde</html>")])
verif(r.returncode == 1 and "pas du JSON" in r.stderr, "200 qui n'est pas la santé de RHI : rouge")
r = verifier([(200, json.dumps({"ok": True, "pret": True}))])
verif(r.returncode == 1 and "None" in r.stderr, "pas de champ version : rouge, jamais « on suppose que c'est bon »")
serveur.shutdown()
r = verifier([sante()], url="http://127.0.0.1:9")
verif(r.returncode == 1 and "MOTIF" in r.stderr, "personne ne répond : rouge")
r = subprocess.run(["sh", str(RACINE / "outils/verifier-deploiement.sh")], capture_output=True, text=True)
verif(r.returncode == 2, "sans commit attendu : refus, pas de vert par défaut")

fin("banc-verification")
