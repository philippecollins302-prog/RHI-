// Le bureau : le RHI du lundi matin, les corrections, le point d'affaire.

const JOURS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const vue = {onglet: lire('rhi.onglet', 'rhi'), semaine: '', personne: ''};

function lundiDe(d) {
  const x = new Date(d); const j = (x.getDay() + 6) % 7;
  x.setDate(x.getDate() - j);
  return x.toISOString().slice(0, 10);
}
vue.semaine = lundiDe(new Date());

document.querySelectorAll('[data-onglet]').forEach((b) => b.onclick = () => {
  vue.onglet = b.dataset.onglet; ecrire('rhi.onglet', vue.onglet); afficher();
});

function choixSemaine() {
  return `<div class="ligne" style="margin-bottom:16px">
    <label>Semaine du <input type="date" id="semaine" value="${esc(vue.semaine)}"></label>
    <a class="btn" href="/api/rhi.csv?semaine=${esc(vue.semaine)}" id="csv">⬇ Tout le RHI en CSV (Excel)</a>
  </div>`;
}
function brancherSemaine() {
  const s = $('#semaine');
  if (s) s.onchange = () => { vue.semaine = lundiDe(s.value); afficher(); };
  // Un lien simple n'enverrait pas le code d'accès : on télécharge via api().
  const c = $('#csv');
  if (c) c.onclick = async (e) => {
    e.preventDefault();
    try {
      const texte = await api(c.getAttribute('href'));
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([texte], {type: 'text/csv'}));
      a.download = `RHI-${vue.semaine}.csv`;
      a.click();
    } catch (err) { dire(err.message); }
  };
}

async function afficher() {
  document.querySelectorAll('[data-onglet]').forEach((b) =>
    b.classList.toggle('actif', b.dataset.onglet === vue.onglet));
  $('#vue').innerHTML = '<p class="doux">Chargement…</p>';
  try {
    await ({rhi: ongletRhi, verifier: ongletVerifier, affaires: ongletAffaires,
            direct: ongletDirect, plannings: ongletPlannings}[vue.onglet] || ongletRhi)();
  } catch (e) {
    $('#vue').innerHTML = `<div class="rien">Erreur : ${esc(e.message)}</div>`;
  }
}

