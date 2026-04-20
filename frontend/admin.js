/**
 * admin.js — /nexus/admin.html
 *
 * 4 tabs, each panel internally scrollable so the page itself never
 * scrolls beyond the header + hero. Tabs:
 *   - Tracks     : filter + expand-to-show-companies + rename/merge/delete
 *   - Companies  : search + track-membership chips (click ✕ to unlink)
 *   - Edges      : search by ticker + add/delete
 *   - Issues     : orphan companies, multi-track dupes, empty tracks
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

// ── Utils ────────────────────────────────────────────────────────────────
function toast(message, kind = 'ok') {
  const el = document.createElement('div');
  el.className = `admin-toast ${kind}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2500);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function fmtMcap(n) {
  if (n == null) return '';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n}`;
}

async function api(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, opts);
  let body = null;
  try { body = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body;
}

// ── State ────────────────────────────────────────────────────────────────
let ALL_TRACKS = [];
let TRACK_FILTER = '';
const TRACK_COMPANIES_CACHE = new Map();   // track_id → companies[]
const EXPANDED_TRACKS = new Set();

// ── Tracks tab ───────────────────────────────────────────────────────────
async function loadTracks() {
  ALL_TRACKS = await api('/admin/tracks');
  document.getElementById('count-tracks').textContent = ALL_TRACKS.length;
  renderTracks();
}

function renderTracks() {
  const wrap = document.getElementById('admin-tracks');
  const q = TRACK_FILTER.trim().toLowerCase();
  const rows = q
    ? ALL_TRACKS.filter(t => t.name.toLowerCase().includes(q))
    : ALL_TRACKS;

  document.getElementById('tracks-meta').textContent =
    `${rows.length}${q ? ` of ${ALL_TRACKS.length}` : ''} tracks`;

  if (rows.length === 0) {
    wrap.innerHTML = '<div class="empty">No tracks match.</div>';
    return;
  }

  wrap.innerHTML = rows.map(t => `
    <div class="admin-row${EXPANDED_TRACKS.has(t.id) ? ' expanded' : ''}" data-id="${t.id}">
      <div class="primary">
        <input class="inline-edit name" value="${escapeHtml(t.name)}" data-original="${escapeHtml(t.name)}" />
      </div>
      <span class="count-chip">${t.company_count}</span>
      <div class="actions">
        <button class="admin-btn save">Save name</button>
        <button class="admin-btn merge">Merge →</button>
        <button class="admin-btn danger delete">Delete</button>
      </div>
      ${EXPANDED_TRACKS.has(t.id) ? `<div class="expand-body" data-body-for="${t.id}">Loading companies…</div>` : ''}
    </div>
  `).join('');

  wrap.querySelectorAll('.admin-row[data-id]').forEach(row => {
    const id = Number(row.dataset.id);
    // Click row (not a button/input) to expand
    row.addEventListener('click', (e) => {
      if (e.target.closest('button, input')) return;
      toggleExpand(id);
    });
    row.querySelector('.save').addEventListener('click', e => { e.stopPropagation(); saveTrackName(id, row); });
    row.querySelector('.merge').addEventListener('click', e => { e.stopPropagation(); mergeTrack(id); });
    row.querySelector('.delete').addEventListener('click', e => { e.stopPropagation(); deleteTrack(id); });
    if (EXPANDED_TRACKS.has(id)) loadTrackCompanies(id);
  });
}

async function toggleExpand(trackId) {
  if (EXPANDED_TRACKS.has(trackId)) EXPANDED_TRACKS.delete(trackId);
  else EXPANDED_TRACKS.add(trackId);
  renderTracks();
}

async function loadTrackCompanies(trackId) {
  const body = document.querySelector(`[data-body-for="${trackId}"]`);
  if (!body) return;
  try {
    const companies = await api(`/admin/tracks/${trackId}/companies`);
    TRACK_COMPANIES_CACHE.set(trackId, companies);
    body.innerHTML = `
      <div class="company-chips" data-track="${trackId}">
        ${companies.map(c => `
          <span class="company-chip" data-ticker="${escapeHtml(c.ticker)}">
            ${escapeHtml(c.ticker)}
            <span class="chip-name">${escapeHtml((c.name || '').slice(0, 32))}</span>
            <span class="chip-x" title="Remove from this track">✕</span>
          </span>
        `).join('') || '<span class="dim small">No companies linked.</span>'}
        <span class="company-chip-add-wrap">
          <input class="admin-input add-ticker" placeholder="+ ticker" />
          <button class="admin-btn add-company">Add</button>
        </span>
      </div>
    `;
    body.querySelectorAll('.chip-x').forEach(x => {
      x.addEventListener('click', async (e) => {
        e.stopPropagation();
        const ticker = x.parentElement.dataset.ticker;
        if (!confirm(`Remove ${ticker} from this track?`)) return;
        try {
          await api(`/admin/tracks/${trackId}/companies/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
          toast(`removed ${ticker}`);
          // Refresh this track row's count + company list
          await loadTracks();
        } catch (err) { toast(err.message, 'error'); }
      });
    });
    body.querySelector('.add-company').addEventListener('click', async (e) => {
      e.stopPropagation();
      const input = body.querySelector('.add-ticker');
      const ticker = input.value.trim().toUpperCase();
      if (!ticker) return;
      try {
        const res = await api(`/admin/tracks/${trackId}/companies`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker }),
        });
        toast(res.newly_linked ? `added ${ticker}` : `${ticker} already linked`);
        input.value = '';
        await loadTracks();
      } catch (err) { toast(err.message, 'error'); }
    });
  } catch (err) {
    body.innerHTML = `<span class="dim small">Load failed: ${escapeHtml(err.message)}</span>`;
  }
}

async function saveTrackName(id, row) {
  const input = row.querySelector('.name');
  const name = input.value.trim();
  const original = input.dataset.original;
  if (!name || name === original) return;
  try {
    await api(`/admin/tracks/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    toast(`renamed to "${name}"`);
    await loadTracks();
  } catch (err) { toast(err.message, 'error'); }
}

async function mergeTrack(sourceId) {
  const src = ALL_TRACKS.find(t => t.id === sourceId);
  const input = prompt(
    `Merge "${src?.name}" into which other track?\n\n` +
    `Type the target track's exact name (case-insensitive).`
  );
  if (!input) return;
  const target = ALL_TRACKS.find(t => t.name.toLowerCase() === input.trim().toLowerCase());
  if (!target) return toast(`no track matching "${input}"`, 'error');
  if (target.id === sourceId) return toast('cannot merge into itself', 'error');
  if (!confirm(`Merge "${src.name}" (${src.company_count} companies) into "${target.name}"?\n\n` +
               `"${src.name}" will be deleted.`)) return;
  try {
    const r = await api('/admin/tracks/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_id: sourceId, target_id: target.id }),
    });
    toast(`merged: ${r.moved} links moved`);
    await loadTracks();
  } catch (err) { toast(err.message, 'error'); }
}

async function deleteTrack(id) {
  const t = ALL_TRACKS.find(x => x.id === id);
  if (!confirm(`Delete "${t?.name}"?\n\n${t?.company_count} company links will be unlinked. Cannot be undone.`)) return;
  try {
    const r = await api(`/admin/tracks/${id}`, { method: 'DELETE' });
    toast(`deleted "${t?.name}" (${r.unlinked_companies} unlinked)`);
    await loadTracks();
  } catch (err) { toast(err.message, 'error'); }
}

// ── Companies tab ────────────────────────────────────────────────────────
const COMPANIES_PAGE_SIZE = 100;
let COMPANIES_SEARCH = '';
let COMPANIES_SORT = 'ticker';
let COMPANIES_PAGE = 1;   // 1-indexed
let COMPANIES_TIMER = null;

async function loadCompanies() {
  const wrap = document.getElementById('admin-companies');
  const meta = document.getElementById('companies-meta');
  const pager = document.getElementById('companies-pager');
  wrap.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const offset = (COMPANIES_PAGE - 1) * COMPANIES_PAGE_SIZE;
    const r = await api(
      `/admin/companies?q=${encodeURIComponent(COMPANIES_SEARCH)}` +
      `&limit=${COMPANIES_PAGE_SIZE}&offset=${offset}&sort=${COMPANIES_SORT}`
    );
    const totalPages = Math.max(1, Math.ceil(r.total / COMPANIES_PAGE_SIZE));
    // Clamp + retry if we landed past the end (e.g. search narrowed results)
    if (COMPANIES_PAGE > totalPages) {
      COMPANIES_PAGE = totalPages;
      return loadCompanies();
    }
    meta.textContent = COMPANIES_SEARCH.trim()
      ? `${r.total} matches`
      : `${r.total} companies`;
    pager.style.display = r.total > COMPANIES_PAGE_SIZE ? 'flex' : 'none';
    const startN = r.total === 0 ? 0 : offset + 1;
    const endN = Math.min(offset + r.companies.length, r.total);
    document.getElementById('pg-info').textContent =
      `page ${COMPANIES_PAGE} of ${totalPages} · showing ${startN}–${endN}`;
    document.getElementById('pg-prev').disabled  = COMPANIES_PAGE <= 1;
    document.getElementById('pg-first').disabled = COMPANIES_PAGE <= 1;
    document.getElementById('pg-next').disabled  = COMPANIES_PAGE >= totalPages;
    document.getElementById('pg-last').disabled  = COMPANIES_PAGE >= totalPages;
    document.getElementById('pg-jump').max = totalPages;
    document.getElementById('count-companies').textContent = r.total;
    if (r.companies.length === 0) {
      wrap.innerHTML = '<div class="empty">No matches.</div>';
      return;
    }
    wrap.innerHTML = r.companies.map(c => `
      <div class="admin-row company-row" data-ticker="${escapeHtml(c.ticker)}">
        <div class="primary">
          <span class="ticker">${escapeHtml(c.ticker)}</span>
          <span class="sub">${escapeHtml(c.name || '')} • ${escapeHtml(c.sector || '–')} • ${fmtMcap(c.market_cap)}</span>
          <div class="track-tags">
            ${c.tracks.map(t => `
              <span class="track-tag" data-track-id="${t.id}">
                ${escapeHtml(t.name)}
                <span class="chip-x" title="Remove from this track">✕</span>
              </span>
            `).join('') || '<span class="dim small">no tracks — orphan company</span>'}
          </div>
        </div>
        <span class="count-chip">${c.tracks.length}</span>
        <div class="actions">
          <span class="dim small">click ✕ to unlink</span>
        </div>
      </div>
    `).join('');
    wrap.querySelectorAll('.track-tag .chip-x').forEach(x => {
      x.addEventListener('click', async (e) => {
        e.stopPropagation();
        const tag = x.closest('.track-tag');
        const row = x.closest('.company-row');
        const ticker = row.dataset.ticker;
        const trackId = Number(tag.dataset.trackId);
        if (!confirm(`Remove ${ticker} from this track?`)) return;
        try {
          await api(`/admin/tracks/${trackId}/companies/${encodeURIComponent(ticker)}`, { method: 'DELETE' });
          toast(`unlinked ${ticker}`);
          loadCompanies();
        } catch (err) { toast(err.message, 'error'); }
      });
    });
  } catch (err) {
    wrap.innerHTML = `<div class="empty">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ── Edges tab ────────────────────────────────────────────────────────────
async function loadEdges() {
  const ticker = document.getElementById('edges-ticker').value.trim().toUpperCase();
  if (!ticker) return toast('enter a ticker', 'error');
  const wrap = document.getElementById('admin-edges');
  try {
    const edges = await api(`/admin/relationships?ticker=${encodeURIComponent(ticker)}`);
    if (edges.length === 0) {
      wrap.innerHTML = `<div class="empty">No edges for ${escapeHtml(ticker)}.</div>`;
      return;
    }
    wrap.innerHTML = edges.map(e => `
      <div class="admin-row" data-id="${e.id}">
        <div class="primary">
          <span class="ticker">${escapeHtml(e.source)}</span>
          <span class="dim small"> → </span>
          <span class="ticker">${escapeHtml(e.target)}</span>
          <span class="sub">${escapeHtml(e.type)}</span>
        </div>
        <span class="count-chip">${escapeHtml(e.type)}</span>
        <div class="actions">
          <button class="admin-btn danger delete-edge">Delete</button>
        </div>
      </div>
    `).join('');
    wrap.querySelectorAll('.delete-edge').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = Number(btn.closest('.admin-row').dataset.id);
        if (!confirm(`Delete edge #${id}?`)) return;
        try {
          await api(`/admin/relationships/${id}`, { method: 'DELETE' });
          toast(`deleted edge #${id}`);
          loadEdges();
        } catch (err) { toast(err.message, 'error'); }
      });
    });
  } catch (err) {
    wrap.innerHTML = `<div class="empty">Error: ${escapeHtml(err.message)}</div>`;
  }
}

async function addEdge() {
  const src  = document.getElementById('new-edge-src').value.trim().toUpperCase();
  const tgt  = document.getElementById('new-edge-tgt').value.trim().toUpperCase();
  const type = document.getElementById('new-edge-type').value;
  if (!src || !tgt) return toast('source + target required', 'error');
  try {
    await api('/admin/relationships', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: src, target: tgt, type }),
    });
    toast(`added ${src} → ${tgt} (${type})`);
    document.getElementById('new-edge-src').value = '';
    document.getElementById('new-edge-tgt').value = '';
    const cur = document.getElementById('edges-ticker').value.trim().toUpperCase();
    if (cur === src || cur === tgt) loadEdges();
  } catch (err) { toast(err.message, 'error'); }
}

// ── Issues tab ───────────────────────────────────────────────────────────
async function loadIssues() {
  const [orphans, multi, empty] = await Promise.all([
    api('/admin/issues/orphan-companies').catch(_ => []),
    api('/admin/issues/multi-track-companies').catch(_ => []),
    api('/admin/issues/empty-tracks').catch(_ => []),
  ]);

  document.getElementById('count-orphans').textContent   = orphans.length;
  document.getElementById('count-multitrack').textContent= multi.length;
  document.getElementById('count-empty').textContent     = empty.length;
  document.getElementById('count-issues').textContent    = orphans.length + multi.length + empty.length;

  const orphansEl = document.getElementById('admin-orphans');
  orphansEl.innerHTML = orphans.length === 0
    ? '<div class="empty">No orphans ✓</div>'
    : orphans.map(c => `
        <div class="admin-row">
          <div class="primary">
            <span class="ticker">${escapeHtml(c.ticker)}</span>
            <span class="sub">${escapeHtml(c.name || '')} • ${fmtMcap(c.market_cap)}</span>
          </div>
          <span class="count-chip">0</span>
          <div class="actions">
            <button class="admin-btn" onclick="(function(){document.querySelector('[data-tab=\\'companies\\']').click(); document.getElementById('companies-search').value='${escapeHtml(c.ticker)}'; document.getElementById('companies-search').dispatchEvent(new Event('input'));})()">Open</button>
          </div>
        </div>
      `).join('');

  const multiEl = document.getElementById('admin-multitrack');
  multiEl.innerHTML = multi.length === 0
    ? '<div class="empty">No multi-track companies ✓</div>'
    : multi.map(c => `
        <div class="admin-row">
          <div class="primary">
            <span class="ticker">${escapeHtml(c.ticker)}</span>
            <span class="sub">${escapeHtml(c.name || '')}</span>
            <div class="track-tags">
              ${c.tracks.map(t => `<span class="track-tag">${escapeHtml(t.name)}</span>`).join('')}
            </div>
          </div>
          <span class="count-chip">${c.track_count}</span>
          <div class="actions"></div>
        </div>
      `).join('');

  const emptyEl = document.getElementById('admin-empty');
  emptyEl.innerHTML = empty.length === 0
    ? '<div class="empty">No empty tracks ✓</div>'
    : empty.map(t => `
        <div class="admin-row" data-id="${t.id}">
          <div class="primary">
            <span>${escapeHtml(t.name)}</span>
          </div>
          <span class="count-chip">0</span>
          <div class="actions">
            <button class="admin-btn danger delete">Delete</button>
          </div>
        </div>
      `).join('');
  emptyEl.querySelectorAll('.delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.closest('.admin-row').dataset.id);
      if (!confirm('Delete this empty track?')) return;
      try {
        await api(`/admin/tracks/${id}`, { method: 'DELETE' });
        toast('deleted');
        loadIssues();
      } catch (err) { toast(err.message, 'error'); }
    });
  });
}

// ── Tabs ─────────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.admin-tabs .tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === name);
  });
  document.querySelectorAll('.admin-tab-panel').forEach(p => {
    p.style.display = p.dataset.tab === name ? '' : 'none';
  });
  if (name === 'issues') loadIssues();
  if (name === 'companies') loadCompanies();
}

// ── Boot ─────────────────────────────────────────────────────────────────
async function init() {
  if (window.nexusAuthReady) await window.nexusAuthReady;

  let who;
  try {
    who = await api('/admin/whoami');
  } catch (err) {
    // 403 = signed in but not admin
    if (String(err.message).includes('admin-only')) {
      const res = await fetch(`${API_BASE}/admin/whoami`);
      const body = await res.json();
      document.getElementById('notice-email').textContent = body.user_email || '(no email)';
      document.getElementById('not-admin-notice').style.display = '';
      document.getElementById('admin-tabs').style.display = 'none';
      document.querySelectorAll('.admin-tab-panel').forEach(p => p.style.display = 'none');
      return;
    }
    toast(err.message, 'error');
    return;
  }

  document.getElementById('admin-user-badge').textContent =
    who.email ? `${who.email} • admin` : 'dev mode (auth off)';

  // Wire controls
  document.querySelectorAll('.admin-tabs .tab').forEach(t => {
    t.addEventListener('click', () => switchTab(t.dataset.tab));
  });
  document.getElementById('tracks-filter').addEventListener('input', e => {
    TRACK_FILTER = e.target.value;
    renderTracks();
  });
  document.getElementById('companies-search').addEventListener('input', e => {
    COMPANIES_SEARCH = e.target.value;
    COMPANIES_PAGE = 1;
    clearTimeout(COMPANIES_TIMER);
    COMPANIES_TIMER = setTimeout(loadCompanies, 250);  // debounce
  });
  document.getElementById('companies-sort').addEventListener('change', e => {
    COMPANIES_SORT = e.target.value;
    COMPANIES_PAGE = 1;
    loadCompanies();
  });
  document.getElementById('pg-first').addEventListener('click', () => { COMPANIES_PAGE = 1; loadCompanies(); });
  document.getElementById('pg-prev' ).addEventListener('click', () => { COMPANIES_PAGE = Math.max(1, COMPANIES_PAGE - 1); loadCompanies(); });
  document.getElementById('pg-next' ).addEventListener('click', () => { COMPANIES_PAGE += 1; loadCompanies(); });
  document.getElementById('pg-last' ).addEventListener('click', () => { COMPANIES_PAGE = Number(document.getElementById('pg-jump').max) || 1; loadCompanies(); });
  document.getElementById('pg-jump' ).addEventListener('change', e => {
    const n = Number(e.target.value);
    if (Number.isFinite(n) && n >= 1) { COMPANIES_PAGE = n; loadCompanies(); }
  });
  document.getElementById('edges-load').addEventListener('click', loadEdges);
  document.getElementById('edges-ticker').addEventListener('keydown', e => {
    if (e.key === 'Enter') loadEdges();
  });
  document.getElementById('new-edge-add').addEventListener('click', addEdge);

  await loadTracks();
}

init();
