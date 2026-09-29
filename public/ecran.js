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

function dessiner() {
  if (!donnees) return;
  (vueCourante === 0 ? vueAtelier : vuePose)();
}

function vueAtelier() {
  $('#titre').textContent = 'Atelier · aujourd\'hui';
  const maintenant = Date.now() + ecartMs;
  $('#vue').innerHTML = `<div class="mur">${donnees.atelier.map((p) => {
    const t = p.en_cours;
    return `<div class="poste ${t ? 'actif' : ''}">
      <div class="qui">${esc(p.nom)}</div>
      ${t ? `<div class="live">⏱ ${esc(t.ch || t.motif)} ${esc(t.chantier)} · ${esc(duree((maintenant - msDeParis(t.debut)) / 1000).slice(0, -3))}</div>` : ''}
      <div class="prevu">${p.prevu.length ? p.prevu.map((x) => esc(x.libelle)).join('<br>') : 'Rien au planning'}</div>
    </div>`;
  }).join('')}</div>`;
}

function vuePose() {
  $('#titre').textContent = 'Pose · cette semaine';
  $('#vue').innerHTML = `<div class="jours">${donnees.pose.map((j, i) => `
    <div class="jour ${j.jour === donnees.jour ? 'aujourdhui' : ''}">
      <h2>${esc(JOURS_ECRAN[i])} ${esc(j.jour.slice(8, 10))}/${esc(j.jour.slice(5, 7))}</h2>
      ${j.equipes.length ? j.equipes.map((e) => `<div class="equipe">
        <div class="qui">${esc(e.personnes.join(' · '))}</div>
        <div>${esc(e.libelle)}</div><div class="ch">${esc(e.ch.join(' '))}</div></div>`).join('')
        : '<div class="doux">—</div>'}
    </div>`).join('')}</div>`;
}

function horloge() {
  $('#horloge').textContent = isoParis(Date.now() + ecartMs).slice(11, 16);
}

setInterval(() => { vueCourante = 1 - vueCourante; dessiner(); }, VUE_MS);
setInterval(relire, RELECTURE_MS);
setInterval(horloge, 1000);
horloge();
relire();
