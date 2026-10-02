// L'écran du mur de l'atelier (demande d'Alexis, réunion du 29/09/2026) :
// « un écran relié au planning, qui se met à jour en permanence, et qui
// passe de la pose à l'atelier ». Il alterne deux vues toutes les 15 s et
// relit le serveur toutes les 30 s. Lecture seule : il ne pointe jamais.

const JOURS_ECRAN = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi'];
const VUE_MS = 15000;
const RELECTURE_MS = 30000;
let donnees = null, vueCourante = 0, ecartMs = 0;

async function relire() {
  try {
    donnees = await api('/api/ecran');
    ecartMs = donnees.maintenant_ms - Date.now();
    dessiner();
  } catch (e) {
    $('#titre').textContent = 'Serveur injoignable — nouvel essai dans 30 s';
  }
}

// Revue du 01/10/2026 : « je ne veux pas ce qu'ils sont en train de faire,
// je veux le planning de la semaine, comme on les a habitués » — une ligne
// par poste (par équipe en pose), une colonne par jour, la couleur de l'Excel.
const VUES = [vueAtelier, vuePose, vueTraitement];

function dessiner() {
  if (!donnees) return;
  // La vue traitement ne passe que si la semaine a des envois.
  const vues = (donnees.traitement || []).length ? VUES : VUES.slice(0, 2);
  vues[vueCourante % vues.length]();
}

function vueTraitement() {
  $('#titre').textContent = 'Traitement de surface · cette semaine';
  const date = (iso) => iso.slice(8, 10) + '/' + iso.slice(5, 7);
  $('#vue').innerHTML = `<div class="mur">${donnees.traitement.map((t) => `
    <div class="poste"><div class="qui">${esc(t.libelle)}</div>
      <div class="ch">${esc(t.ch)}</div>
      <div class="live">${t.debut === t.fin ? esc(date(t.debut)) : esc(date(t.debut)) + ' → ' + esc(date(t.fin))}</div>
    </div>`).join('')}</div>`;
}

// Un fond foncé appelle un texte blanc : la couleur vient de l'Excel, on ne la choisit pas.
function encre(fond) {
  if (!/^#[0-9A-F]{6}$/i.test(fond || '')) return '';
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(fond.slice(i, i + 2), 16));
  return (0.299 * r + 0.587 * g + 0.114 * b) < 140 ? '#fff' : '#1a1a1a';
}

function caseSemaine(x) {
  const fond = /^#[0-9A-F]{6}$/i.test(x.couleur || '') ? x.couleur : '';
  const morceaux = x.libelle.split(' / ');
  const nom = x.chantier || morceaux[0] || x.libelle;
  // Le libellé de l'Excel commence souvent par le nom du chantier : pas deux fois.
  const pareil = (a, b) => a.trim().toUpperCase() === b.trim().toUpperCase();
  const detail = (pareil(morceaux[0], nom) ? morceaux.slice(1) : morceaux).join(' · ');
  return `<div class="tache" style="${fond ? `background:${esc(fond)};color:${esc(encre(fond))}` : ''}">
    <div class="nom">${esc(nom)}</div>
    ${detail ? `<div class="detail">${esc(detail)}</div>` : ''}
    <div class="ref">${esc([x.ch, x.conduc].filter(Boolean).join(' · '))}</div></div>`;
}

function grilleSemaine(titre, bandes) {
  const sem = donnees.semaine;
  $('#titre').textContent = titre;
  const maintenant = Date.now() + ecartMs;
  $('#vue').innerHTML = bandes.length ? `<table class="semaine">
    <tr><th></th>${sem.jours.map((j, i) => `<th class="${j === donnees.jour ? 'aujourdhui' : ''}">
      ${esc(JOURS_ECRAN[i])} ${esc(j.slice(8, 10))}/${esc(j.slice(5, 7))}</th>`).join('')}</tr>
    ${bandes.map((b) => `<tr>
      <th class="qui">${esc(b.nom)}${b.en_cours ? `<div class="live">⏱ ${esc(b.en_cours.ch || b.en_cours.motif)}
        · ${esc(duree((maintenant - msDeParis(b.en_cours.debut)) / 1000).slice(0, -3))}</div>` : ''}</th>
      ${b.cases.map((cs, i) => `<td class="${sem.jours[i] === donnees.jour ? 'aujourdhui' : ''}">
        ${cs.map(caseSemaine).join('')}</td>`).join('')}
    </tr>`).join('')}
  </table>` : '<div class="rien">Pas de planning cette semaine : le bureau dépose le planning.</div>';
}

function vueAtelier() { grilleSemaine('Atelier · la semaine', donnees.semaine.atelier); }
function vuePose() { grilleSemaine('Pose · la semaine', donnees.semaine.pose); }

function horloge() {
  $('#horloge').textContent = isoParis(Date.now() + ecartMs).slice(11, 16);
}

setInterval(() => { vueCourante += 1; dessiner(); }, VUE_MS);
setInterval(relire, RELECTURE_MS);
setInterval(horloge, 1000);
horloge();
relire();
