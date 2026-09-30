"""Le courrier : la marche en avant du lundi, envoyée à 7 h.

Mêmes variables que dans Ali Baba (SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASS, MAIL_FROM), pour qu'un seul réglage Clever Cloud serve aux deux.
Les destinataires : RHI_MARCHE_A, adresses séparées par des virgules.

Contrat de retour, celui d'Ali Baba : « envoye », « simule » (SMTP non
réglé : rien ne part, et on le dit), ou « erreur: … ». Le transport est une
variable du module : les bancs la remplacent, aucun banc ne poste.
"""
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def reglage() -> dict:
    return {"host": os.getenv("SMTP_HOST", ""), "port": int(os.getenv("SMTP_PORT", "587")),
            "user": os.getenv("SMTP_USER", ""), "pass": os.getenv("SMTP_PASS", ""),
            "de": os.getenv("MAIL_FROM", "rhi@groupe-alma.fr")}


def destinataires() -> list:
    return [a.strip() for a in os.getenv("RHI_MARCHE_A", "").split(",") if a.strip()]


def _smtp(dests: list, sujet: str, texte: str, piece_nom: str, piece: bytes) -> str:
    r = reglage()
    if not (r["host"] and r["user"]):
        return "simule"
    try:
        m = MIMEMultipart("mixed")
        m["Subject"], m["From"], m["To"] = sujet, r["de"], ", ".join(dests)
        m.attach(MIMEText(texte, "plain", "utf-8"))
        pj = MIMEApplication(piece)
        pj.add_header("Content-Disposition", "attachment", filename=piece_nom)
        m.attach(pj)
        with smtplib.SMTP(r["host"], r["port"], timeout=40) as srv:
            srv.starttls()
            srv.login(r["user"], r["pass"])
            srv.sendmail(r["de"], dests, m.as_string())
        return "envoye"
    except Exception as e:  # le serveur de courrier ne doit jamais faire tomber RHI
        return f"erreur: {str(e)[:120]}"


transport = _smtp


def envoyer(sujet: str, texte: str, piece_nom: str, piece: bytes) -> str:
    dests = destinataires()
    if not dests:
        return "sans destinataire"
    return transport(dests, sujet, texte, piece_nom, piece)
