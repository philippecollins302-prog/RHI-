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
