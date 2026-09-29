# RHI — Relevé Hebdomadaire Individuel

Le pointage des heures par affaire de **VIP Plus** (serrurerie, Groupe Alma) :
chaque heure de l'atelier et de la pose tombe sur son numéro d'affaire (CH),
pour que le point d'affaire et la rentabilité se lisent enfin sans estimation.

- **Atelier** : une tablette par poste. Je touche mon nom, je touche mon
  chantier (ceux du planning du jour en tête), le chrono tourne. Toucher un
  autre chantier arrête le premier. « J'arrête » en fin de tâche.
- **Pose** : le téléphone du chef d'équipe, qui pointe pour lui et son binôme.
- **Écran de l'atelier** (`/ecran`) : sur un écran au mur, alterne toutes les
  15 s l'atelier du jour (prévu + qui pointe quoi) et la pose de la semaine.
- **Bureau** (`/bureau`) : le RHI de chacun le lundi matin (jour × CH, export
  Excel), les pointages douteux à corriger, le point d'affaire (réel face au
  prévu du plan de charge), qui pointe en ce moment, le dépôt des plannings.

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
| `RHI_COUT_HORAIRE` | taux horaire moyen (€/h) quand une personne n'a pas le sien |
| `INTERFAST_VIP` / `INTERFAST_ALFA` | clé InterFast de l'entreprise de l'instance — jamais dans le dépôt |

## Bancs

```bash
sh bancs/tous.sh
```

Voir `CLAUDE.md` pour les règles du projet et `docs/` pour la suite.
