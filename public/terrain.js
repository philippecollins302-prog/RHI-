// La tablette de l'atelier, ou le téléphone du chef d'équipe de pose.
//
// Trois gestes, pas un de plus : je choisis mon nom, je touche mon chantier,
// je touche « J'arrête ». Toucher un autre chantier arrête le précédent :
// rien ne bloque, jamais (réunion du 29/09/2026). Ce qui est douteux se
// corrige au bureau.

const etat = {
  mode: lire('rhi.mode', ''),          // 'atelier' | 'pose', choisi une fois par appareil
  personnes: [],                        // qui pointe en ce moment sur cet écran
  choix: new Set(),                     // sélection en cours (pose : chef + binôme)
  ecart: 0,                             // heure du serveur - heure de l'appareil, en ms
  enCours: [],
  menu: null,
  filtre: '',
};
const APPAREIL = lire('rhi.appareil', '') || (() => {
  const id = 'app-' + Math.random().toString(36).slice(2, 8);
  ecrire('rhi.appareil', id);
  return id;
})();
// À l'atelier, la tablette est partagée : sans geste pendant une minute, elle
// revient à la liste des noms, pour que le suivant ne pointe pas sous le nom
// du précédent.
const RETOUR_MS = 60000;
let minuteur = null;

function reveil() {
  clearTimeout(minuteur);
  if (etat.mode === 'atelier' && etat.personnes.length) {
    minuteur = setTimeout(accueil, RETOUR_MS);
  }
}
document.addEventListener('pointerdown', reveil);

$('#changer').onclick = accueil;

function choisirMode() {
  $('#titre').textContent = 'RHI · Cet appareil sert à…';
  $('#changer').hidden = true;
  $('#ecran').innerHTML = `
    <div class="grille">
      <button class="gros" data-mode="atelier">🏭 L'atelier<small>Une tablette sur pied, chacun pointe à son nom</small></button>
      <button class="gros" data-mode="pose">🚚 La pose<small>Le téléphone du chef d'équipe, pour lui et son binôme</small></button>
    </div>`;
  document.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => {
    etat.mode = b.dataset.mode;
    ecrire('rhi.mode', etat.mode);
    accueil();
  });
}

