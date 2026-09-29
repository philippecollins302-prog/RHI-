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
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
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
