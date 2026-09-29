// Partagé par la tablette et le bureau : échappement, appels, code d'accès.
const $ = (s) => document.querySelector(s);

function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) =>
    ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

function lire(cle, defaut) {
  try { const v = localStorage.getItem(cle); return v === null ? defaut : v; } catch (e) { return defaut; }
}
function ecrire(cle, v) {
  try { localStorage.setItem(cle, v); } catch (e) { /* navigation privée : on s'en passe */ }
}

function dire(texte) {
  const m = $('#message');
  if (!m) return;
  m.textContent = texte;
  m.classList.add('visible');
  clearTimeout(dire.t);
  dire.t = setTimeout(() => m.classList.remove('visible'), 3500);
}

// Un 401 demande le code une fois, le garde sur l'appareil, et rejoue l'appel.
async function api(chemin, options = {}) {
  const entetes = Object.assign({'X-RHI-Code': lire('rhi.code', '')}, options.headers || {});
  if (options.json !== undefined) {
    entetes['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.json);
  }
  const r = await fetch(chemin, Object.assign({}, options, {headers: entetes}));
  if (r.status === 401 && !options.rejoue) {
    const code = prompt("Code d'accès de l'appareil :");
    if (code) { ecrire('rhi.code', code.trim()); return api(chemin, Object.assign(options, {rejoue: true})); }
  }
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (e) { /* corps vide */ }
    // `http` distingue un refus du serveur (à ne pas rejouer) d'une panne de
    // réseau (fetch lève alors une TypeError, sans `http`) : à rejouer.
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.http = r.status;
    throw err;
  }
  const type = r.headers.get('content-type') || '';
  return type.includes('json') ? r.json() : r.text();
}

function duree(secondes) {
  const s = Math.max(0, Math.floor(secondes));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}`;
}

function heures(h) {
  if (!h) return '';
  const e = Math.floor(h), m = Math.round((h - e) * 60);
  return m === 60 ? `${e + 1}h00` : `${e}h${String(m).padStart(2, '0')}`;
}

// L'heure du serveur (corrigée de l'écart mesuré), écrite à l'heure de Paris
// comme le serveur l'attend : « 2026-09-29T07:30:00 ».
function isoParis(ms) {
  return new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit',
    day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false})
    .format(new Date(ms)).replace(' ', 'T');
}

function lireJson(cle, defaut) {
  try { return JSON.parse(lire(cle, '')) ?? defaut; } catch (e) { return defaut; }
}

// L'inverse : « 2026-09-29T07:30:00 » à l'heure de Paris → instant absolu (ms),
// quel que soit le fuseau réglé sur l'appareil. `new Date(iso)` lirait l'heure
// dans le fuseau de l'appareil : faux sur une tablette restée en UTC.
function msDeParis(iso) {
  const n = iso.match(/\d+/g).map(Number);
  const brut = Date.UTC(n[0], n[1] - 1, n[2], n[3] || 0, n[4] || 0, n[5] || 0);
  const decalage = (ms) => {
    const lu = isoParis(ms).match(/\d+/g).map(Number);
    return Date.UTC(lu[0], lu[1] - 1, lu[2], lu[3], lu[4], lu[5]) - ms;
  };
  // Deux passes : autour d'un changement d'heure, le décalage lu à l'heure
  // « brute » n'est pas celui de l'instant cherché (banc-heures, 25/10).
  return brut - decalage(brut - decalage(brut));
}