async function accueil() {
  clearTimeout(minuteur);
  etat.personnes = [];
  etat.choix = new Set(etat.mode === 'pose' ? JSON.parse(lire('rhi.equipe', '[]')) : []);
  etat.filtre = '';
  $('#changer').hidden = true;
  $('#titre').textContent = etat.mode === 'pose' ? 'RHI · Qui est sur le chantier ?' : 'RHI · Qui es-tu ?';
  let liste = [], encours = [];
  try {
    [liste, encours] = await Promise.all([
      api('/api/personnes?equipe=' + etat.mode), api('/api/en-cours')]);
  } catch (e) {
    $('#ecran').innerHTML = `<div class="rien">Pas de connexion au serveur : ${esc(e.message)}.<br>
      <button onclick="accueil()">Réessayer</button></div>`;
    return;
  }
  const tourne = new Map(encours.pointages.map((p) => [p.personne, p]));
  const pose = etat.mode === 'pose';
  $('#ecran').innerHTML = `
    ${liste.length ? '' : `<div class="rien">Aucun nom pour l'instant : le bureau doit importer le planning ${esc(etat.mode)}.</div>`}
    <div class="grille">
      ${liste.map((p) => {
        const t = tourne.get(p.nom);
        return `<button class="gros ${etat.choix.has(p.nom) ? 'choisi' : ''}" data-nom="${esc(p.nom)}">
          ${esc(p.nom)}<small>${t ? '⏱ ' + esc(t.ch || t.motif) + ' ' + esc(t.chantier) : '—'}</small></button>`;
      }).join('')}
    </div>
    ${pose ? `<p><button class="valider" id="valider" style="width:100%">C'est nous → nos chantiers</button></p>` : ''}
    <p class="doux" style="margin-top:32px">Appareil ${esc(APPAREIL)} · mode ${esc(etat.mode)} ·
      <a href="#" id="remode">changer</a></p>`;
  document.querySelectorAll('[data-nom]').forEach((b) => b.onclick = () => {
    const nom = b.dataset.nom;
    if (!pose) { ouvrir([nom]); return; }
    etat.choix.has(nom) ? etat.choix.delete(nom) : etat.choix.add(nom);
    b.classList.toggle('choisi');
  });
  if (pose) $('#valider').onclick = () => {
    if (!etat.choix.size) { dire('Touche au moins un nom'); return; }
    ecrire('rhi.equipe', JSON.stringify([...etat.choix]));
    ouvrir([...etat.choix]);
  };
  $('#remode').onclick = (e) => { e.preventDefault(); ecrire('rhi.mode', ''); etat.mode = ''; choisirMode(); };
}

async function ouvrir(noms) {
  etat.personnes = noms;
  $('#titre').textContent = noms.join(' + ');
  $('#changer').hidden = false;
  reveil();
  await rafraichir();
}

async function rafraichir() {
  try {
    const [menu, encours] = await Promise.all([
      api('/api/menu?personne=' + encodeURIComponent(etat.personnes[0])),
      api('/api/en-cours')]);
    etat.menu = menu;
    etat.ecart = new Date(encours.maintenant).getTime() - Date.now();
    etat.enCours = encours.pointages.filter((p) => etat.personnes.includes(p.personne));
  } catch (e) {
    dire('Serveur injoignable : ' + e.message);
    return;
  }
  dessiner();
}

function dessiner() {
  const m = etat.menu;
  const actuel = etat.enCours[0];
  const f = etat.filtre.trim().toUpperCase();
  const autres = f.length < 2 ? [] : m.affaires.filter((a) =>
    (a.ch + ' ' + a.chantier).toUpperCase().includes(f)).slice(0, 12);
  const chSaisi = /^CH\s*\d{5}$/.test(f) && !autres.some((a) => a.ch === f.replace(/\s/g, ''));
  $('#ecran').innerHTML = `
    ${actuel ? `
      <div class="encours">
        <div class="quoi"><div class="ch">${esc(actuel.ch || 'HORS AFFAIRE')}</div>
          <strong>${esc(actuel.chantier || actuel.libelle || actuel.motif)}</strong>
          ${etat.enCours.length > 1 ? `<div class="doux">${etat.enCours.length} personnes pointent</div>` : ''}</div>
        <div class="chrono" id="chrono" data-debut="${esc(actuel.debut)}">0:00:00</div>
        <button class="stop" id="stop">J'arrête</button>
      </div>` : `<div class="rien">Rien ne tourne. Touche le chantier sur lequel tu démarres.</div>`}

    <h2>Mon planning du jour</h2>
    ${m.planning.length ? `<div class="grille">${m.planning.map((p) => `
      <button class="gros chantier" data-ch="${esc(p.ch)}" data-libelle="${esc(p.libelle)}">
        <span class="ch">${esc(p.ch)}</span><br>${esc(p.chantier || p.libelle.split(' / ')[0])}
        <small>${esc(p.libelle.split(' / ').slice(1).join(' · '))}</small></button>`).join('')}</div>`
      : `<div class="rien">Rien au planning pour aujourd'hui${m.taches_sans_ch.length ? ' (tâche sans CH : ' + esc(m.taches_sans_ch.join(', ')) + ')' : ''}. Cherche ton chantier juste en dessous.</div>`}

    <h2>Un autre chantier</h2>
    <input id="cherche" placeholder="Nom du chantier ou CH (ex. LES CIGALES, CH00906)" value="${esc(etat.filtre)}" autocomplete="off">
    <div class="grille" style="margin-top:12px">
      ${autres.map((a) => `<button class="gros chantier" data-ch="${esc(a.ch)}" data-libelle="">
        <span class="ch">${esc(a.ch)}</span><br>${esc(a.chantier || '—')}</button>`).join('')}
      ${chSaisi ? `<button class="gros chantier" data-ch="${esc(f.replace(/\s/g, ''))}" data-libelle="">
        <span class="ch">${esc(f)}</span><br>Pointer sur ce CH<small>Absent des plannings : le bureau vérifiera</small></button>` : ''}
    </div>

    <h2>Hors affaire</h2>
    <div class="grille">${m.motifs.map((x) => `
      <button class="motif" data-motif="${esc(x.code)}">${esc(x.libelle)}</button>`).join('')}</div>`;

  const champ = $('#cherche');
  champ.oninput = () => {
    etat.filtre = champ.value;
    const pos = champ.selectionStart;
    dessiner();
    const c = $('#cherche'); c.focus(); c.setSelectionRange(pos, pos);
  };
  document.querySelectorAll('[data-ch]').forEach((b) => b.onclick = () =>
    demarrer({ch: b.dataset.ch, libelle: b.dataset.libelle}));
  document.querySelectorAll('[data-motif]').forEach((b) => b.onclick = () =>
    demarrer({motif: b.dataset.motif}));
  if (actuel) $('#stop').onclick = arreter;
  tic();
}

async function demarrer(quoi) {
  try {
    await api('/api/demarrer', {method: 'POST',
      json: Object.assign({personnes: etat.personnes, appareil: APPAREIL}, quoi)});
    etat.filtre = '';
    dire('▶ C\'est parti : ' + (quoi.ch || 'hors affaire'));
    await rafraichir();
  } catch (e) { dire('Pas pointé : ' + e.message); }
}

async function arreter() {
  try {
    await api('/api/arreter', {method: 'POST', json: {personnes: etat.personnes}});
    dire('■ Arrêté');
    if (etat.mode === 'atelier') { accueil(); return; }
    await rafraichir();
  } catch (e) { dire('Pas arrêté : ' + e.message); }
}

function tic() {
  const c = $('#chrono');
  if (!c) return;
  const debut = new Date(c.dataset.debut).getTime();
  c.textContent = duree((Date.now() + etat.ecart - debut) / 1000);
}
setInterval(tic, 1000);

etat.mode ? accueil() : choisirMode();
