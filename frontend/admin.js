/**
 * admin.js — /nexus/admin.html page
 *
 * - Waits for window.nexusAuthReady (auth.js handles Firebase login)
 * - Hits /admin/whoami to check if the signed-in user is in the allowlist
 * - If yes: loads tracks + binds the CRUD controls
 * - If no: shows a "not authorized" notice with the user's email
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

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

// ── Tracks table ─────────────────────────────────────────────────────────
let ALL_TRACKS = [];
let FILTER = '';

function renderTracksTable() {
  const wrap = document.getElementById('admin-tracks');
  const q = FILTER.trim().toLowerCase();
  const rows = q
    ? ALL_TRACKS.filter(t => t.name.toLowerCase().includes(q))
    : ALL_TRACKS;

  document.getElementById('tracks-count').textContent =
    `${rows.length} shown${q ? ` (filtered from ${ALL_TRACKS.length})` : ''}`;

  if (rows.length === 0) {
    wrap.innerHTML = '<div class="empty">No tracks match.</div>';
    return;
  }

  wrap.innerHTML = `
    <table class="admin-table">
      <thead>
        <tr>
          <th style="width:40%">Name</th>
          <th>Description</th>
          <th class="num">Companies</th>
          <th style="width:220px">Actions</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map(t => `
          <tr data-id="${t.id}">
            <td><input class="inline-edit name" value="${escapeHtml(t.name)}" /></td>
            <td><input class="inline-edit desc" placeholder="(no description)" value="${escapeHtml(t.description || '')}" /></td>
            <td class="num">${t.company_count}</td>
            <td>
              <button class="admin-btn save">Save</button>
              <button class="admin-btn merge">Merge →</button>
              <button class="admin-btn danger delete">Delete</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  wrap.querySelectorAll('tr[data-id]').forEach(row => {
    const id = Number(row.dataset.id);
    row.querySelector('.save').addEventListener('click', () => saveTrack(id, row));
    row.querySelector('.merge').addEventListener('click', () => mergeTrack(id));
    row.querySelector('.delete').addEventListener('click', () => deleteTrack(id));
  });
}

async function loadTracks() {
  const res = await fetch(`${API_BASE}/admin/tracks`);
  if (!res.ok) {
    toast(`loadTracks failed: ${res.status}`, 'error');
    return;
  }
  ALL_TRACKS = await res.json();
  renderTracksTable();
}

async function saveTrack(id, row) {
  const name = row.querySelector('.name').value.trim();
  const description = row.querySelector('.desc').value;
  const res = await fetch(`${API_BASE}/admin/tracks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  const body = await res.json();
  if (!res.ok) {
    toast(body.error || `save failed: ${res.status}`, 'error');
    return;
  }
  toast(`saved "${name}"`);
  await loadTracks();
}

async function mergeTrack(sourceId) {
  const srcName = ALL_TRACKS.find(t => t.id === sourceId)?.name || `#${sourceId}`;
  const input = prompt(
    `Merge "${srcName}" into which other track?\n\n` +
    `Enter the target track's exact name (case-insensitive match).`
  );
  if (!input) return;
  const target = ALL_TRACKS.find(t => t.name.toLowerCase() === input.trim().toLowerCase());
  if (!target) {
    toast(`no track matching "${input}"`, 'error');
    return;
  }
  if (target.id === sourceId) {
    toast('cannot merge a track into itself', 'error');
    return;
  }
  if (!confirm(`Merge "${srcName}" into "${target.name}"?\n\n` +
               `All ${ALL_TRACKS.find(t => t.id === sourceId)?.company_count || 0} ` +
               `companies from "${srcName}" will move to "${target.name}". ` +
               `"${srcName}" will be deleted. This cannot be undone.`)) return;
  const res = await fetch(`${API_BASE}/admin/tracks/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_id: sourceId, target_id: target.id }),
  });
  const body = await res.json();
  if (!res.ok) { toast(body.error || `merge failed: ${res.status}`, 'error'); return; }
  toast(`merged: ${body.moved} company links moved`);
  await loadTracks();
}

async function deleteTrack(id) {
  const name = ALL_TRACKS.find(t => t.id === id)?.name || `#${id}`;
  if (!confirm(`Delete track "${name}"?\n\nAll company→track links under it will be removed. Cannot be undone.`)) return;
  const res = await fetch(`${API_BASE}/admin/tracks/${id}`, { method: 'DELETE' });
  const body = await res.json();
  if (!res.ok) { toast(body.error || 'delete failed', 'error'); return; }
  toast(`deleted "${name}" (${body.unlinked_companies} links removed)`);
  await loadTracks();
}

// ── Edges by ticker ──────────────────────────────────────────────────────
async function loadEdges() {
  const ticker = document.getElementById('edges-ticker').value.trim().toUpperCase();
  if (!ticker) { toast('enter a ticker', 'error'); return; }
  const res = await fetch(`${API_BASE}/admin/relationships?ticker=${encodeURIComponent(ticker)}`);
  if (!res.ok) { toast(`load failed: ${res.status}`, 'error'); return; }
  const edges = await res.json();
  const wrap = document.getElementById('admin-edges');
  if (edges.length === 0) {
    wrap.innerHTML = `<div class="empty">No edges for ${escapeHtml(ticker)}.</div>`;
    return;
  }
  wrap.innerHTML = `
    <table class="admin-table">
      <thead>
        <tr><th>Source</th><th>Target</th><th>Type</th><th style="width:80px">Actions</th></tr>
      </thead>
      <tbody>
        ${edges.map(e => `
          <tr data-id="${e.id}">
            <td>${escapeHtml(e.source)}</td>
            <td>${escapeHtml(e.target)}</td>
            <td>${escapeHtml(e.type)}</td>
            <td><button class="admin-btn danger delete-edge">Delete</button></td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
  wrap.querySelectorAll('.delete-edge').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = Number(btn.closest('tr').dataset.id);
      if (!confirm(`Delete edge #${id}?`)) return;
      const res = await fetch(`${API_BASE}/admin/relationships/${id}`, { method: 'DELETE' });
      const body = await res.json();
      if (!res.ok) { toast(body.error || 'delete failed', 'error'); return; }
      toast(`deleted edge #${id}`);
      loadEdges();
    });
  });
}

async function addEdge() {
  const src  = document.getElementById('new-edge-src').value.trim().toUpperCase();
  const tgt  = document.getElementById('new-edge-tgt').value.trim().toUpperCase();
  const type = document.getElementById('new-edge-type').value;
  if (!src || !tgt) { toast('source + target required', 'error'); return; }
  const res = await fetch(`${API_BASE}/admin/relationships`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source: src, target: tgt, type }),
  });
  const body = await res.json();
  if (!res.ok) { toast(body.error || 'add failed', 'error'); return; }
  toast(`added ${src} → ${tgt} (${type})`);
  document.getElementById('new-edge-src').value = '';
  document.getElementById('new-edge-tgt').value = '';
  // Refresh the edges panel if the user is currently filtering by either endpoint
  const current = document.getElementById('edges-ticker').value.trim().toUpperCase();
  if (current === src || current === tgt) loadEdges();
}

// ── Boot ─────────────────────────────────────────────────────────────────
async function init() {
  if (window.nexusAuthReady) await window.nexusAuthReady;

  // whoami tells us if auth is required, who's signed in, and whether
  // they're in the allowlist. Single source of truth for gating the UI.
  const res = await fetch(`${API_BASE}/admin/whoami`).catch(() => null);
  const badge = document.getElementById('admin-user-badge');

  if (!res || !res.ok) {
    // Dev mode: auth disabled and /admin/whoami returns 200 with no email;
    // or prod with a non-admin user returning 403.
    if (res && res.status === 403) {
      const body = await res.json();
      badge.textContent = body.user_email || 'signed in';
      document.getElementById('notice-email').textContent = body.user_email || '(no email)';
      document.getElementById('not-admin-notice').style.display = '';
      document.getElementById('tracks-panel')?.remove();
      document.getElementById('edges-panel')?.remove();
      return;
    }
    badge.textContent = 'unreachable';
    toast(`whoami failed: ${res?.status || 'no response'}`, 'error');
    return;
  }

  const who = await res.json();
  badge.textContent = who.email ? `${who.email} • admin` : 'dev mode (auth off)';

  // Wire up controls
  document.getElementById('tracks-filter').addEventListener('input', e => {
    FILTER = e.target.value;
    renderTracksTable();
  });
  document.getElementById('edges-load').addEventListener('click', loadEdges);
  document.getElementById('edges-ticker').addEventListener('keydown', e => {
    if (e.key === 'Enter') loadEdges();
  });
  document.getElementById('new-edge-add').addEventListener('click', addEdge);

  await loadTracks();
}

init();
