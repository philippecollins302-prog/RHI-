// Le bureau : le RHI du lundi matin, les corrections, le point d'affaire.

const JOURS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const vue = {onglet: lire('rhi.onglet', 'rhi'), semaine: '', personne: ''};

fetch('/api/config').then((r) => r.json()).then((c) => {
  $('#titre-bureau').textContent = 'RHI · Bureau — ' + c.nom;
}).catch(() => { /* le titre générique suffit */ });

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
    await ({chantiers: ongletChantiers, rhi: ongletRhi, verifier: ongletVerifier, affaires: ongletAffaires,
            direct: ongletDirect, plannings: ongletPlannings,
            personnes: ongletPersonnes, envois: ongletEnvois, marche: ongletMarche}[vue.onglet] || ongletRhi)();
  } catch (e) {
    $('#vue').innerHTML = `<div class="rien">Erreur : ${esc(e.message)}</div>`;
  }
}

// ── Mes chantiers : le premier étage, le contrôle du chargé d'affaires ──
async function ongletChantiers() {
  const moi = lire('rhi.conduc', '');
  const d = await api('/api/chantiers?semaine=' + vue.semaine + (moi ? '&conduc=' + encodeURIComponent(moi) : ''));
  const jour = (iso) => JOURS[(new Date(iso + 'T12:00:00').getDay() + 6) % 7];
  $('#vue').innerHTML = choixSemaine() + `
    <div class="carte">
      <label>Chargé d'affaires <select id="conduc"><option value="">— tous —</option>
        ${d.conducs.map((c) => `<option ${c === moi ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
      <span class="doux">Chacun contrôle ses chantiers ; le responsable de BU valide ensuite les RHI.</span>
      ${d.a_controler ? `<span class="pastille p-ambre">${esc(d.a_controler)} à contrôler</span>` : '<span class="pastille p-vert">tout est contrôlé</span>'}
    </div>` + (d.chantiers.length ? d.chantiers.map((c) => `
    <div class="carte">
      <span class="ch">${esc(c.ch)}</span> <strong>${esc(c.chantier || '—')}</strong>
      <span class="doux">· ${esc(c.conduc || 'sans chargé connu')} · ${heures(c.total)}</span>
      ${c.controle
        ? `<span class="pastille p-vert">✓ contrôlé par ${esc(c.controle.par)} le ${esc(c.controle.le.slice(0, 10))}</span>
           <button data-decontroler="${esc(c.ch)}">Retirer</button>`
        : `<button data-controler="${esc(c.ch)}">✓ Heures contrôlées</button>`}
      ${c.ouverts ? `<span class="pastille p-ambre">${esc(c.ouverts)} pointage(s) ouvert(s)</span>` : ''}
      <div class="defile"><table>
        <tr><th>Qui</th>${JOURS.map((j) => `<th class="n">${j}</th>`).join('')}<th class="n">Total</th></tr>
        ${c.gens.map((g) => `<tr><td>${esc(g.personne)}</td>${g.jours.map((h) => `<td class="n">${heures(h)}</td>`).join('')}
          <td class="n"><strong>${heures(g.total)}</strong></td></tr>`).join('')}
      </table></div>
      ${c.hors_planning.map((x) => `<span class="pastille p-ambre">${esc(x.personne)} pointé ${esc(jour(x.jour))} sans être au planning</span>`).join(' ')}
      ${c.prevu_non_pointe.map((x) => `<span class="pastille p-ambre">${esc(x.personne)} prévu ${esc(jour(x.jour))}, rien pointé ici</span>`).join(' ')}
    </div>`).join('') : '<div class="rien">Aucun chantier pointé cette semaine.</div>');
  brancherSemaine();
  $('#conduc').onchange = () => { ecrire('rhi.conduc', $('#conduc').value); afficher(); };
  document.querySelectorAll('[data-controler]').forEach((b) => b.onclick = async () => {
    const qui = ($('#conduc').value || lire('rhi.qui', '') || prompt('Vos initiales (elles signent le contrôle) :') || '').trim();
    if (!qui) return;
    try { await api('/api/controles', {method: 'POST', json: {ch: b.dataset.controler, semaine: vue.semaine, qui}}); afficher(); }
    catch (e) { dire(e.message); }
  });
  document.querySelectorAll('[data-decontroler]').forEach((b) => b.onclick = async () => {
    try {
      await api('/api/controles?ch=' + encodeURIComponent(b.dataset.decontroler) + '&semaine=' + vue.semaine, {method: 'DELETE'});
      afficher();
    } catch (e) { dire(e.message); }
  });
}

// ── RHI : une carte par personne, une ligne par CH, une colonne par jour ──
async function ongletRhi() {
  const d = await api('/api/rhi?semaine=' + vue.semaine);
  const pleins = d.releves.filter((r) => r.total > 0);
  const vides = d.releves.filter((r) => r.total === 0).map((r) => r.personne);
  const tp = d.temps_perdu;
  const bilan = vue.bilan;
  vue.bilan = null;
  $('#vue').innerHTML = choixSemaine() + (bilan ? `
    <div class="carte">
      <span class="pastille p-vert">${esc(bilan.valides.length)} relevés validés</span>
      ${bilan.valides.length ? `<span class="doux">${esc(bilan.valides.join(', '))}</span>` : ''}
      ${bilan.ecartes.map((x) => `<br><span class="pastille p-ambre">à regarder</span> <strong>${esc(x.personne)}</strong>
        <span class="doux">${esc(x.raisons.join(' · '))}</span>`).join('')}
    </div>` : '') + (pleins.length ? `
    <div class="carte">
      <button id="valider-tout">✓ Valider tous les relevés sans alerte</button>
      <button id="imprimer">🖨 Imprimer les RHI à signer</button><br>
      <strong>Hors affaire cette semaine : ${heures(tp.hors_affaire) || '0h'}</strong>
      <span class="doux">sur ${heures(tp.total) || '0h'} pointées (${esc(tp.part)} %)</span>
      ${tp.motifs.map((m) => `<br><span class="pastille p-ambre">${esc(m.libelle)} · ${heures(m.heures)}</span>
        <span class="doux">${esc(m.qui.map((q) => q[0] + ' ' + heures(q[1])).join(', '))}</span>`).join('')}
    </div>` : '<div class="rien">Aucune heure pointée cette semaine.</div>') +
    pleins.map((r) => `
    <div class="carte">
      <strong style="font-size:20px">${esc(r.personne)}</strong>
      <span class="doux"> · ${heures(r.total)} dont ${heures(r.hors_affaire) || '0h'} hors affaire</span>
      ${r.a_verifier ? `<span class="pastille p-ambre">${r.a_verifier} à vérifier</span>` : ''}
      ${r.validee
        ? `<span class="pastille p-vert">✓ validé par ${esc(r.validee.par)} le ${esc(r.validee.le.slice(0, 10))}</span>
           <button data-devalider="${esc(r.personne)}">Dévalider</button>`
        : `<button data-valider="${esc(r.personne)}">Valider la semaine</button>`}
      <div class="defile"><table>
        <tr><th>CH</th><th>Chantier / motif</th>${JOURS.map((j) => `<th class="n">${j}</th>`).join('')}<th class="n">Total</th></tr>
        ${r.lignes.map((l) => `<tr><td class="ch">${esc(l.ch || l.ch_impute || '—')}</td><td>${esc(l.libelle)}
          ${l.controle ? `<span class="pastille p-vert" title="contrôlé par ${esc(l.controle.par)}">✓ ${esc(l.controle.par)}</span>`
            : l.conduc ? `<span class="pastille p-ambre">à contrôler (${esc(l.conduc)})</span>` : ''}</td>
          ${l.jours.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n"><strong>${heures(l.total)}</strong></td></tr>`).join('')}
        <tr class="total"><td></td><td>Total</td>${r.par_jour.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n">${heures(r.total)}</td></tr>
      </table></div>
    </div>`).join('') +
    (vides.length ? `<p class="doux">Rien pointé cette semaine : ${esc(vides.join(', '))}</p>` : '');
  brancherSemaine();
  if ($('#imprimer')) $('#imprimer').onclick = () => imprimerRhi(pleins, d.lundi);
  const signataire = () => {
    const qui = (lire('rhi.qui', '') || prompt('Votre nom (il signe la validation) :') || '').trim();
    if (qui) ecrire('rhi.qui', qui);
    return qui;
  };
  if ($('#valider-tout')) $('#valider-tout').onclick = async () => {
    const qui = signataire();
    if (!qui) return;
    try {
      const r = await api('/api/validations/toutes', {method: 'POST', json: {semaine: vue.semaine, qui}});
      vue.bilan = r;
      afficher();
    } catch (e) { dire(e.message); }
  };
  document.querySelectorAll('[data-valider]').forEach((b) => b.onclick = async () => {
    const qui = signataire();
    if (!qui) return;
    try {
      await api('/api/validations', {method: 'POST',
        json: {personne: b.dataset.valider, semaine: vue.semaine, qui}});
      afficher();
    } catch (e) { dire(e.message); }
  });
  document.querySelectorAll('[data-devalider]').forEach((b) => b.onclick = async () => {
    if (!confirm('Dévalider ? La semaine redevient corrigeable.')) return;
    try {
      await api('/api/validations?personne=' + encodeURIComponent(b.dataset.devalider) + '&semaine=' + vue.semaine,
        {method: 'DELETE'});
      afficher();
    } catch (e) { dire(e.message); }
  });
}

// ── Le RHI imprimé : une page par personne, à signer ──
function imprimerRhi(releves, lundi) {
  const date = (iso) => iso.slice(8, 10) + '/' + iso.slice(5, 7) + '/' + iso.slice(0, 4);
  const dimanche = new Date(lundi + 'T12:00:00Z');
  dimanche.setUTCDate(dimanche.getUTCDate() + 6);
  const page = (r) => `
    <section class="feuille">
      <h1>Relevé Hebdomadaire Individuel</h1>
      <p><strong>${esc(r.personne)}</strong> — semaine du ${esc(date(lundi))} au ${esc(date(dimanche.toISOString()))}
        ${r.validee ? ` · validé par ${esc(r.validee.par)} le ${esc(date(r.validee.le))}` : ' · <strong>non validé</strong>'}</p>
      <table>
        <tr><th>CH</th><th>Chantier / motif</th>${JOURS.map((j) => `<th class="n">${j}</th>`).join('')}<th class="n">Total</th></tr>
        ${r.lignes.map((l) => `<tr><td>${esc(l.ch || l.ch_impute || '—')}</td><td>${esc(l.libelle)}</td>
          ${l.jours.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n">${heures(l.total)}</td></tr>`).join('')}
        <tr class="total"><td></td><td>Total</td>${r.par_jour.map((h) => `<td class="n">${heures(h)}</td>`).join('')}<td class="n">${heures(r.total)}</td></tr>
      </table>
      <h2>Détail</h2>
      <table>
        <tr><th>Jour</th><th>De</th><th>À</th><th>CH / motif</th><th class="n">Durée</th></tr>
        ${r.pointages.map((p) => `<tr><td>${esc(date(p.debut))}</td><td>${esc(p.debut.slice(11, 16))}</td>
          <td>${esc((p.fin || '').slice(11, 16) || 'ouvert')}</td><td>${esc(p.ch || '')} ${esc(p.chantier || p.motif_libelle || p.libelle || '')}</td>
          <td class="n">${heures(p.heures)}</td></tr>`).join('')}
      </table>
      <div class="signatures"><div>Signature du salarié</div><div>Signature du responsable</div></div>
    </section>`;
  let zone = $('#impression');
  if (!zone) { zone = document.createElement('div'); zone.id = 'impression'; document.body.appendChild(zone); }
  zone.innerHTML = releves.map(page).join('');
  document.body.classList.add('imprime');
  window.print();
  document.body.classList.remove('imprime');
}

// ── À vérifier : les pointages douteux, corrigeables sur place ──
async function ongletVerifier() {
  const d = await api('/api/rhi?semaine=' + vue.semaine);
  const douteux = d.releves.flatMap((r) => r.pointages.filter((p) => p.alertes.length));
  const gens = await api('/api/personnes');
  const jour = vue.semaine + 'T07:00';
  $('#vue').innerHTML = choixSemaine() + `
    <div class="carte" id="ajout">
      <strong>Ajouter un pointage oublié</strong>
      <span class="doux">— une journée pas pointée, un chantier oublié sur la tablette.</span><br>
      <select data-champ="personne">${gens.map((g) => `<option>${esc(g.nom)}</option>`).join('')}</select>
      <input data-champ="ch" placeholder="CH00…" style="width:130px">
      <input type="datetime-local" data-champ="debut" value="${esc(jour)}">
      <input type="datetime-local" data-champ="fin" value="${esc(vue.semaine + 'T12:00')}">
      <button id="ajouter">Ajouter</button>
    </div>` + (d.oublis.length ? `
    <div class="carte">
      <strong>Au planning, rien pointé</strong>
      <span class="doux">— une journée entière absente du RHI. Congé ou maladie : rien à faire ; sinon, saisir.</span>
      <div class="defile"><table>
        <tr><th>Qui</th><th>Jour</th><th>Prévu au planning</th><th></th></tr>
        ${d.oublis.map((o) => `<tr>
          <td>${esc(o.personne)}</td><td>${esc(JOURS[(new Date(o.jour + 'T12:00:00Z').getUTCDay() + 6) % 7])} ${esc(o.jour.slice(8, 10))}/${esc(o.jour.slice(5, 7))}</td>
          <td>${o.prevu.map((x) => `<span class="ch">${esc(x.ch || '')}</span> ${esc(x.libelle)}`).join('<br>')}</td>
          <td><button data-saisir="${esc(o.personne)}" data-jour="${esc(o.jour)}" data-ch="${esc((o.prevu.find((x) => x.ch) || {}).ch || '')}">Saisir</button></td>
        </tr>`).join('')}
      </table></div>
    </div>` : '') + (douteux.length ? `
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
  document.querySelectorAll('[data-saisir]').forEach((b) => b.onclick = () => {
    const champ = (n) => $('#ajout [data-champ=' + n + ']');
    champ('personne').value = b.dataset.saisir;
    champ('ch').value = b.dataset.ch;
    champ('debut').value = b.dataset.jour + 'T07:00';
    champ('fin').value = b.dataset.jour + 'T12:00';
    $('#ajout').scrollIntoView();
    champ('fin').focus();
  });
  $('#ajouter').onclick = async () => {
    const corps = {qui: lire('rhi.qui', '') || 'bureau'};
    document.querySelectorAll('#ajout [data-champ]').forEach((i) => { corps[i.dataset.champ] = i.value.trim(); });
    if (!/^CH\d{5}$/i.test(corps.ch)) { dire('Un CH complet : CH suivi de cinq chiffres'); return; }
    corps.ch = corps.ch.toUpperCase();
    try { await api('/api/pointages', {method: 'POST', json: corps}); dire('Ajouté au RHI de ' + corps.personne); afficher(); }
    catch (e) { dire(e.message); }
  };
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
      <tr><th>CH</th><th>Chantier</th><th>Client</th><th>Conduc.</th><th class="n">Réel</th><th class="n">Prévu fab</th><th class="n">Consommé</th><th class="n">Coût MO</th><th class="n">Vendu HT</th><th class="n">MO / vendu</th></tr>
      ${liste.map((a) => {
        const p = a.consomme_pct;
        const cl = p === null ? '' : p > 100 ? 'p-rouge' : p > 80 ? 'p-ambre' : 'p-vert';
        return `<tr><td><a href="#" data-ch="${esc(a.ch)}" class="ch">${esc(a.ch)}</a></td><td>${esc(a.chantier)}</td>
          <td class="doux">${esc(a.client || '')}</td><td>${esc(a.conduc)}</td><td class="n">${heures(a.heures_reelles) || '—'}</td>
          <td class="n">${a.heures_prevues ? heures(a.heures_prevues) : '—'}</td>
          <td class="n">${p === null ? '' : `<span class="pastille ${cl}">${esc(p)} %</span>`}</td>
          <td class="n">${a.cout_main_oeuvre ? euros(a.cout_main_oeuvre) : ''}</td>
          <td class="n">${a.vendu_ht ? euros(a.vendu_ht) : '<span class="doux">—</span>'}</td>
          <td class="n">${a.part_mo_pct === null ? '' : esc(String(a.part_mo_pct).replace('.', ',')) + ' %'}</td></tr>`;
      }).join('')}
    </table></div><div id="detail"></div>`;
  document.querySelectorAll('[data-ch]').forEach((a) => a.onclick = async (e) => {
    e.preventDefault();
    const d = await api('/api/affaires/' + a.dataset.ch);
    $('#detail').innerHTML = `<div class="carte" style="margin-top:16px">
      <div class="ch">${esc(d.ch)}</div><strong style="font-size:20px">${esc(d.chantier)}</strong>
      <p>${heures(d.heures_reelles) || '0h'} pointées${d.heures_prevues ? ' sur ' + heures(d.heures_prevues) + ' prévues' : ''}.
        ${d.cout_main_oeuvre ? `<br>Coût main-d'œuvre : <strong>${euros(d.cout_main_oeuvre)}</strong>` : ''}
        ${d.vendu_ht ? `<br>Vendu HT (devis signés ou payés ${esc(d.devis_refs)}) : <strong>${euros(d.vendu_ht)}</strong>`
          : '<br><span class="doux">Vendu HT : aucun devis signé portant ce CH dans InterFast</span>'}
        ${d.sans_cout.length ? `<br><span class="pastille p-ambre">Sans coût horaire (non chiffrés) : ${esc(d.sans_cout.join(', '))}</span>` : ''}
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
  const now = d.maintenant_ms;
  $('#vue').innerHTML = d.pointages.length ? `<table>
    <tr><th>Qui</th><th>CH</th><th>Chantier / motif</th><th>Depuis</th><th class="n">Durée</th></tr>
    ${d.pointages.map((p) => `<tr><td>${esc(p.personne)}</td><td class="ch">${esc(p.ch || '—')}</td>
      <td>${esc(p.chantier || p.libelle || p.motif)}</td><td>${esc(p.debut.slice(11, 16))}</td>
      <td class="n">${duree((now - msDeParis(p.debut)) / 1000)}</td></tr>`).join('')}
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
      <button id="montants">Relire les montants vendus</button>
      <div id="synchro-res" style="margin-top:12px"></div>
      <p><a class="btn" href="/api/sauvegarde" id="sauvegarde">⬇ Télécharger toute la base (sauvegarde)</a>
        <span class="doux">Une copie est faite chaque jour sur le serveur ; celle-ci est à garder ailleurs.</span></p>
      <p class="doux">Vendu HT = devis <em>signés</em> ou <em>payés</em> dont le titre porte le CH (« Import Optima -
        CH00…»). Un devis sans CH dans son titre n'est pas compté : RHI affiche « — » plutôt que 0 €.</p>
    </div>`;
  $('#sauvegarde').onclick = async (e) => {
    e.preventDefault();
    try {
      const r = await fetch('/api/sauvegarde', {headers: {'X-RHI-Code': lire('rhi.code', '')}});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(await r.blob());
      a.download = 'rhi-' + isoParis(Date.now()).slice(0, 16).replace(':', 'h') + '.db';
      a.click();
    } catch (err) { dire('Sauvegarde : ' + err.message); }
  };
  $('#montants').onclick = async () => {
    const sortie = $('#synchro-res');
    sortie.textContent = 'Lecture des devis, un CH à la fois…';
    try {
      const r = await api('/api/interfast/montants', {method: 'POST'});
      sortie.innerHTML = `<span class="pastille p-vert">✓</span> ${esc(r.avec_vendu)} CH chiffrés sur ${esc(r.lus)}.` +
        (r.sans_devis_signe.length ? ` <span class="pastille p-ambre">Sans devis signé : ${esc(r.sans_devis_signe.join(', '))}</span>` : '');
    } catch (err) {
      sortie.innerHTML = `<span class="pastille p-rouge">✗</span> ${esc(err.message)}`;
    }
  };
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

function euros(v) {
  return esc(Number(v).toLocaleString('fr-FR', {style: 'currency', currency: 'EUR', maximumFractionDigits: 0}));
}

// ── Personnes : équipe, actif, compte InterFast, coût horaire ──
async function ongletPersonnes() {
  const [d, comptes] = await Promise.all([api('/api/personnes/detail'), api('/api/interfast/utilisateurs')]);
  const options = (choisi) => `<option value="">— aucun —</option>` + comptes.map((u) =>
    `<option value="${esc(u.id)}" ${u.id === choisi ? 'selected' : ''}>${esc(u.prenom)} ${esc(u.nom)}${u.archive ? ' (archivé)' : ''}</option>`).join('');
  $('#vue').innerHTML = `
    <div class="carte">
      <p>Le coût horaire chiffre le point d'affaire. Priorité : celui saisi ici, sinon celui d'InterFast
        (s'il n'est pas à 0), sinon le taux moyen ${d.cout_defaut ? `(<strong>${euros(d.cout_defaut)}</strong>/h)` : '(non réglé : variable RHI_COUT_HORAIRE)'}.</p>
      <p><strong>Ajouter une personne</strong> (un intérimaire) : elle apparaît aussitôt sur les tablettes.</p>
      <input id="nouveau-nom" placeholder="NOM Prénom" maxlength="40" style="width:220px">
      <select id="nouveau-equipe"><option>atelier</option><option>pose</option></select>
      <button id="ajouter-personne">Ajouter</button>
      <hr>
      <button id="relire">Relire les comptes InterFast</button> <span class="doux">(une minute : InterFast est lu un compte à la fois)</span>
      <div id="rapport" style="margin-top:12px"></div>
    </div>
    <div class="defile"><table>
      <tr><th>Nom (planning)</th><th>Équipe</th><th>Actif</th><th>Compte InterFast</th><th class="n">Coût saisi €/h</th><th class="n">Retenu</th></tr>
      ${d.personnes.map((p) => `<tr data-nom="${esc(p.nom)}">
        <td><strong>${esc(p.nom)}</strong>${p.interim ? ' <span class="pastille p-ambre">intérim</span>' : ''}<br><span class="doux">${esc(p.nom_complet)}</span></td>
        <td><select data-champ="equipe"><option ${p.equipe === 'atelier' ? 'selected' : ''}>atelier</option>
          <option ${p.equipe === 'pose' ? 'selected' : ''}>pose</option></select></td>
        <td><input type="checkbox" data-champ="actif" ${p.actif ? 'checked' : ''} style="width:auto"></td>
        <td><select data-champ="compte">${options(p.interfast_user_id)}</select></td>
        <td class="n"><input type="number" min="0" step="0.5" data-champ="cout" value="${esc(p.cout_horaire ?? '')}" style="width:100px"></td>
        <td class="n">${p.cout_retenu ? euros(p.cout_retenu) : '<span class="pastille p-ambre">aucun</span>'}</td>
      </tr>`).join('')}
    </table></div>`;
  $('#ajouter-personne').onclick = async () => {
    try {
      const r = await api('/api/personnes', {method: 'POST', json: {nom: $('#nouveau-nom').value, equipe: $('#nouveau-equipe').value}});
      dire(r.deja ? r.nom + ' était déjà connu : réactivé' : r.nom + ' ajouté aux tablettes'); afficher();
    } catch (e) { dire(e.message); }
  };
  document.querySelectorAll('tr[data-nom] [data-champ]').forEach((champ) => champ.onchange = async () => {
    const nom = champ.closest('tr').dataset.nom;
    const corps = {
      equipe: {equipe: champ.value},
      actif: {actif: champ.checked ? 1 : 0},
      compte: champ.value ? {interfast_user_id: Number(champ.value)} : {delier: true},
      cout: {cout_horaire: Number(champ.value || 0)},
    }[champ.dataset.champ];
    try { await api('/api/personnes/' + encodeURIComponent(nom), {method: 'PATCH', json: corps}); dire('Enregistré'); afficher(); }
    catch (e) { dire(e.message); }
  });
  $('#relire').onclick = async () => {
    const r0 = $('#rapport'); r0.textContent = 'Lecture des comptes InterFast…';
    try {
      const r = await api('/api/interfast/utilisateurs', {method: 'POST'});
      const liste = (titre, cl, v) => v.length ? `<p><span class="pastille ${cl}">${esc(titre)}</span> ${esc(v.join(', '))}</p>` : '';
      r0.innerHTML = liste('Reliés', 'p-vert', r.liees) + liste('Déjà reliés', 'p-vert', r.deja_liees) +
        liste('Plusieurs comptes possibles — choisir ci-dessous', 'p-ambre',
          Object.entries(r.ambigus).map(([k, v]) => k + ' (' + v.join(' / ') + ')')) +
        liste('Compte archivé dans InterFast', 'p-ambre',
          Object.entries(r.archives).map(([k, v]) => k + ' (' + v.join(' / ') + ')')) +
        liste('Aucun compte InterFast', 'p-rouge', r.sans_correspondance);
      setTimeout(afficher, 4000);
    } catch (e) { r0.innerHTML = `<span class="pastille p-rouge">✗</span> ${esc(e.message)}`; }
  };
}

// ── Vers InterFast : les cases du planning, une par CH et par jour ──
async function ongletEnvois() {
  const d = await api('/api/interfast/envois?semaine=' + vue.semaine);
  const cl = {'prête': 'p-vert', 'bloquée': 'p-rouge', 'en attente': 'p-ambre', 'posée': 'p-ambre',
    'à compléter': 'p-rouge', 'terminée': 'p-vert', 'écart': 'p-rouge', 'à vérifier': 'p-rouge'};
  const date = (iso) => iso.slice(8, 10) + '/' + iso.slice(5, 7);
  const ligneEquipe = (e) => `<tr>
      <td>${esc(e.technicien)}${e.compte ? '' : ' <span class="pastille p-rouge">sans compte</span>'}
        ${e.valide ? '' : ' <span class="pastille p-ambre">RHI non validé</span>'}</td>
      <td>${esc(e.debut)}</td><td>${esc(e.fin)}</td><td>${esc(e.pause || '—')}</td>
      <td class="n">${heures(e.heures)}</td>
      <td class="n">${e.interfast === null ? '—' : heures(e.interfast)}${e.ecart ? ' <span class="pastille p-rouge">écart</span>' : ''}</td></tr>`;
  $('#vue').innerHTML = choixSemaine() + `
    <div class="carte">
      <p>Les heures entrent dans InterFast comme des <strong>cases du planning</strong> : une par CH et par jour,
        avec toute l'équipe. RHI pose la case ; dans InterFast, on la <strong>termine</strong> en recopiant
        les heures de chacun (début, fin, pause), puis on <strong>valide la feuille de temps</strong>
        (Équipe → la fiche → Feuilles de temps, en orange tant qu'elle n'est pas validée).
        Seules les heures validées comptent dans la marge du chantier.</p>
      <p>${d.ecriture ? '' : '<span class="pastille p-ambre">Écriture vers InterFast coupée : rien ne part, on voit ce qui partirait.</span>'}</p>
      <p><span class="pastille p-vert">${esc(d.pretes)} prêtes · ${heures(d.heures_pretes) || '0h'}</span>
        <span class="pastille p-ambre">${esc(d.en_attente)} en attente de validation</span>
        <span class="pastille p-rouge">${esc(d.bloquees)} bloquées</span>
        <span class="pastille">${esc(d.posees)} posées · ${esc(d.terminees)} terminées</span>
        ${d.ecarts ? `<span class="pastille p-rouge">${esc(d.ecarts)} avec un écart d'heures</span>` : ''}</p>
      <p>${d.ecriture && d.pretes ? `<button class="btn" id="poser">Poser les ${esc(d.pretes)} cases prêtes dans InterFast</button>` : ''}
        ${d.posees + d.terminees + d.ecarts ? '<button class="btn" id="relire">Relire les heures reçues par InterFast</button>' : ''}
        <span id="retour-envoi"></span></p>
    </div>` + (d.cases.length ? d.cases.map((x) => `
    <div class="carte">
      <span class="pastille ${esc(cl[x.etat] || '')}">${esc(x.etat)}</span>
      <strong>${esc(date(x.jour))} · ${esc(x.heure)}–${esc(x.fin)}</strong>
      <span class="ch">${esc(x.ch)}</span> ${esc(x.client)} <span class="doux">${esc(x.chantier)}</span>
      ${x.ref ? `<span class="pastille">${esc(x.ref)}</span>` : ''}
      ${d.ecriture && x.etat === 'prête' ? `<button class="btn" data-poser="${esc(x.id)}">Poser cette case</button>` : ''}
      ${x.blocages.length ? `<br><span class="doux">Bloquée : ${esc(x.blocages.join(' · '))}</span>` : ''}
      ${x.en_attente.length ? `<br><span class="doux">À valider d'abord : ${esc(x.en_attente.join(', '))}</span>` : ''}
      ${x.a_ajouter.length ? `<br><span class="doux">À ajouter à la main dans ${esc(x.ref)} : ${esc(x.a_ajouter.join(', '))}</span>
        <button data-completer="${esc(x.id)}">C'est fait : ajoutés dans InterFast</button>` : ''}
      ${x.etat === 'à vérifier' ? `<br><span class="doux">InterFast n'a pas clairement confirmé : regarder dans son planning si la case existe.</span>
        <input data-ref-pour="${esc(x.id)}" placeholder="IN00…" style="width:110px">
        <button data-trancher="${esc(x.id)}" data-oui="1">Elle existe : c'est cette référence</button>
        <button data-trancher="${esc(x.id)}" data-oui="">Elle n'existe pas : la renvoyer</button>` : ''}
      <div class="defile"><table>
        <tr><th>Pour terminer la case</th><th>Début</th><th>Fin</th><th>Pause</th><th class="n">Heures RHI</th><th class="n">Reçu par InterFast</th></tr>
        ${x.equipe.map(ligneEquipe).join('')}
      </table></div>
    </div>`).join('') : '<div class="rien">Aucun pointage sur un CH cette semaine.</div>');
  brancherSemaine();
  const retour = $('#retour-envoi');
  const bouton = (id, fn) => { const b = $('#' + id); if (b) b.onclick = fn; };
  const geste = async (chemin, id, ref) => {
    const [ch, jour] = id.split('|');
    try { await api(chemin, {method: 'POST', json: {ch, jour, ref: ref || ''}}); afficher(); }
    catch (e) { dire(e.message); }
  };
  document.querySelectorAll('[data-completer]').forEach((b) => {
    b.onclick = () => geste('/api/interfast/cases/completer', b.dataset.completer);
  });
  document.querySelectorAll('[data-trancher]').forEach((b) => {
    b.onclick = () => {
      const ref = b.dataset.oui ? b.parentElement.querySelector('[data-ref-pour]').value : '';
      if (b.dataset.oui && !ref.trim()) { dire('La référence IN… lue dans InterFast'); return; }
      geste('/api/interfast/cases/reference', b.dataset.trancher, ref);
    };
  });
  bouton('poser', async () => {
    $('#poser').disabled = true;
    retour.textContent = 'Envoi en cours, une case à la fois…';
    try {
      const r = await api('/api/interfast/envois', {method: 'POST', json: {semaine: vue.semaine}});
      dire(`${r.posees.length} cases posées` + (r.echecs.length ? `, ${r.echecs.length} en échec : ` +
        r.echecs.map((x) => x.id + ' — ' + x.erreur).join(' · ') : ''));
      afficher();
    } catch (e) { retour.textContent = e.message; $('#poser').disabled = false; }
  });
  document.querySelectorAll('[data-poser]').forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try {
        const r = await api('/api/interfast/envois', {method: 'POST', json: {semaine: vue.semaine, cases: [b.dataset.poser]}});
        dire(r.posees.length ? 'Case posée : ' + r.posees[0].ref : 'Échec : ' + r.echecs.map((x) => x.erreur).join(' · '));
        afficher();
      } catch (e) { dire(e.message); b.disabled = false; }
    };
  });
  bouton('relire', async () => {
    retour.textContent = 'Lecture des heures dans InterFast, une case à la fois (une à deux minutes)…';
    try {
      const r = await api('/api/interfast/suivi?semaine=' + vue.semaine, {method: 'POST'});
      dire(`${r.terminees.length} terminées, ${r.a_terminer.length} à terminer dans InterFast, ` +
        `${r.ecarts.length} avec un écart d'heures` +
        (r.illisibles.length ? ', illisibles (trop d\'interventions ce jour-là) : ' + r.illisibles.join(', ') : ''));
      afficher();
    } catch (e) { retour.textContent = e.message; }
  });
}