// ── RHI : une carte par personne, une ligne par CH, une colonne par jour ──
async function ongletRhi() {
  const d = await api('/api/rhi?semaine=' + vue.semaine);
  const pleins = d.releves.filter((r) => r.total > 0);
  const vides = d.releves.filter((r) => r.total === 0).map((r) => r.personne);
  $('#vue').innerHTML = choixSemaine() + (pleins.length ? '' :
      '<div class="rien">Aucune heure pointée cette semaine.</div>') +
    pleins.map((r) => `
    <div class="carte">
      <strong style="font-size:20px">${esc(r.personne)}</strong>
      <span class="doux"> · ${heures(r.total)} dont ${heures(r.hors_affaire) || '0h'} hors affaire</span>
      ${r.a_verifier ? `<span class="pastille p-ambre">${r.a_verifier} à vérifier</span>` : ''}
      <div class="defile"><table>
        <tr><th>CH</th><th>Chantier / motif</th>${JOURS.map((j) => `<th class="n">${j}</th>`).join('')}<th class="n">Total</th></tr>
        ${r.lignes.map((l) => `<tr><td class="ch">${esc(l.ch || '—')}</td><td>${esc(l.libelle)}</td>
          ${l.jours.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n"><strong>${heures(l.total)}</strong></td></tr>`).join('')}
        <tr class="total"><td></td><td>Total</td>${r.par_jour.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n">${heures(r.total)}</td></tr>
      </table></div>
    </div>`).join('') +
    (vides.length ? `<p class="doux">Rien pointé cette semaine : ${esc(vides.join(', '))}</p>` : '');
  brancherSemaine();
}

// ── À vérifier : les pointages douteux, corrigeables sur place ──
async function ongletVerifier() {
  const d = await api('/api/rhi?semaine=' + vue.semaine);
  const douteux = d.releves.flatMap((r) => r.pointages.filter((p) => p.alertes.length));
  $('#vue').innerHTML = choixSemaine() + (douteux.length ? `
    <div class="defile"><table>
      <tr><th>Qui</th><th>CH / motif</th><th>Début</th><th>Fin</th><th class="n">Durée</th><th>Pourquoi</th><th></th></tr>
      ${douteux.map((p) => `<tr data-id="${p.id}">
        <td>${esc(p.personne)}</td>
        <td><input value="${esc(p.ch || '')}" data-champ="ch" placeholder="${esc(p.motif || 'CH…')}" style="width:130px"></td>
        <td><input type="datetime-local" value="${esc(p.debut.slice(0, 16))}" data-champ="debut"></td>
        <td><input type="datetime-local" value="${esc((p.fin || '').slice(0, 16))}" data-champ="fin"></td>
        <td class="n">${heures(p.heures)}</td>
        <td>${p.alertes.map((a) => `<span class="pastille p-ambre">${esc(a)}</span>`).join(' ')}</td>
        <td><button data-enregistrer>Corriger</button> <button data-annuler>Annuler</button></td>
      </tr>`).join('')}
    </table></div>` : '<div class="rien">Rien à vérifier cette semaine.</div>');
  brancherSemaine();
  document.querySelectorAll('[data-enregistrer]').forEach((b) => b.onclick = async () => {
    const tr = b.closest('tr'); const corps = {};
    tr.querySelectorAll('[data-champ]').forEach((i) => { if (i.value) corps[i.dataset.champ] = i.value; });
    try { await api('/api/pointages/' + tr.dataset.id, {method: 'PATCH', json: corps}); dire('Corrigé'); afficher(); }
    catch (e) { dire(e.message); }
  });
  document.querySelectorAll('[data-annuler]').forEach((b) => b.onclick = async () => {
    if (!confirm('Annuler ce pointage ? Il ne comptera plus nulle part.')) return;
    const tr = b.closest('tr');
    try { await api('/api/pointages/' + tr.dataset.id, {method: 'PATCH', json: {annule: 1}}); afficher(); }
    catch (e) { dire(e.message); }
  });
}

// ── Point d'affaire : réel face au prévu du plan de charge ──
async function ongletAffaires() {
  const liste = await api('/api/affaires');
  $('#vue').innerHTML = `
    <p class="doux">Heures réelles pointées face aux heures prévues du plan de charge atelier
      (fabrication seulement : la pose n'a pas de prévu chiffré dans les plannings).</p>
    <div class="defile"><table>
      <tr><th>CH</th><th>Chantier</th><th>Conduc.</th><th class="n">Réel</th><th class="n">Prévu fab</th><th class="n">Consommé</th></tr>
      ${liste.map((a) => {
        const p = a.consomme_pct;
        const cl = p === null ? '' : p > 100 ? 'p-rouge' : p > 80 ? 'p-ambre' : 'p-vert';
        return `<tr><td><a href="#" data-ch="${esc(a.ch)}" class="ch">${esc(a.ch)}</a></td><td>${esc(a.chantier)}</td>
          <td>${esc(a.conduc)}</td><td class="n">${heures(a.heures_reelles) || '—'}</td>
          <td class="n">${a.heures_prevues ? heures(a.heures_prevues) : '—'}</td>
          <td class="n">${p === null ? '' : `<span class="pastille ${cl}">${p} %</span>`}</td></tr>`;
      }).join('')}
    </table></div><div id="detail"></div>`;
  document.querySelectorAll('[data-ch]').forEach((a) => a.onclick = async (e) => {
    e.preventDefault();
    const d = await api('/api/affaires/' + a.dataset.ch);
    $('#detail').innerHTML = `<div class="carte" style="margin-top:16px">
      <div class="ch">${esc(d.ch)}</div><strong style="font-size:20px">${esc(d.chantier)}</strong>
      <p>${heures(d.heures_reelles) || '0h'} pointées${d.heures_prevues ? ' sur ' + heures(d.heures_prevues) + ' prévues' : ''}.
        ${d.heures_en_suspens ? `<span class="pastille p-ambre">${heures(d.heures_en_suspens)} en suspens : arrêt oublié à corriger (onglet À vérifier)</span>` : ''}</p>
      <div class="ligne" style="align-items:flex-start">
        <table><tr><th>Qui</th><th class="n">Heures</th></tr>${Object.entries(d.par_personne).map(([k, v]) =>
          `<tr><td>${esc(k)}</td><td class="n">${heures(v)}</td></tr>`).join('')}</table>
        <table><tr><th>Semaine</th><th class="n">Heures</th></tr>${Object.entries(d.par_semaine).map(([k, v]) =>
          `<tr><td>${esc(k)}</td><td class="n">${heures(v)}</td></tr>`).join('')}</table>
        <table><tr><th>Prévu au plan de charge</th><th class="n">h</th></tr>${d.lignes_prevues.map((l) =>
          `<tr><td>${esc(l.designation)}</td><td class="n">${l.heures ?? '—'}</td></tr>`).join('')}</table>
      </div></div>`;
    $('#detail').scrollIntoView();
  });
}

// ── En ce moment : qui pointe sur quoi ──
async function ongletDirect() {
  const d = await api('/api/en-cours');
  const now = new Date(d.maintenant).getTime();
  $('#vue').innerHTML = d.pointages.length ? `<table>
    <tr><th>Qui</th><th>CH</th><th>Chantier / motif</th><th>Depuis</th><th class="n">Durée</th></tr>
    ${d.pointages.map((p) => `<tr><td>${esc(p.personne)}</td><td class="ch">${esc(p.ch || '—')}</td>
      <td>${esc(p.chantier || p.libelle || p.motif)}</td><td>${esc(p.debut.slice(11, 16))}</td>
      <td class="n">${duree((now - new Date(p.debut).getTime()) / 1000)}</td></tr>`).join('')}
  </table>` : '<div class="rien">Personne ne pointe en ce moment.</div>';
}

// ── Plannings : le dépôt des Excel d'Alexis ──
async function ongletPlannings() {
  $('#vue').innerHTML = `
    <div class="carte">
      <p>Déposez le <strong>planning ATE</strong> (atelier) et le <strong>planning POSE SER</strong>.
        RHI en tire les noms, « mes chantiers du jour » de chacun et les heures prévues par CH.
        Chaque dépôt remplace le précédent du même type ; les heures pointées ne sont jamais touchées.</p>
      <input type="file" id="fichiers" accept=".xlsx" multiple>
      <div id="resultats" style="margin-top:12px"></div>
    </div>
    <div class="carte">
      <p><strong>InterFast</strong> : relit tous les chantiers (CH, client, statut). Lecture seule —
        rien n'est écrit dans InterFast. Un chantier « Terminé » n'est plus proposé sur les tablettes.</p>
      <button id="synchro">Relire les chantiers InterFast</button>
      <div id="synchro-res" style="margin-top:12px"></div>
    </div>`;
  $('#synchro').onclick = async () => {
    const sortie = $('#synchro-res');
    sortie.textContent = 'Lecture en cours (une vingtaine de pages)…';
    try {
      const r = await api('/api/interfast/chantiers', {method: 'POST'});
      sortie.innerHTML = `<span class="pastille p-vert">✓</span> ${esc(r.chantiers)} chantiers lus.` +
        (r.absents_d_interfast.length ? ` <span class="pastille p-ambre">CH inconnus d'InterFast :
          ${esc(r.absents_d_interfast.join(', '))}</span>` : ' Tous les CH de RHI existent dans InterFast.');
    } catch (err) {
      sortie.innerHTML = `<span class="pastille p-rouge">✗</span> ${esc(err.message)}`;
    }
  };
  $('#fichiers').onchange = async (e) => {
    const sortie = $('#resultats'); sortie.innerHTML = '';
    for (const f of e.target.files) {
      const corps = new FormData(); corps.append('fichier', f);
      try {
        const r = await api('/api/plannings', {method: 'POST', body: corps});
        sortie.innerHTML += `<p><span class="pastille p-vert">✓</span> ${esc(f.name)} : planning ${esc(r.nature)},
          ${r.personnes} personnes, ${r.affectations} affectations.</p>`;
      } catch (err) {
        sortie.innerHTML += `<p><span class="pastille p-rouge">✗</span> ${esc(f.name)} : ${esc(err.message)}</p>`;
      }
    }
  };
}

afficher();
