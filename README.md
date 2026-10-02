# RHI — Relevé Hebdomadaire Individuel

Le pointage des heures par affaire de **VIP Plus** (serrurerie) et **Alfa**
(menuiserie), Groupe Alma — une instance par entreprise. Chaque heure de
l'atelier et de la pose tombe sur son numéro d'affaire (CH), pour que le point
d'affaire et la rentabilité se lisent enfin sans estimation.

- **Atelier** : une tablette par poste. Je touche mon nom, je touche mon
  chantier (ceux du planning du jour en tête), le chrono tourne. Toucher un
  autre chantier arrête le premier. « J'arrête » en fin de tâche.
- **Pose** : le téléphone du chef d'équipe, qui pointe pour lui et son binôme.
- **Sans réseau** : on pointe quand même ; les gestes partent au retour du
  réseau, à l'heure où ils ont été faits.
- **Écran de l'atelier** (`/ecran`) : alterne l'atelier du jour (qui pointe
  quoi), la pose de la semaine et les envois en traitement de surface.
- **Bureau** (`/bureau`) : le RHI de chacun (jour × CH, export Excel,
  validation de la semaine), les pointages à vérifier, le point d'affaire
  (heures, coût de main-d'œuvre, vendu HT), la marche en avant (chaque pose
  face à ses études, sa fab et son traitement, et sa synthèse en Markdown),
  les personnes, l'aperçu de ce qui partirait vers InterFast, les plannings,
  la sauvegarde.
- **InterFast** en lecture seule : chantiers, comptes, devis signés
  (`docs/interfast.md`).

Guide des utilisateurs : `/mode-emploi.html`. Mise en ligne :
`docs/deploiement.md`. Suite : `docs/feuille-de-route.md`.

## Démarrer

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 9000
```

Puis <http://localhost:9000/bureau> → onglet **Plannings** : déposer le
planning ATE et le planning POSE SER. La tablette est sur
<http://localhost:9000/>.

## Réglages (environnement)

| Variable | Rôle |
|---|---|
| `RHI_ENTREPRISE` | `VIP` (serrurerie, par défaut) ou `ALFA` (menuiserie) : une instance par entreprise |
| `RHI_DONNEES` | dossier de la base (`donnees/` par défaut ; `/donnees` sur Clever Cloud) |
| `RHI_CODE_TERRAIN` | code des tablettes et téléphones |
| `RHI_CODE_BUREAU` | code du bureau (voit tout) |
| `RHI_CH_FRAIS_GENERAUX` | CH InterFast du hors affaire (défaut VIP : `CH00081`) |
| `RHI_CH_DIVERS` | CH InterFast des interventions sans numéro d'affaire ; vide = pas proposé sur la tablette |
| `RHI_COUT_HORAIRE` | taux horaire moyen (€/h) quand une personne n'a pas le sien |
| `RHI_MARCHE_A` | destinataires de la synthèse marche en avant (adresses séparées par des virgules) — l'envoi du lundi est éteint depuis la revue du 01/10 : la marche en avant part chez un agent à part |
| `RHI_PLANNINGS_URL` | liens de **téléchargement direct** des plannings ATE et POSE (séparés par des virgules ou des retours à la ligne) : RHI les relit tout seul ; vide = dépôt à la main |
| `RHI_PLANNINGS_MINUTES` | tous les combien RHI relit ces liens (5 par défaut) |
| `RHI_HEURES_JOUR` | la journée normale, du lundi au vendredi (`8,8,8,8,7` par défaut) : base des écarts du RHI |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_FROM` | le serveur de courrier, mêmes noms que dans Ali Baba ; absent = rien ne part |
| `INTERFAST_VIP` / `INTERFAST_ALFA` | clé InterFast de l'entreprise de l'instance — jamais dans le dépôt |

## Bancs

```bash
sh bancs/tous.sh
```

Voir `CLAUDE.md` pour les règles du projet et `docs/` pour la suite.