// ── Marche en avant : chaque pose à venir face à ses études et sa fab ──
async function ongletMarche() {
  const [d, co] = await Promise.all([api('/api/marche'), api('/api/marche/courrier')]);
  const cl = {rouge: 'p-rouge', orange: 'p-ambre', gris: '', vert: 'p-vert'};
  const titre = {rouge: 'Risques prioritaires', orange: 'À surveiller', gris: 'À confirmer ou nettoyer', vert: 'Cohérent'};
  const date = (iso) => iso.slice(8, 10) + '/' + iso.slice(5, 7);
  const blocs = ['rouge', 'orange', 'gris', 'vert'].map((n) => {
    const ls = d.lignes.filter((l) => l.niveau === n);
    if (!ls.length) return '';
    return `<h2>${esc(titre[n])} · ${esc(ls.length)}</h2>` + ls.map((l) => `
      <div class="carte">
        <span class="pastille ${esc(cl[n])}">pose ${esc(date(l.pose))} · J${l.dans_j >= 0 ? '+' : ''}${esc(l.dans_j)}</span>
        <strong>${esc(l.libelle)}</strong> <span class="ch">${esc(l.ch || 'sans CH')}</span>
        <span class="doux">· ${esc(l.personnes.join(', '))}</span>
        <ul>${l.constats.map((x) => `<li>${esc(x.texte)}${x.consecutifs > 1
          ? ` <span class="pastille p-ambre">${esc(x.consecutifs)}ᵉ analyse d'affilée</span>` : ''}</li>`).join('')}</ul>
      </div>`).join('');
  }).join('');
  $('#vue').innerHTML = `
    <div class="carte">
      <p>Poses du ${esc(date(d.jour))} au ${esc(date(d.jusqu_au))}, face au plan de charge, au planning FAB et au BET.
        Une fabrication n'est comptée <strong>faite</strong> que si elle est datée d'avant aujourd'hui.</p>
      <p>${d.bet_charge ? `BET chargé, planifié jusqu'au ${esc(date(d.bet_a_jour_au || d.jour))}.`
        : '<span class="pastille p-ambre">BET non chargé : déposer le planning BET (onglet Plannings) pour les alertes « études ».</span>'}</p>
      <p><a class="btn" href="/api/marche.md" id="synthese">⬇ La synthèse en Markdown (à envoyer)</a></p>
      <p>${!co.a.length ? '<span class="pastille p-ambre">Envoi du lundi 7 h : aucun destinataire (RHI_MARCHE_A)</span>'
        : !co.smtp ? '<span class="pastille p-ambre">Envoi du lundi 7 h : serveur de courrier non réglé (SMTP_HOST)</span>'
        : `Envoyée chaque lundi à 7 h à ${esc(co.a.join(', '))}. <button id="envoyer-marche">✉ Envoyer maintenant</button>`}
        ${co.dernier ? `<span class="doux">Dernier envoi : ${esc(co.dernier.jour)} — ${esc(co.dernier.statut)}</span>` : ''}</p>
    </div>` + (blocs || '<div class="rien">Aucune pose dans les 4 semaines : déposer le planning de pose.</div>');
  if ($('#envoyer-marche')) $('#envoyer-marche').onclick = async () => {
    try { const r = await api('/api/marche/envoyer', {method: 'POST'}); dire('Synthèse : ' + r.statut); afficher(); }
    catch (e) { dire(e.message); }
  };
  $('#synthese').onclick = async (e) => {
    e.preventDefault();
    try {
      const texte = await api('/api/marche.md');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([texte], {type: 'text/markdown'}));
      a.download = 'marche-en-avant-' + d.jour + '.md';
      a.click();
    } catch (err) { dire(err.message); }
  };
}

afficher();
