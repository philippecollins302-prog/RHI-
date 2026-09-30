# Questions pour Alexis — à envoyer par mail

*Préparées pendant l'écriture de la V1 (29/09/2026), comme demandé en fin de
réunion. Chaque question bloque ou oriente un choix précis ; la réponse par
défaut retenue en attendant est indiquée.*

---

**Objet : RHI — 10 questions pour caler le pointage atelier et pose**

Bonjour Alexis,

La première version de RHI tourne : les gars touchent leur nom, leur
chantier (ceux de ton planning du jour arrivent en tête), et le chrono
tourne. Pour la caler sur ta réalité, il nous manque tes réponses à ces
questions. Une ligne par réponse suffit.

### Qui pointe
1. **Qui pointe à l'atelier ?** Dans ton planning FAB, on lit 8 noms dans la
   colonne du samedi. Est-ce la bonne liste ? Le plieur (qui « fait trop de
   chantiers ») est-il bien exclu, et ses heures vont-elles sur tes frais ?
   *En attendant : tous les noms du planning FAB pointent, le bureau peut en
   masquer.*
2. **Combien de postes, donc de tablettes ?** Tu parlais de quatre. Un poste =
   une tablette partagée par plusieurs gars, c'est bien ça ?
3. **À la pose, qui tient le téléphone ?** Le chef d'équipe pointe-t-il
   toujours pour son binôme ? Et les intérimaires : pointent-ils (sous leur
   nom, ou sous « INTÉRIM ») ?

### Ce qu'on pointe
4. **Un CH suffit-il, ou faut-il descendre à la pièce ?** Aujourd'hui on
   pointe au CH (ex. « garde-corps » et « main courante » du même CH se
   confondent). Faut-il distinguer les lignes de ton plan de charge ?
   *En attendant : au CH, le libellé du planning est gardé à côté.*
5. **Les tâches sans CH** (pliage, débit, plasma) : sur quel compte les
   met-on ? Un CH « atelier général » dans InterFast, ou les répartir ?
6. **Les motifs hors affaire** proposés : attente matière / plans, rangement,
   panne, entretien machine, trajet, formation, autre. Il en manque ? Il y en
   a de trop ?
7. **Les interventions sans numéro d'affaire** (tu disais que certaines
   n'en ont pas, « et là ça ne sert plus à rien ») : qui crée le CH, et à quel
   moment ? RHI accepte un CH tapé à la main et le signale au bureau.

### Le bureau
8. **Qui corrige les pointages le lundi matin ?** Toi, ou une assistante ?
   Faut-il qu'un chargé d'affaires (MM, LC, NC…) voie ses seules affaires ?
9. **Le point d'affaire** compare le réel au « Prévisionnel h/h » de ton plan
   de charge. Est-ce le bon prévu, ou faut-il prendre les heures vendues du
   devis (InterFast) ? Et quel taux horaire pour passer des heures aux euros ?

### InterFast
10. **Le coût horaire des gars.** Dans InterFast, les techniciens de la
    serrurerie ont un coût horaire à 0 € : sans lui, aucune rentabilité ne
    se calcule, ni dans InterFast ni dans RHI. Qui peut le renseigner (coût
    chargé par personne, ou un taux moyen atelier / pose) ?
    Et pour faire tomber les heures dans InterFast : RHI posera une case
    par chantier et par jour dans le planning, avec l'équipe ; il faudra la
    terminer puis valider la feuille de temps dans InterFast (l'API ne sait
    pas le faire). Qui s'en charge, et quand ? (`docs/interfast.md`)

### Les comptes InterFast (relevé du 29/09/2026)
11. Trois opérateurs présents dans ton planning atelier ont leur compte
    **archivé** dans InterFast, et neuf noms des plannings n'ont **aucun
    compte** (poseurs, intérimaires, libellés comme « SAV »). Qui doit en
    avoir un ? La liste nominative est dans l'onglet *Personnes* de RHI.

### Le planning TRAITEMENT
12. RHI lit tes envois en traitement de surface (case « CHANTIER - CH…/DEVIS »,
    fusionnée sur les jours chez le traiteur). Mais il ne dit pas **quelle
    pièce** part, et tes couleurs (vert clair envoyé, vert foncé livré, rose en
    retard, orange en prévision…) ne sont écrites nulle part. Peux-tu confirmer
    le code couleur, et ajouter la pièce dans la case (« COURREAU - CH00061 -
    GC X7 ») ? RHI pourra alors dire « retard de traitement » avec certitude.
    Exemple trouvé le 28/09 : un envoi de Courreau court jusqu'au 19/10, jour
    d'une pose de Courreau — même pièce ou pas ?

Merci !

---

## Réponses (deux mails, 30/09/2026)

*Sans noms de personnes : le dépôt est public. La liste nominative (qui
pointe, chargés d'affaires, RH) reste dans les mails et dans l'onglet
Personnes de RHI.*

| Sujet | Réponse | Dans RHI |
|---|---|---|
| Qui pointe à l'atelier | Quatre permanents, plus le plieur, qui pointe sur CH | — |
| Tablettes | **Cinq** à l'atelier (le plieur compris). Wi-Fi à vérifier : le réseau passe mal au BET | à l'achat |
| Intérimaires | Pointent sous leur nom sur les tablettes des permanents ; les RH ajoutent les noms (qui exactement : à trancher chez eux) | **fait** (bureau → Personnes, `banc-interim`) |
| Pose | Chaque poseur fait son RHI aujourd'hui ; demain, le téléphone du chef d'équipe pour lui et son binôme | déjà ainsi |
| Précision | Au CH, pas à l'ouvrage (l'ouvrage, plus tard, pour le retour d'expérience du chiffrage) | déjà ainsi |
| Pliage, débit, plasma | Toujours sur un CH | déjà ainsi : la tablette n'offre pas de pointage sans CH hors des motifs |
| Motifs | Rangement, entretien machine, formation, autre (à valider) — tous sur le CH des frais généraux | **fait** (`banc-motifs`) |
| CH des frais généraux | `CH00081` (« CH FG SER ») | **fait** (`RHI_CH_FRAIS_GENERAUX`) |
| Trajet | Compté dans le chantier : départ pointé, retour du soir sur le dernier chantier | **fait** (plus un motif) |
| Sans numéro d'affaire | Un « CH DIVERS », à créer dans InterFast, avec transfert des heures vers le bon CH | **fait** dès son numéro réglé (`RHI_CH_DIVERS`) ; transfert depuis « À vérifier » |
| Validation | Chaque chargé d'affaires vérifie ses chantiers et la cohérence avec le planning ; le responsable de BU vérifie le planning final général | à faire |
| Chargés d'affaires | Normalement renseignés sur chaque chantier dans InterFast (à vérifier) ; trois noms sinon | à lire dans InterFast |
| Point d'affaire | InterFast doit porter toutes les heures engagées ; le chargé d'affaires estime le reste à faire ; engagé + reste face au chiffrage = dérapage | à faire |
| Taux | Un taux atelier et un taux pose, bibliothèque InterFast ; **ce sont les heures qui comptent**, pas le taux | le coût reste secondaire |
| Affaire de test InterFast | `CH00066` | pour l'essai d'écriture |
| Synthèse du lundi | À Alexis seulement (`RHI_MARCHE_A`) | réglage Clever |
| Pose d'Assas | Approvisionnement extérieur confirmé : une pose sans trace amont le suggère désormais | **fait** |
| Lunas / MBS | Stock en avance de fabrication, en attente du GO de la maîtrise d'œuvre | — |
| Planning TRAITEMENT (pièce dans la case) | « Rien à voir avec les RHI » | abandonné |

**Deux sujets à ne pas mélanger**, dit-il : les **RHI** (le pointage) et le
**contrôle des plannings** (la marche en avant). Les deux vivent dans RHI,
mais ils se présentent séparément.

Reste sans réponse : la date de démarrage et les quinze minutes de
démonstration aux gars.
