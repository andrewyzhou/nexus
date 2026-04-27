/**
 * main.js — Nexus Frontend
 *
 * Tries the live backend first (GET /graph). If unreachable or empty,
 * falls back to ./data/mock.json so the demo still renders.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

// SVG icons — using inline SVG guarantees pixel-perfect centering regardless
// of font metrics. All icons are 12×12 viewBox, stroked at 2px.
const ICON_PLUS  = `<svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="1" y1="6" x2="11" y2="6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
const ICON_CLOSE = `<svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><line x1="1" y1="1" x2="9" y2="9" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="9" y1="1" x2="1" y2="9" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
const ICON_CHEVRON = `<svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><polyline points="2,3 5,7 8,3" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

// ── Edge colors by relationship type ─────────────────────────────────────────
// Note: 'ownership' was previously 'subsidiary' — renamed because the data
// covers both majority (true subsidiary) and minority (investor) stakes.
// Wikidata P355 only has a quantity qualifier on ~20% of edges so we can't
// reliably split the two; one label covers both cases.
const EDGE_COLORS = {
  competitor: '#ef4444',  // red
  supplier:   '#eab308',  // yellow
  ownership:  '#3b82f6',  // blue
};

// ── Helpers ───────────────────────────────────────────────────────────────────
// marketCap comes from the API in billions (e.g. 0.42 = $420M)
function fmtCap(b) {
  if (b == null) return '—';
  if (b >= 1000) return '$' + (b / 1000).toFixed(2) + 'T';
  if (b >= 1)    return '$' + b.toFixed(1) + 'B';
  if (b >= 0.001) return '$' + (b * 1000).toFixed(0) + 'M';
  return '<$1M';
}

// ── State ─────────────────────────────────────────────────────────────────────
let allNodes = [], allEdges = [], tracks = [];
let trackById = new Map();  // fast lookup: track.id → track object
let nodeById  = new Map();  // fast lookup: node.id  → node object
let hiddenTracks  = new Set();
let pinnedNodes   = new Set();   // individual node IDs shown regardless of track state
let excludedNodes = new Set();   // individual node IDs explicitly hidden regardless of track state
let searchQuery   = '';
let selectedNode  = null;
let simulation, svg, linkGroup, nodeGroup, zoomBehavior;

// Per-user server state (loaded after auth resolves)
let recentItems = [];   // [{item_type, item_id, label}]
let savedItems  = [];   // [{item_type, item_id, label}]
let moversByKind = {};  // { day_gainers: [{ticker,name,price,change_pct}], ... }
let liveQuotes  = {};   // { TICKER: {price, change_pct} }  populated lazily

// Quick Start: two curated lists rendered as collapsible sub-groups.
// Tracks are matched by EXACT name from the DB (no fuzzy match — it
// previously matched "Chemical for Semiconductors" → "Semiconductors").
// Companies are matched by ticker against the loaded /graph payload;
// silently skip any that don't resolve so a renamed/missing one doesn't
// blow up the section.
const QUICK_START_TRACKS = [
  // AI/Tech (4)
  'AI Chips',
  'AI Software - Large',
  'Hyperscaler',
  'Semiconductor Manufacturer',
  // Diverse (3)
  'EV & Auto - Large',
  'Medical Devices - Major',
  'Internet Retail - USA',
];
const QUICK_START_COMPANIES = [
  // Tech (4)
  'NVDA', 'MSFT', 'GOOG', 'META',
  // Diverse (3)
  'TSLA', 'JPM', 'LLY',
];

// Browse All sector buckets: each bucket maps to a fuzzy substring matched
// against the track label. A track may appear under multiple buckets.
const BROWSE_BUCKETS = [
  { id: 'tech',    label: 'Technology', match: ['ai', 'tech', 'software', 'cloud', 'cyber', 'semi', 'chip', 'data', 'saas', 'crypto', 'fintech', 'internet', 'robot'] },
  { id: 'health',  label: 'Healthcare', match: ['health', 'biotech', 'pharma', 'medic', 'gene', 'drug', 'medtech'] },
  { id: 'consumer',label: 'Consumer',   match: ['retail', 'consumer', 'food', 'beverage', 'apparel', 'auto', 'restaurant', 'travel', 'ecomm', 'gaming', 'media', 'entertainment'] },
  { id: 'finance', label: 'Finance',    match: ['bank', 'finance', 'insurance', 'payment', 'lending', 'reit', 'real estate', 'asset'] },
  { id: 'energy',  label: 'Energy',     match: ['energy', 'oil', 'gas', 'solar', 'nuclear', 'battery', 'mining', 'metal', 'utility', 'clean'] },
];

// Trending Today rows. 'trending' was dropped — Yahoo aggressively 429s the
// /v1/finance/trending/US endpoint. Day gainers/losers/actives use the
// stable yf.screen() screener API.
const TRENDING_KINDS = [
  { id: 'day_gainers',  label: 'Day Gainers',  arrow: '↑' },
  { id: 'day_losers',   label: 'Day Losers',   arrow: '↓' },
  { id: 'most_actives', label: 'Most Active',  arrow: '⇅' },
];

// ── Boot ──────────────────────────────────────────────────────────────────────
async function loadGraphData() {
  try {
    const res = await fetch(`${API_BASE}/graph`);
    if (!res.ok) throw new Error(`API ${res.status}`);
    const data = await res.json();
    if (data && Array.isArray(data.nodes) && data.nodes.length > 0) {
      console.info(`[nexus] loaded ${data.nodes.length} nodes / ${data.edges.length} edges from API`);
      return { ...data, _source: 'api' };
    }
    console.warn('[nexus] API returned empty graph, falling back to mock');
  } catch (err) {
    console.warn('[nexus] API unreachable, falling back to mock:', err.message);
  }
  const mock = await fetch('./data/mock.json').then(r => r.json());
  return { ...mock, _source: 'mock' };
}

// Per-user storage key. Prefer the Firebase uid (so state follows the user
// across browsers); fall back to an anonymous local UUID when auth is off.
function getUserId() {
  if (window.nexusUserUid) return window.nexusUserUid;
  let uid = localStorage.getItem('nexus_user_id');
  if (!uid) {
    uid = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
          const r = Math.random() * 16 | 0;
          return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    localStorage.setItem('nexus_user_id', uid);
  }
  return uid;
}

// Computed lazily so it picks up the Firebase uid after auth resolves.
let STATE_KEY = `nexus_graph_state_anon`;
const STATE_VERSION = 2;

function saveState() {
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify({
      v:             STATE_VERSION,
      pinnedNodes:   [...pinnedNodes],
      hiddenTracks:  [...hiddenTracks],
      excludedNodes: [...excludedNodes],
    }));
  } catch (_) {}
}

function loadState() {
  try {
    const raw = localStorage.getItem(STATE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      // Discard state saved before versioning was added (broken all-hidden default)
      if (!parsed.v || parsed.v < STATE_VERSION) {
        localStorage.removeItem(STATE_KEY);
        return null;
      }
      return parsed;
    }
    // One-time migration: adopt any state saved under the old un-scoped key
    const legacy = localStorage.getItem('nexus_graph_state');
    if (legacy) {
      localStorage.removeItem('nexus_graph_state');
      const parsed = JSON.parse(legacy);
      if (parsed.v && parsed.v >= STATE_VERSION) {
        localStorage.setItem(STATE_KEY, legacy);
        return parsed;
      }
    }
    return null;
  } catch (_) { return null; }
}

async function init() {
  // Block first fetch on Firebase auth when enabled (no-op otherwise).
  if (window.nexusAuthReady) await window.nexusAuthReady;

  // Re-key state now that we know the Firebase uid (or anon fallback).
  STATE_KEY = `nexus_graph_state_${getUserId()}`;

  const data = await loadGraphData();
  tracks   = data.tracks;
  trackById = new Map(tracks.map(t => [t.id, t]));
  allNodes = data.nodes.map(n => ({ ...n }));
  allEdges = data.edges.map(e => ({ ...e }));
  nodeById = new Map(allNodes.map(n => [n.id, n]));

  const saved = loadState();
  const validTrackIds = new Set(tracks.map(t => t.id));
  const validNodeIds  = new Set(allNodes.map(n => n.id));

  if (saved) {
    hiddenTracks  = new Set(saved.hiddenTracks.filter(id => validTrackIds.has(id)));
    pinnedNodes   = new Set(saved.pinnedNodes.filter(id => validNodeIds.has(id)));
    excludedNodes = new Set((saved.excludedNodes || []).filter(id => validNodeIds.has(id)));
  } else {
    // First visit: blank graph — user builds it themselves.
    hiddenTracks = new Set(tracks.map(t => t.id));
  }

  const badge = document.getElementById('source-badge');
  if (badge) badge.textContent = data._source === 'api' ? 'live' : 'demo';

  buildTrackCSS(tracks);
  buildSidebar();
  buildGraph();
  applyVisibility();

  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', onSearch);
  searchInput.addEventListener('focus', () => { if (searchInput.value.trim()) onSearch({ target: searchInput }); });
  searchInput.addEventListener('blur', () => setTimeout(hideSearchDropdown, 150));

  // Fire-and-forget initial loads for per-user lists + movers. Each section
  // hides itself if empty / failed.
  refreshRecent();
  refreshSaved();
  refreshTrending();
  // Initial live-quote fetch covers Quick Start / On Graph / etc.
  refreshLiveQuotes();
}

// ── Action helpers (used by every sidebar section) ──────────────────────────
//
// addItem / removeItem / toggleItem are the canonical way every sidebar row
// mutates pinnedNodes/hiddenTracks. They also write to the per-user "recent"
// list so the Recent section reflects whatever the user just touched.

// On-graph semantics:
//   - Company: visible on the graph regardless of how it got there
//     (pinned individually OR inherited from a visible track).
//   - Track: every member is visible. Partial-membership (some excluded
//     or one member explicitly unpinned) reads as NOT on-graph, so the
//     row's button flips back to + and clicking it restores the missing
//     members in one click.
function isItemOnGraph(item) {
  if (item.item_type === 'company') {
    const node = nodeById.get(item.item_id);
    return node ? nodeIsVisible(node) : false;
  }
  // Track
  const t = trackById.get(item.item_id);
  if (!t) return false;
  let any = false;
  for (const n of allNodes) {
    if (!(n.tracks || []).includes(t.id)) continue;
    any = true;
    if (!nodeIsVisible(n)) return false;
  }
  return any;
}

function addItem(item, { skipRecent = false } = {}) {
  if (item.item_type === 'track') {
    hiddenTracks.delete(item.item_id);
    // Adding a track means "show all of this track" — clear any prior
    // exclusions of its members so re-adding restores the full membership.
    allNodes.forEach(n => {
      if ((n.tracks || []).includes(item.item_id)) excludedNodes.delete(n.id);
    });
  } else {
    pinnedNodes.add(item.item_id);
    excludedNodes.delete(item.item_id);
  }
  if (!skipRecent) recordRecent(item);
  applyVisibility({ skipFit: true });
  syncPanelAddBtn();
}

function removeItem(item) {
  if (item.item_type === 'track') {
    hiddenTracks.add(item.item_id);
    // Also clear any explicit pins of members so × on a track really empties
    // it from the graph. (Otherwise individually-pinned members would stay.)
    allNodes.forEach(n => {
      if ((n.tracks || []).includes(item.item_id)) pinnedNodes.delete(n.id);
    });
  } else {
    pinnedNodes.delete(item.item_id);
    // Only mark as excluded if the node is currently in a visible track —
    // otherwise it'd already be invisible, no need to track an exclusion.
    const node = nodeById.get(item.item_id);
    if (node && (node.tracks || []).some(t => !hiddenTracks.has(t))) {
      excludedNodes.add(item.item_id);
    }
  }
  applyVisibility({ skipFit: true });
  syncPanelAddBtn();
}

function toggleItem(item) {
  if (isItemOnGraph(item)) removeItem(item); else addItem(item);
}

// Item shape for tracks/companies — used by all sections.
function trackItem(track) { return { item_type: 'track',   item_id: track.id, label: track.label }; }
function nodeItem(node)   { return { item_type: 'company', item_id: node.id,  label: `${node.ticker} · ${node.name}` }; }

// Re-render strategy:
//   - On Graph + Recent: full rebuild (small lists, membership changes)
//   - QuickStart / Saved / Trending / Browse: keep DOM, update +/- and ★
//     buttons in place. This preserves things like the user-opened
//     "Day Gainers" subgroup and Browse → A–Z scroll position.
function refreshSidebarRows() {
  renderOnGraph();
  renderRecent();
  updateAllRowStates();
  renderEmptyState();
  // New rows may have appeared (On Graph / Recent rebuild) — fetch their
  // live quotes if we haven't already. Cheap when cached.
  refreshLiveQuotes();
}

function updateAllRowStates() {
  // Includes the left sidebar AND the right detail panel — both render rows
  // via renderRow, so both need their +/- and ★ kept in sync after any
  // state mutation.
  document.querySelectorAll('#sidebar [data-item-key], #detail-panel [data-item-key]')
    .forEach(updateRowEl);
}

function updateRowEl(row) {
  const key = row.dataset.itemKey;
  if (!key) return;
  const [type, id] = key.split('::');
  const item = hydrateItem({ item_type: type, item_id: id });
  if (!item) return;
  const onGraph = isItemOnGraph(item);
  row.classList.toggle('is-on', onGraph);
  // Primary +/- (skipped for On Graph rows where we always want ×)
  const primary = row.querySelector('.sb-action--primary');
  if (primary && row.dataset.actionMode !== 'remove') {
    primary.classList.toggle('is-remove', onGraph);
    primary.innerHTML = onGraph ? ICON_CLOSE : ICON_PLUS;
    primary.title = onGraph ? 'Remove from graph' : 'Add to graph';
  }
  // Refresh price/change cells if a live quote landed
  if (type === 'company') {
    const node = nodeById.get(id);
    if (node) writeRowStats(row, node);
  }
  // ★ saved indicator
  const star = row.querySelector('.sb-action--star');
  if (star) {
    const saved = isSaved(item);
    star.classList.toggle('is-saved', saved);
    star.title = saved ? 'Unsave' : 'Save';
  }
}

// ── Sidebar shell ───────────────────────────────────────────────────────────
function buildSidebar() {
  // Wire up collapsibles (Trending / Browse).
  document.querySelectorAll('.sidebar-section-head--toggle').forEach(head => {
    head.addEventListener('click', () => {
      const targetId = head.dataset.target;
      const body = document.getElementById(targetId);
      if (!body) return;
      const open = body.hasAttribute('hidden');
      body.toggleAttribute('hidden', !open);
      head.classList.toggle('collapsed', !open);
      // Lazy-load Browse on first open (cheap but defers ~1k DOM nodes)
      if (open && targetId === 'browse-body') renderBrowse();
    });
  });

  // Per-user-state buttons. Stop propagation so they don't trigger the
  // surrounding section's collapse toggle.
  document.getElementById('on-graph-clear')?.addEventListener('click', e => {
    e.stopPropagation();
    clearAllPinned();
  });
  document.getElementById('recent-reset')?.addEventListener('click', e => {
    e.stopPropagation();
    resetRecent();
  });

  // One-time renders for sections whose data is sync (already in /graph
  // payload). refreshSidebarRows handles On Graph + Recent on every state
  // change but does NOT rebuild Quick Start — its DOM is preserved so chevron
  // expansions and ★ toggles stay put. We need to seed it here.
  renderQuickStart();
  renderTrending();   // empty until refreshTrending() lands; preserves layout

  // Initial render — On Graph / Recent / row stats / empty-state.
  refreshSidebarRows();
}

// ── On Graph ────────────────────────────────────────────────────────────────
// Group every visible node under its primary track so the user sees both
// "the track is active" and "here are its other members you could add".
// Companies with no track go into a 'standalone' bucket. A company is
// considered to belong to its first listed track only — most are in one,
// and surfacing duplicates would clutter On Graph for multi-track outliers.
function visibleGraphGroups() {
  const visible = allNodes.filter(nodeIsVisible);
  const byTrack = new Map();   // track.id -> { track, visibleCount }
  const standalone = [];
  for (const n of visible) {
    const primary = (n.tracks || [])[0];
    const t = primary ? trackById.get(primary) : null;
    if (!t) { standalone.push(n); continue; }
    if (!byTrack.has(t.id)) byTrack.set(t.id, { track: t, visibleCount: 0 });
    byTrack.get(t.id).visibleCount++;
  }
  // Most-populated tracks first; alphabetical tiebreaker.
  const groups = [...byTrack.values()].sort((a, b) =>
    b.visibleCount - a.visibleCount || a.track.label.localeCompare(b.track.label));
  standalone.sort((a, b) => a.ticker.localeCompare(b.ticker));
  return { groups, standalone, totalCompanies: visible.length };
}

function renderOnGraph() {
  const section = document.getElementById('on-graph-section');
  const list    = document.getElementById('on-graph-list');
  const count   = document.getElementById('on-graph-count');
  if (!section || !list) return;

  const { groups, standalone, totalCompanies } = visibleGraphGroups();
  if (!totalCompanies) {
    section.toggleAttribute('hidden', true);
    count.textContent = '';
    list.innerHTML = '';
    return;
  }
  section.toggleAttribute('hidden', false);

  // "Full" tracks = every member is on graph (uses isItemOnGraph(track)).
  let fullTrackCount = 0;
  for (const { track } of groups) {
    if (isItemOnGraph(trackItem(track))) fullTrackCount++;
  }
  count.textContent = fullTrackCount > 0
    ? `(${totalCompanies} · ${fullTrackCount} track${fullTrackCount === 1 ? '' : 's'})`
    : `(${totalCompanies})`;

  list.innerHTML = '';
  // Track-grouped: header row + always-expanded sub-list of ALL members
  for (const { track } of groups) {
    list.appendChild(renderOnGraphTrackGroup(track));
  }
  // Companies with no track shown bare
  for (const node of standalone) {
    list.appendChild(renderRow(
      { ...nodeItem(node), badge: node.ticker },
      { actionMode: 'remove' },
    ));
  }
}

// Track header row + permanently-expanded list of every member of that
// track (not just the visible ones). Each member row uses the standard
// renderRow so its +/- and ★ behave identically to the rest of the
// sidebar. The sub-list never collapses — On Graph is the place where
// removing items shouldn't bury other members behind a click.
function renderOnGraphTrackGroup(track) {
  const wrap = document.createElement('div');
  wrap.className = 'sb-row';
  // Track header — actionMode auto so it shows × when full, + when partial.
  wrap.appendChild(renderRow(
    { ...trackItem(track), color: track.color },
    { actionMode: 'auto', expandable: false },
  ));
  const sub = document.createElement('div');
  sub.className = 'sb-track-members open';   // always visible
  const members = allNodes
    .filter(n => (n.tracks || []).includes(track.id))
    .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0));
  members.forEach(n => sub.appendChild(renderRow(
    { ...nodeItem(n), badge: n.ticker },
    { /* default actionMode auto */ },
  )));
  wrap.appendChild(sub);
  return wrap;
}

function clearAllPinned() {
  if (selectedNode) closePanel();
  pinnedNodes.clear();
  // Also hide every track — "clear" should mean an empty graph, not a half-clear.
  hiddenTracks = new Set(tracks.map(t => t.id));
  applyVisibility({ skipFit: true });
  refreshSidebarRows();
}

// ── Quick Start ─────────────────────────────────────────────────────────────
// Exact label match against the loaded track list. The DB names are the
// source of truth — see backend/db/load_track_descriptions.py for the full
// list. Returns null if no track has that exact label.
function findTrackByLabel(label) {
  return tracks.find(t => t.label === label) || null;
}

function trackPreviewTickers(track, n = 5) {
  const members = allNodes
    .filter(node => (node.tracks || []).includes(track.id))
    .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0))
    .slice(0, n);
  return members.map(m => m.ticker);
}

function renderQuickStart() {
  const list = document.getElementById('quick-start-list');
  if (!list) return;
  list.innerHTML = '';

  // Tracks sub-group
  const trackItems = QUICK_START_TRACKS
    .map(label => findTrackByLabel(label))
    .filter(Boolean)
    .map(t => ({ ...trackItem(t), color: t.color }));
  if (trackItems.length) {
    list.appendChild(renderQuickStartGroup('Tracks', trackItems, /*defaultOpen*/ true));
  }

  // Companies sub-group
  const companyItems = QUICK_START_COMPANIES
    .map(tk => allNodes.find(n => n.ticker?.toUpperCase() === tk))
    .filter(Boolean)
    .map(n => ({ ...nodeItem(n), badge: n.ticker }));
  if (companyItems.length) {
    list.appendChild(renderQuickStartGroup('Companies', companyItems, /*defaultOpen*/ true));
  }
}

// Collapsible sub-group inside Quick Start. Header is a clickable .sb-trend-head
// (reused styling — same caret rotation), body is a vanilla list of rows.
function renderQuickStartGroup(label, items, defaultOpen = true) {
  const wrap = document.createElement('div');
  wrap.className = 'sb-trend-group';
  const head = document.createElement('div');
  head.className = 'sb-trend-head' + (defaultOpen ? ' open' : '');
  head.innerHTML = `
    <span class="sb-trend-label">${label}</span>
    <span class="sb-trend-count">${items.length}</span>
    <span class="sb-trend-caret"></span>
  `;
  const body = document.createElement('div');
  body.className = 'sb-trend-body';
  body.hidden = !defaultOpen;
  items.forEach(item => body.appendChild(renderRow(item, { })));
  head.addEventListener('click', () => {
    body.hidden = !body.hidden;
    head.classList.toggle('open', !body.hidden);
    if (!body.hidden) refreshLiveQuotes();
  });
  wrap.appendChild(head);
  wrap.appendChild(body);
  return wrap;
}

// ── Recent (per-user, server-backed) ────────────────────────────────────────
async function refreshRecent() {
  try {
    const r = await fetch(`${API_BASE}/recent`);
    if (r.ok) {
      recentItems = await r.json();
      renderRecent();
    }
  } catch (_) {}
}

function renderRecent() {
  const section = document.getElementById('recent-section');
  const list    = document.getElementById('recent-list');
  if (!section || !list) return;
  // Hide already-on-graph items so Recent stays useful. Keep a max of 8.
  const visible = recentItems.filter(i => !isItemOnGraph(i)).slice(0, 8);
  section.toggleAttribute('hidden', visible.length === 0);
  list.innerHTML = '';
  visible.forEach(item => {
    // Hydrate label from current data when possible (DB label may be stale)
    const hydrated = hydrateItem(item);
    if (hydrated) list.appendChild(renderRow(hydrated, { }));
  });
}

async function resetRecent() {
  try {
    await fetch(`${API_BASE}/recent`, { method: 'DELETE' });
    recentItems = [];
    renderRecent();
  } catch (_) {}
}

function recordRecent(item) {
  // Optimistically prepend so the UI updates without waiting for the server.
  recentItems = [item, ...recentItems.filter(
    i => !(i.item_type === item.item_type && i.item_id === item.item_id),
  )].slice(0, 30);
  // Server upsert (fire-and-forget).
  fetch(`${API_BASE}/recent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(item),
  }).catch(() => {});
}

// ── Saved (per-user, server-backed) ─────────────────────────────────────────
async function refreshSaved() {
  try {
    const r = await fetch(`${API_BASE}/saved`);
    if (r.ok) {
      savedItems = await r.json();
      renderSaved();
    }
  } catch (_) {}
}

function renderSaved() {
  const section = document.getElementById('saved-section');
  const list    = document.getElementById('saved-list');
  if (!section || !list) return;
  section.toggleAttribute('hidden', savedItems.length === 0);
  list.innerHTML = '';
  savedItems.forEach(item => {
    const hydrated = hydrateItem(item);
    if (hydrated) list.appendChild(renderRow(hydrated, { }));
  });
  refreshLiveQuotes();
}

function isSaved(item) {
  return savedItems.some(i => i.item_type === item.item_type && i.item_id === item.item_id);
}

function toggleSaved(item) {
  // Strip transient render-only fields (color/preview/badge/change_pct) so
  // the canonical {item_type,item_id,label} we send to the server matches
  // what GET /saved returns.
  const canonical = { item_type: item.item_type, item_id: item.item_id, label: item.label };
  if (isSaved(canonical)) {
    savedItems = savedItems.filter(i => !(i.item_type === canonical.item_type && i.item_id === canonical.item_id));
    fetch(`${API_BASE}/saved?item_type=${encodeURIComponent(canonical.item_type)}&item_id=${encodeURIComponent(canonical.item_id)}`,
          { method: 'DELETE' }).catch(() => {});
  } else {
    savedItems = [canonical, ...savedItems];
    fetch(`${API_BASE}/saved`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(canonical),
    }).catch(() => {});
  }
  renderSaved();          // Saved section's membership changed
  updateAllRowStates();   // ★ across QuickStart / Recent / Trending / Browse
}

// Take a stored {item_type,item_id,label} and resolve a richer object suitable
// for renderRow (track color/preview, node ticker badge, etc.). Returns null
// if the item no longer exists in the loaded dataset.
function hydrateItem(item) {
  if (item.item_type === 'track') {
    const t = trackById.get(item.item_id);
    if (!t) return null;
    return { ...trackItem(t), color: t.color, preview: trackPreviewTickers(t, 4) };
  }
  if (item.item_type === 'company') {
    const n = nodeById.get(item.item_id);
    if (!n) return null;
    return { ...nodeItem(n), badge: n.ticker };
  }
  return null;
}

// ── Trending Today (yfinance, cached server-side) ───────────────────────────
async function refreshTrending() {
  await Promise.all(TRENDING_KINDS.map(async k => {
    try {
      const r = await fetch(`${API_BASE}/movers/${k.id}`);
      if (!r.ok) { moversByKind[k.id] = []; return; }
      const data = await r.json();
      moversByKind[k.id] = (data.items || []).slice(0, 10);
    } catch (_) {
      moversByKind[k.id] = [];
    }
  }));
  renderTrending();
}

function renderTrending() {
  const list = document.getElementById('trending-list');
  if (!list) return;
  list.innerHTML = '';

  TRENDING_KINDS.forEach(kind => {
    const items = moversByKind[kind.id] || [];
    // Header row (clicking expands inline)
    const wrapper = document.createElement('div');
    wrapper.className = 'sb-trend-group';

    const header = document.createElement('div');
    header.className = 'sb-trend-head';
    header.innerHTML = `
      <span class="sb-trend-arrow">${kind.arrow}</span>
      <span class="sb-trend-label">${kind.label}</span>
      <span class="sb-trend-count">${items.length || ''}</span>
      <span class="sb-trend-caret"></span>
    `;
    if (!items.length) header.classList.add('sb-trend-head--empty');

    const body = document.createElement('div');
    body.className = 'sb-trend-body';
    body.hidden = true;

    items.forEach(it => {
      const node = allNodes.find(n => n.ticker?.toUpperCase() === (it.ticker || '').toUpperCase());
      // Even if we don't have the company in our universe, render a "+ ticker"
      // row that's not actionable (we can't add unknown tickers to the graph).
      if (!node) {
        const row = document.createElement('div');
        row.className = 'sb-item sb-item--readonly';
        row.innerHTML = `
          <span class="sb-item-ticker">${it.ticker}</span>
          <span class="sb-item-name">${it.name || ''}</span>
          ${renderChangePct(it.change_pct)}
        `;
        body.appendChild(row);
        return;
      }
      const item = nodeItem(node);
      const row = renderRow({ ...item, badge: node.ticker, change_pct: it.change_pct }, { });
      body.appendChild(row);
    });

    if (items.length) {
      header.addEventListener('click', () => {
        body.hidden = !body.hidden;
        header.classList.toggle('open', !body.hidden);
        if (!body.hidden) refreshLiveQuotes();
      });
    }

    wrapper.appendChild(header);
    wrapper.appendChild(body);
    list.appendChild(wrapper);
  });
  // Trending rows have their own change_pct from the screener; this also
  // hydrates the price cell from the live-quote cache.
  refreshLiveQuotes();
}

function renderChangePct(p) {
  if (p == null) return '';
  // Yahoo screener returns percent points (e.g. 5.42 = +5.42%); our /quotes
  // endpoint also returns percent points. No /100 needed.
  const v = Number(p);
  if (!isFinite(v)) return '';
  const cls = v >= 0 ? 'sb-pct sb-pct--up' : 'sb-pct sb-pct--down';
  const sign = v >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
}

function fmtPrice(p) {
  if (p == null) return '';
  const v = Number(p);
  if (!isFinite(v)) return '';
  return '$' + v.toFixed(v >= 100 ? 0 : 2);
}

// Track stats helpers — derive from the loaded /graph payload, no API call.
function trackMemberCount(t) {
  let n = 0;
  for (const node of allNodes) if ((node.tracks || []).includes(t.id)) n++;
  return n;
}
function trackTopSector(t) {
  const counts = new Map();
  for (const node of allNodes) {
    if (!(node.tracks || []).includes(t.id)) continue;
    const s = (node.sector || '').trim();
    if (!s) continue;
    counts.set(s, (counts.get(s) || 0) + 1);
  }
  let best = null, max = 0;
  for (const [s, c] of counts) if (c > max) { max = c; best = s; }
  return best;
}

// Fill the .sb-item-mcap and .sb-item-pct cells for a company row.
// `priorPct` (optional) is the change_pct from a Trending mover row, which
// beats the lazy-fetched live quote for that one section.
function writeRowStats(row, node, priorPct) {
  const mcapEl = row.querySelector('.sb-item-mcap');
  const pctEl  = row.querySelector('.sb-item-pct');
  if (mcapEl) mcapEl.textContent = fmtCap(node.marketCap);
  const live = liveQuotes[node.ticker?.toUpperCase()];
  const pct = (priorPct != null) ? priorPct
            : (live && live.change_pct != null) ? live.change_pct
            : null;
  if (pctEl) pctEl.innerHTML = renderChangePct(pct);
}

// Lazy-fetch live price + day-change for every ticker currently rendered
// in the sidebar. Cheap when most are already cached server-side.
let _quotesInflight = false;
async function refreshLiveQuotes() {
  if (_quotesInflight) return;
  const need = new Set();
  document.querySelectorAll('#sidebar [data-item-key^="company::"], #detail-panel [data-item-key^="company::"]').forEach(row => {
    const id = row.dataset.itemKey.split('::')[1];
    const node = nodeById.get(id);
    const tk = node && node.ticker ? node.ticker.toUpperCase() : null;
    if (tk && !liveQuotes[tk]) need.add(tk);
  });
  if (!need.size) return;
  _quotesInflight = true;
  try {
    const list = [...need].slice(0, 200).join(',');
    const r = await fetch(`${API_BASE}/quotes?tickers=${encodeURIComponent(list)}`);
    if (r.ok) {
      const data = await r.json();
      Object.assign(liveQuotes, data);
      updateAllRowStates();
    }
  } catch (_) {} finally {
    _quotesInflight = false;
  }
}

// ── Browse All ──────────────────────────────────────────────────────────────
// Two top-level groups (Tracks, Companies); each group has an A–Z list and
// optional sector buckets. Lazy-rendered so the initial paint doesn't try to
// build 5000 rows.

let browseRendered = false;

function renderBrowse() {
  const list = document.getElementById('browse-list');
  if (!list) return;
  // Browse only renders once per page load — cheaper than rebuilding every
  // pin/unpin. The action icons inside still update because they use `.is-on`
  // class which we reset on each row build.
  if (browseRendered) {
    // Just refresh the on-graph state of existing rows.
    list.querySelectorAll('[data-item-key]').forEach(row => {
      const key = row.dataset.itemKey;
      const [type, id] = key.split('::');
      const item = type === 'track' ? hydrateItem({ item_type: 'track', item_id: id })
                                    : hydrateItem({ item_type: 'company', item_id: id });
      if (!item) return;
      const onGraph = isItemOnGraph(item);
      row.classList.toggle('is-on', onGraph);
      const btn = row.querySelector('.sb-action');
      if (btn) {
        btn.innerHTML = onGraph ? ICON_CLOSE : ICON_PLUS;
        btn.title = onGraph ? 'Remove from graph' : 'Add to graph';
      }
    });
    return;
  }
  browseRendered = true;
  list.innerHTML = '';

  // Tracks group
  list.appendChild(renderBrowseGroup({
    id: 'browse-tracks',
    label: `Tracks (${tracks.length})`,
    children: [
      { id: 'tracks-az', label: 'All A–Z', items: tracks.slice().sort((a,b) => a.label.localeCompare(b.label)).map(t => ({ ...trackItem(t), color: t.color })) },
      ...BROWSE_BUCKETS.map(b => {
        const matched = tracks
          .filter(t => b.match.some(m => t.label.toLowerCase().includes(m)))
          .sort((a, b) => a.label.localeCompare(b.label))
          .map(t => ({ ...trackItem(t), color: t.color }));
        return { id: `tracks-${b.id}`, label: `${b.label} (${matched.length})`, items: matched };
      }),
    ],
  }));

  // Companies group
  const companiesAZ = allNodes
    .slice()
    .sort((a, b) => a.ticker.localeCompare(b.ticker))
    .map(n => ({ ...nodeItem(n), badge: n.ticker }));

  // By-sector bucket (uses the sector field on each node)
  const sectorMap = new Map();
  allNodes.forEach(n => {
    const s = (n.sector || 'Uncategorized').trim() || 'Uncategorized';
    if (!sectorMap.has(s)) sectorMap.set(s, []);
    sectorMap.get(s).push({ ...nodeItem(n), badge: n.ticker });
  });
  const sectorChildren = [...sectorMap.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(([s, items]) => ({
      id: `companies-sector-${s}`,
      label: `${s} (${items.length})`,
      items: items.sort((a, b) => a.label.localeCompare(b.label)),
    }));

  list.appendChild(renderBrowseGroup({
    id: 'browse-companies',
    label: `Companies (${allNodes.length})`,
    children: [
      { id: 'companies-az', label: 'All A–Z', items: companiesAZ },
      { id: 'companies-by-sector', label: 'By Sector', children: sectorChildren },
    ],
  }));
}

function renderBrowseGroup(group) {
  const wrap = document.createElement('div');
  wrap.className = 'sb-browse-group';

  const head = document.createElement('div');
  head.className = 'sb-browse-head collapsed';
  head.innerHTML = `<span class="sb-browse-label">${group.label}</span><span class="sb-trend-caret"></span>`;
  wrap.appendChild(head);

  const body = document.createElement('div');
  body.className = 'sb-browse-body';
  body.hidden = true;
  wrap.appendChild(body);

  let built = false;
  head.addEventListener('click', () => {
    body.hidden = !body.hidden;
    head.classList.toggle('collapsed', body.hidden);
    if (!body.hidden && !built) {
      built = true;
      (group.children || []).forEach(child => body.appendChild(renderBrowseChild(child)));
    }
  });

  return wrap;
}

function renderBrowseChild(child) {
  // A child may be either a leaf list (has `items`) or another group
  // (has `children`).
  if (child.children) return renderBrowseGroup(child);
  return renderBrowseLeaf(child);
}

function renderBrowseLeaf(leaf) {
  const wrap = document.createElement('div');
  wrap.className = 'sb-browse-leaf';

  const head = document.createElement('div');
  head.className = 'sb-browse-leaf-head collapsed';
  head.innerHTML = `<span class="sb-browse-leaf-label">${leaf.label}</span><span class="sb-trend-caret"></span>`;
  wrap.appendChild(head);

  const body = document.createElement('div');
  body.className = 'sb-browse-leaf-body';
  body.hidden = true;
  wrap.appendChild(body);

  let built = false;
  head.addEventListener('click', () => {
    body.hidden = !body.hidden;
    head.classList.toggle('collapsed', body.hidden);
    if (!body.hidden && !built) {
      built = true;
      // Render rows in chunks so a 5000-item leaf doesn't jank the UI.
      const items = leaf.items || [];
      let idx = 0;
      const CHUNK = 80;
      const renderChunk = () => {
        const stop = Math.min(idx + CHUNK, items.length);
        for (; idx < stop; idx++) body.appendChild(renderRow(items[idx], { }));
        if (idx < items.length) requestAnimationFrame(renderChunk);
        else refreshLiveQuotes();   // hydrate stats once leaf is fully built
      };
      renderChunk();
    }
  });

  return wrap;
}

// ── Generic row renderer (used by every section) ────────────────────────────
//
// item: { item_type, item_id, label, color?, preview?, badge?, change_pct? }
// opts: { actionMode: 'auto' | 'remove' | 'none',  // primary +/- icon
//         showStar: boolean,                       // ★ save toggle
//         expandable: boolean,                     // chevron → member list (tracks only)
//         showChange: boolean }                    // chip for change_pct

function renderRow(item, opts = {}) {
  const {
    actionMode = 'auto',
    showStar   = true,
    expandable = (item.item_type === 'track'),
    showChange = (item.change_pct != null),
  } = opts;

  // Wrapper holds row + (optional) inline expansion of member companies.
  const wrapper = document.createElement('div');
  wrapper.className = 'sb-row';

  const onGraph = isItemOnGraph(item);
  const row = document.createElement('div');
  row.className = `sb-item${onGraph ? ' is-on' : ''}`;
  row.dataset.itemKey = `${item.item_type}::${item.item_id}`;
  if (actionMode === 'remove') row.dataset.actionMode = 'remove';

  // Track rows: color dot + label + (sector · member count).
  // Company rows: ticker + name + market cap + price + change%.
  if (item.item_type === 'track') {
    const dot = document.createElement('span');
    dot.className = 'sb-item-dot';
    dot.style.background = item.color || '#888';
    row.appendChild(dot);
    const label = document.createElement('span');
    label.className = 'sb-item-label';
    label.textContent = item.label;
    row.appendChild(label);
    const t = trackById.get(item.item_id);
    if (t) {
      const meta = document.createElement('span');
      meta.className = 'sb-item-meta';
      const sector = trackTopSector(t);
      const count  = trackMemberCount(t);
      meta.textContent = sector ? `${sector} · ${count}` : `${count}`;
      meta.title = `${count} compan${count === 1 ? 'y' : 'ies'}${sector ? ` · top sector: ${sector}` : ''}`;
      row.appendChild(meta);
    }
  } else {
    const badge = document.createElement('span');
    badge.className = 'sb-item-ticker';
    badge.textContent = item.badge || item.label.split(' ')[0];
    row.appendChild(badge);
    const label = document.createElement('span');
    label.className = 'sb-item-label';
    label.textContent = item.label.includes(' · ') ? item.label.split(' · ')[1] : item.label;
    row.appendChild(label);

    // Stats: market cap + day change %. Price was dropped — too redundant
    // with change% and made the row crowded. Cells are present even when
    // empty so updateRowEl can refresh them in place once refreshLiveQuotes
    // lands. Trending sections pre-populate change_pct on the item itself.
    const node = nodeById.get(item.item_id);
    if (node) {
      const mcap = document.createElement('span');
      mcap.className = 'sb-item-mcap';
      mcap.textContent = fmtCap(node.marketCap);
      row.appendChild(mcap);

      const pct = document.createElement('span');
      pct.className = 'sb-item-pct';
      row.appendChild(pct);

      writeRowStats(row, node, item.change_pct);
    }
  }

  // Track-row chevron: expand inline to show member companies, each with
  // their own +/- so users can pin individual companies from a track without
  // adding the whole track.
  let memberBody = null;
  if (item.item_type === 'track' && expandable) {
    const chevron = document.createElement('button');
    chevron.className = 'sb-action sb-action--chevron';
    chevron.title = 'Show companies';
    chevron.innerHTML = ICON_CHEVRON;
    memberBody = document.createElement('div');
    // .open class controls visibility — can't use [hidden] attr because
    // .sb-track-members has display:flex which would override it.
    memberBody.className = 'sb-track-members';
    let built = false;
    chevron.addEventListener('click', e => {
      e.stopPropagation();
      const open = !memberBody.classList.contains('open');
      memberBody.classList.toggle('open', open);
      chevron.classList.toggle('open', open);
      if (open && !built) {
        built = true;
        const t = trackById.get(item.item_id);
        if (!t) { memberBody.innerHTML = '<div class="sb-empty">No companies</div>'; return; }
        const members = allNodes
          .filter(n => (n.tracks || []).includes(t.id))
          .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0));
        if (!members.length) {
          memberBody.innerHTML = '<div class="sb-empty">No companies</div>';
          return;
        }
        members.forEach(n => memberBody.appendChild(renderRow(
          { ...nodeItem(n), badge: n.ticker },
          { showStar: true, expandable: false },
        )));
      }
    });
    row.appendChild(chevron);
  }

  // ↗ Open the dedicated detail page (stock.html or track.html). Always
  // present so the row body can stay non-navigating (clicking the row body
  // opens the side panel for companies / toggles the chevron for tracks).
  const openPage = document.createElement('a');
  openPage.className = 'sb-action sb-action--open';
  openPage.title = item.item_type === 'company' ? 'Open stock page' : 'Open track page';
  openPage.innerHTML = '↗';
  openPage.href = item.item_type === 'company'
    ? `stock.html?ticker=${encodeURIComponent((nodeById.get(item.item_id)?.ticker) || item.item_id)}`
    : `track.html?slug=${encodeURIComponent(item.item_id)}`;
  openPage.addEventListener('click', e => e.stopPropagation());
  row.appendChild(openPage);

  // ★ Save toggle (skipped on On Graph rows)
  if (showStar) {
    const star = document.createElement('button');
    star.className = 'sb-action sb-action--star' + (isSaved(item) ? ' is-saved' : '');
    star.title = isSaved(item) ? 'Unsave' : 'Save';
    star.textContent = '★';
    star.addEventListener('click', e => { e.stopPropagation(); toggleSaved(item); });
    row.appendChild(star);
  }

  // Primary +/- action
  if (actionMode !== 'none') {
    const action = document.createElement('button');
    action.className = 'sb-action sb-action--primary';
    const showRemove = actionMode === 'remove' || onGraph;
    action.classList.toggle('is-remove', showRemove);
    action.innerHTML = showRemove ? ICON_CLOSE : ICON_PLUS;
    action.title = showRemove ? 'Remove from graph' : 'Add to graph';
    action.addEventListener('click', e => {
      e.stopPropagation();
      if (actionMode === 'remove' || isItemOnGraph(item)) removeItem(item);
      else addItem(item);
    });
    row.appendChild(action);
  }

  // Click on the body (not the buttons): companies open the detail panel.
  // Tracks toggle the chevron expand if expandable, otherwise nothing —
  // sidebar shouldn't navigate users away mid-exploration.
  row.addEventListener('click', e => {
    if (e.target.closest('.sb-action')) return;
    if (item.item_type === 'company') {
      const n = nodeById.get(item.item_id);
      if (n) openPanel(n);
    } else if (memberBody) {
      // Synthesize a chevron click so toggle logic stays in one place.
      row.querySelector('.sb-action--chevron')?.click();
    }
  });

  wrapper.appendChild(row);
  if (memberBody) wrapper.appendChild(memberBody);
  return wrapper;
}

// ── Empty-state center panel ────────────────────────────────────────────────
function renderEmptyState() {
  const emptyEl = document.getElementById('graph-empty');
  if (!emptyEl) return;
  const visible = allNodes.filter(nodeIsVisible);
  emptyEl.toggleAttribute('hidden', visible.length > 0);
  if (visible.length > 0) return;

  const sug = document.getElementById('graph-empty-suggestions');
  if (!sug) return;
  sug.innerHTML = '';

  // Two columns matching the sidebar's Quick Start: Tracks + Companies.
  // Resolved against the loaded /graph payload — anything missing is
  // silently skipped.
  const trackItems = QUICK_START_TRACKS
    .map(label => findTrackByLabel(label))
    .filter(Boolean)
    .map(t => ({ ...trackItem(t), color: t.color }));

  const companyItems = QUICK_START_COMPANIES
    .map(tk => allNodes.find(n => n.ticker?.toUpperCase() === tk))
    .filter(Boolean)
    .map(n => nodeItem(n));

  const renderColumn = (heading, items) => {
    const col = document.createElement('div');
    col.className = 'graph-empty-col';
    const h = document.createElement('div');
    h.className = 'graph-empty-col-head';
    h.textContent = heading;
    col.appendChild(h);
    items.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'graph-empty-suggestion';
      // Color-tint track buttons with the track color so they read like
      // their sidebar counterparts; companies stay neutral accent.
      if (item.item_type === 'track' && item.color) {
        btn.style.color = item.color;
        btn.style.borderColor = item.color + '66';
        btn.style.background = item.color + '14';
      }
      btn.textContent = `+ ${item.label.split(' · ').slice(-1)[0]}`;
      btn.addEventListener('click', () => addItem(item));
      col.appendChild(btn);
    });
    return col;
  };

  if (trackItems.length)   sug.appendChild(renderColumn('Tracks',    trackItems));
  if (companyItems.length) sug.appendChild(renderColumn('Companies', companyItems));
}

// ── Inject track colours as CSS vars (in case they differ from defaults) ──────
function buildTrackCSS(tracks) {
  const root = document.documentElement;
  tracks.forEach(t => {
    root.style.setProperty(`--track-${t.id}`, t.color);
  });
}

function buildEdgeLegend() {
  const container = document.getElementById('edge-legend');
  container.innerHTML = '';
  Object.entries(EDGE_COLORS).forEach(([type, color]) => {
    const item = document.createElement('div');
    item.className = 'edge-legend-item';
    const ARROW_LABELS = {
      ownership: ['Parent', 'Subsidiary'],
      supplier:  ['Supplier', 'Customer'],
    };
    const hasArrow = type in ARROW_LABELS;
    if (hasArrow) {
      const [from, to] = ARROW_LABELS[type];
      item.innerHTML = `
        <span class="edge-legend-label" style="color:var(--text-secondary)">${from}</span>
        <svg class="edge-swatch-arrow" viewBox="0 0 28 8" xmlns="http://www.w3.org/2000/svg">
          <line x1="0" y1="4" x2="21" y2="4" stroke="${color}" stroke-width="1.5"/>
          <polygon points="19,1 28,4 19,7" fill="${color}"/>
        </svg>
        <span class="edge-legend-label" style="color:var(--text-secondary)">${to}</span>
      `;
    } else {
      const label = type.charAt(0).toUpperCase() + type.slice(1);
      item.innerHTML = `
        <span class="edge-legend-label" style="color:var(--text-secondary)">${label}</span>
        <span class="edge-swatch" style="background:${color}"></span>
        <span class="edge-legend-label" style="color:var(--text-secondary)">${label}</span>
      `;
    }
    container.appendChild(item);
  });
}

function toggleTrack(trackId) {
  const t = trackById.get(trackId);
  if (!t) return;
  toggleItem(trackItem(t));
}

function fuzzyScore(q, target) {
  const t = target.toLowerCase();
  if (t === q)           return 100;
  if (t.startsWith(q))   return 90;
  if (t.includes(q))     return 80;
  // word-boundary prefix: e.g. "pri" matches "3D Printing"
  if (t.split(/[\s\-_()]+/).some(w => w.startsWith(q))) return 70;
  // subsequence: all query chars appear in order
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  if (qi === q.length) return Math.max(10, 60 - (t.length - q.length));
  return -1;
}

function onSearch(e) {
  const q = e.target.value.trim().toLowerCase();
  searchQuery = q;
  if (!q) { hideSearchDropdown(); return; }

  const scoredTracks = tracks
    .map(t => ({ t, score: fuzzyScore(q, t.label) }))
    .filter(x => x.score >= 0)
    .sort((a, b) => b.score - a.score);

  const scoredNodes = allNodes
    .map(n => ({ n, score: Math.max(fuzzyScore(q, n.ticker), fuzzyScore(q, n.name)) }))
    .filter(x => x.score >= 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 8);

  if (!scoredTracks.length && !scoredNodes.length) { hideSearchDropdown(); return; }

  const nodesFirst = (scoredNodes[0]?.score ?? -1) >= (scoredTracks[0]?.score ?? -1);
  showSearchDropdown(scoredTracks.map(x => x.t), scoredNodes.map(x => x.n), nodesFirst);
}

function showSearchDropdown(matchedTracks, matchedNodes, nodesFirst = false) {
  let dropdown = document.getElementById('search-dropdown');
  if (!dropdown) {
    dropdown = document.createElement('div');
    dropdown.id = 'search-dropdown';
    document.querySelector('.search-wrap').appendChild(dropdown);
  }

  dropdown.innerHTML = '';

  const renderTracks = () => {
    if (!matchedTracks.length) return;
    const header = document.createElement('div');
    header.className = 'search-dropdown-header';
    header.textContent = 'Tracks';
    dropdown.appendChild(header);
    matchedTracks.forEach(t => {
      const item = document.createElement('div');
      item.className = 'search-dropdown-item';
      item.innerHTML = `<span class="search-dot" style="background:${t.color}"></span><span>${t.label}</span>`;
      item.addEventListener('mousedown', () => selectSearchTrack(t.id));
      dropdown.appendChild(item);
    });
  };

  const renderNodes = () => {
    if (!matchedNodes.length) return;
    const header = document.createElement('div');
    header.className = 'search-dropdown-header';
    header.textContent = 'Companies';
    dropdown.appendChild(header);
    matchedNodes.forEach(n => {
      const t = tracks.find(t => t.id === n.track);
      const item = document.createElement('div');
      item.className = 'search-dropdown-item';
      item.innerHTML = `
        <span class="search-ticker" style="color:${t ? t.color : '#888'}">${n.ticker}</span>
        <span class="search-name">${n.name}</span>
      `;
      item.addEventListener('mousedown', () => selectSearchNode(n));
      dropdown.appendChild(item);
    });
  };

  if (nodesFirst) { renderNodes(); renderTracks(); }
  else            { renderTracks(); renderNodes(); }

  dropdown.style.display = 'block';
}

function hideSearchDropdown() {
  const d = document.getElementById('search-dropdown');
  if (d) d.style.display = 'none';
}

function selectSearchTrack(trackId) {
  const t = trackById.get(trackId);
  if (t) addItem(trackItem(t));
  document.getElementById('search-input').value = '';
  searchQuery = '';
  hideSearchDropdown();
}

function selectSearchNode(n) {
  addItem(nodeItem(n));
  // Fit all visible nodes once the new node has a position
  setTimeout(() => fitView(allNodes.filter(nodeIsVisible)), 120);
  document.getElementById('search-input').value = '';
  searchQuery = '';
  hideSearchDropdown();
}

function zoomToNode(n) {
  const container = document.getElementById('graph-canvas');
  const W = container.clientWidth, H = container.clientHeight;
  const scale = 1.8;
  const tx = W / 2 - scale * n.x;
  const ty = H / 2 - scale * n.y;
  svg.transition().duration(500)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

function applyVisibility(opts = {}) {
  // Force-rebuild instead of toggling opacity — the universe has
  // 4000+ nodes, so we only ever simulate the visible subset.
  saveState();
  renderGraph(opts);
  // Sidebar mirrors graph state; empty state shows when nothing is visible.
  if (typeof refreshSidebarRows === 'function') refreshSidebarRows();
}

// ── D3 Graph ──────────────────────────────────────────────────────────────────
function nodeRadius(d) {
  // scale by log1p(marketCap); min 16px so 5-char tickers always fit
  const r = Math.max(16, Math.min(32, 8 + Math.log1p(d.marketCap) * 2.4));
  d._baseR = r;
  return r;
}

function trackColor(d) {
  // For multi-track companies, prefer whichever of the node's tracks is
  // currently visible — that's the track the user is looking at right now.
  const ids = (d.tracks && d.tracks.length) ? d.tracks : [d.track];
  const visibleId = ids.find(id => !hiddenTracks.has(id));
  const pickId = visibleId || ids[0];
  const t = trackById.get(pickId);
  return t ? t.color : '#888888';
}

function nodeIsVisible(d) {
  if (excludedNodes.has(d.id)) return false;
  if (pinnedNodes.has(d.id)) return true;
  if (Array.isArray(d.tracks)) {
    return d.tracks.length > 0 && d.tracks.some(id => !hiddenTracks.has(id));
  }
  if (!d.track || d.track === 'uncategorized') return false;
  return !hiddenTracks.has(d.track);
}

function syncPanelAddBtn() {
  if (!selectedNode) return;
  const btn = document.getElementById('panel-add-btn');
  if (!btn) return;
  const onGraph = nodeIsVisible(selectedNode);
  btn.classList.toggle('on-graph', onGraph);
  btn.textContent = onGraph ? '✕ Remove from graph' : '+ Add to graph';
}

let zoomLayer;
let lastVisibleCount = 0;

function buildGraph() {
  svg = d3.select('#graph-canvas')
    .append('svg')
    .attr('width', '100%')
    .attr('height', '100%');

  // ── Defs: arrow markers per edge type ──
  const defs = svg.append('defs');
  Object.entries(EDGE_COLORS).forEach(([type, color]) => {
    defs.append('marker')
      .attr('id', `arrow-${type}`)
      .attr('viewBox', '0 0 6 6')
      .attr('refX', 6)
      .attr('refY', 3)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto-start-reverse')
      .append('path')
        .attr('d', 'M0,0 L6,3 L0,6 Z')
        .attr('fill', color);
  });

  // ── Zoom layer ──
  zoomLayer = svg.append('g').attr('class', 'zoom-layer');

  zoomBehavior = d3.zoom()
    .scaleExtent([0.2, 4])
    .on('zoom', e => zoomLayer.attr('transform', e.transform));

  svg.call(zoomBehavior);

  svg.on('dblclick.zoom', () => {
    svg.transition().duration(500)
      .call(zoomBehavior.transform, d3.zoomIdentity);
  });

  linkGroup = zoomLayer.append('g').attr('class', 'links');
  nodeGroup = zoomLayer.append('g').attr('class', 'nodes');

  renderGraph();
}

/**
 * Fit the zoom transform so all nodes are visible with padding.
 * Called after the simulation settles to auto-center the graph.
 * Accounts for the detail panel width when it's open.
 */
function fitView(nodes) {
  if (!nodes || nodes.length === 0) return;
  const container = document.getElementById('graph-canvas');
  const panelOpen = panel && panel.classList.contains('open');
  const panelW = panelOpen ? (parseInt(getComputedStyle(document.documentElement).getPropertyValue('--panel-w')) || 360) : 0;
  const W = container.clientWidth - panelW;
  const H = container.clientHeight;

  const xs = nodes.map(n => n.x).filter(v => isFinite(v));
  const ys = nodes.map(n => n.y).filter(v => isFinite(v));
  if (!xs.length) return;

  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 60;
  const bW = (maxX - minX) || 1;
  const bH = (maxY - minY) || 1;

  const scale = Math.min(
    (W - pad * 2) / bW,
    (H - pad * 2) / bH,
    1.4   // don't zoom in past 1.4×
  );
  const cx = W / 2;  // center of available canvas (left of panel)
  const tx = cx - scale * (minX + maxX) / 2;
  const ty = H / 2 - scale * (minY + maxY) / 2;

  svg.transition().duration(500)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

/**
 * Rebuild the SVG nodes/links from the currently visible subset of allNodes.
 * Called from init() and from applyVisibility() whenever filters change.
 * Rendering only the visible subset keeps the force simulation tractable
 * even though the full universe has 4000+ tickers.
 */
function renderGraph({ skipFit = false } = {}) {
  if (!nodeGroup) return;
  const container = document.getElementById('graph-canvas');
  const W = container.clientWidth;
  const H = container.clientHeight;

  const visibleNodes = allNodes.filter(nodeIsVisible);
  const nodesAdded = visibleNodes.length > lastVisibleCount;
  lastVisibleCount = visibleNodes.length;
  if (nodesAdded) skipFit = false;
  const idSet = new Set(visibleNodes.map(n => n.id));
  const visibleEdges = allEdges.filter(e => {
    const s = typeof e.source === 'object' ? e.source.id : e.source;
    const t = typeof e.target === 'object' ? e.target.id : e.target;
    return idSet.has(s) && idSet.has(t);
  });

  // Wipe previous render
  if (simulation) simulation.stop();
  linkGroup.selectAll('*').remove();
  nodeGroup.selectAll('*').remove();

  if (visibleNodes.length === 0) {
    return;
  }

  // Keep already-settled positions; only initialize nodes appearing for the first time.
  // Spawn new arrivals close to the center so the gravity forces keep clusters together.
  visibleNodes.forEach(n => {
    if (!isFinite(n.x) || !isFinite(n.y)) {
      const angle = Math.random() * 2 * Math.PI;
      const r = 60 + Math.random() * 60;   // 60–120 px from center
      n.x = W / 2 + Math.cos(angle) * r;
      n.y = H / 2 + Math.sin(angle) * r;
    }
    n.vx = 0;
    n.vy = 0;
  });

  let fitDone = false;

  // Detect parallel edges BEFORE forceLink mutates source/target into objects.
  // Use the raw string IDs from allEdges (visibleEdges are references to the same objects).
  const pairCount = {};
  visibleEdges.forEach(e => {
    const a = typeof e.source === 'object' ? e.source.id : e.source;
    const b = typeof e.target === 'object' ? e.target.id : e.target;
    const key = [a, b].sort().join('||');
    pairCount[key] = (pairCount[key] || 0) + 1;
  });
  const pairIndex = {};
  visibleEdges.forEach(e => {
    const a = typeof e.source === 'object' ? e.source.id : e.source;
    const b = typeof e.target === 'object' ? e.target.id : e.target;
    const key = [a, b].sort().join('||');
    if (pairIndex[key] === undefined) pairIndex[key] = 0;
    e._parallel = pairCount[key] > 1;
    e._pairKey  = key;
    e._pairIdx  = pairIndex[key]++;
  });

  simulation = d3.forceSimulation(visibleNodes)
    .force('link', d3.forceLink(visibleEdges).id(d => d.id).distance(65).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-320))
    // forceX/Y apply per-node gravity so isolated clusters don't drift away.
    // forceCenter only corrects the centroid — it can't stop components from flying apart.
    .force('x', d3.forceX(W / 2).strength(0.05))
    .force('y', d3.forceY(H / 2).strength(0.05))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 20))
    .alphaDecay(0.028);

  linkGroup.selectAll('path.edge')
    .data(visibleEdges)
    .enter().append('path')
    .attr('class', 'edge')
    .attr('fill', 'none')
    .attr('stroke', d => EDGE_COLORS[d.type] || '#888')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 1)
    .attr('marker-end', d => (d.type === 'ownership' || d.type === 'supplier') ? `url(#arrow-${d.type})` : null);

  const nodeEl = nodeGroup.selectAll('g')
    .data(visibleNodes)
    .enter().append('g')
    .attr('class', 'node-g')
    .style('cursor', 'pointer')
    .call(
      d3.drag()
        .on('start', dragStart)
        .on('drag',  dragged)
        .on('end',   dragEnd)
    )
    .on('mouseover', onNodeHover)
    .on('mousemove', onNodeMove)
    .on('mouseout',  onNodeOut)
    .on('click',     onNodeClick);

  // Filled colored disc. Stroke and label color are theme-driven via CSS so
  // both dark and light modes render legibly (see style.css node rules).
  nodeEl.append('circle')
    .attr('class', 'node-body')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => trackColor(d));

  nodeEl.append('text')
    .attr('class', 'node-label')
    .text(d => d.ticker)
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'central')
    .attr('font-size', d => Math.max(9, Math.min(11, nodeRadius(d) * 0.55)))
    .attr('pointer-events', 'none');

  simulation.on('tick', () => {
    linkGroup.selectAll('path.edge').each(function(d) {
      const sx = d.source.x, sy = d.source.y;
      const tx = d.target.x, ty = d.target.y;
      const dx = tx - sx, dy = ty - sy;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / dist, uy = dy / dist;
      const sr = d.source._baseR || 16;
      const tr = d.target._baseR || 16;
      // Start/end points trimmed to node radius
      const x1 = sx + ux * sr, y1 = sy + uy * sr;
      const x2 = tx - ux * tr, y2 = ty - uy * tr;

      let pathD;
      if (d._parallel) {
        // Use the canonical node-pair order (sorted by id) to get a stable
        // perpendicular direction — independent of which node is source/target.
        const [idA, idB] = d._pairKey.split('||');
        const canonFlip = d.source.id === idB; // source is the "larger" id
        // Perpendicular to the edge, always pointing the same way for this pair
        const nx = -uy, ny = ux;
        // _pairIdx 0 → one side, 1 → other side; canonFlip corrects for direction
        const sign = ((d._pairIdx % 2 === 0) !== canonFlip) ? 1 : -1;
        const offset = sign * 22;
        const mx = (x1 + x2) / 2 + nx * offset;
        const my = (y1 + y2) / 2 + ny * offset;
        pathD = `M${x1},${y1} Q${mx},${my} ${x2},${y2}`;
      } else {
        pathD = `M${x1},${y1} L${x2},${y2}`;
      }
      d3.select(this).attr('d', pathD);
    });
    nodeGroup.selectAll('.node-g')
      .attr('transform', d => `translate(${d.x},${d.y})`);
    // Fit once the layout has mostly settled (alpha < 0.1)
    if (!skipFit && !fitDone && simulation.alpha() < 0.1) {
      fitDone = true;
      fitView(visibleNodes);
    }
  });
  simulation.on('end', () => { if (!skipFit) fitView(visibleNodes); });

  // Fallback: always fit after 800 ms in case the simulation converges
  // too quickly (e.g. nodes already have positions from a prior render).
  if (!skipFit) setTimeout(() => fitView(visibleNodes), 800);
}

// ── Drag ──────────────────────────────────────────────────────────────────────
function dragStart(event, d) {
  if (!event.active) simulation.alphaTarget(0.3).restart();
  d.fx = d.x; d.fy = d.y;
}
function dragged(event, d) { d.fx = event.x; d.fy = event.y; }
function dragEnd(event, d) {
  if (!event.active) simulation.alphaTarget(0);
  d.fx = null; d.fy = null;
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

function onNodeHover(event, d) {
  // A node may belong to multiple tracks (most belong to one). Show every
  // track as a colored chip so the user can tell which track contributed
  // this node — distinct from the broader yfinance sector below.
  const ids = (d.tracks && d.tracks.length) ? d.tracks : (d.track ? [d.track] : []);
  const trackChips = ids
    .map(id => trackById.get(id))
    .filter(Boolean)
    .map(t => `<span class="tt-track-chip" style="color:${t.color};border-color:${t.color}55;background:${t.color}1a">${t.label}</span>`)
    .join('');
  const headerColor = ids.length ? (trackById.get(ids[0])?.color || '#fff') : '#fff';
  tooltip.innerHTML = `
    <div class="tt-ticker" style="color:${headerColor}">${d.ticker}</div>
    <div class="tt-name">${d.name}</div>
    ${trackChips ? `<div class="tt-tracks">${trackChips}</div>` : ''}
    <div class="tt-meta">${d.sector || '—'} · ${fmtCap(d.marketCap)}</div>
  `;
  tooltip.classList.add('visible');
  positionTooltip(event);
}

function onNodeMove(event) { positionTooltip(event); }

function onNodeOut() { tooltip.classList.remove('visible'); }

function positionTooltip(event) {
  const W = window.innerWidth, H = window.innerHeight;
  let x = event.clientX + 14;
  let y = event.clientY + 14;
  if (x + 180 > W) x = event.clientX - 180;
  if (y + 90  > H) y = event.clientY - 90;
  tooltip.style.left = x + 'px';
  tooltip.style.top  = y + 'px';
}

// ── Detail Panel ──────────────────────────────────────────────────────────────
const panel = document.getElementById('detail-panel');

function onNodeClick(event, d) {
  event.stopPropagation();
  if (selectedNode && selectedNode.id === d.id) {
    closePanel();
  } else {
    selectedNode = d;
    openPanel(d);
  }
}

function openPanel(d) {
  selectedNode = d;
  const t = tracks.find(t => t.id === d.track);
  const color = t ? t.color : '#888888';

  // Find connections (nodes currently on the graph)
  const graphConnections = allEdges
    .filter(e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source;
      const t = typeof e.target === 'object' ? e.target.id : e.target;
      return s === d.id || t === d.id;
    })
    .map(e => {
      const srcId = typeof e.source === 'object' ? e.source.id : e.source;
      const isSource = srcId === d.id;
      const node = isSource ? e.target : e.source;
      const tkr = typeof node === 'object' ? node.ticker : (allNodes.find(n => n.id === node)?.ticker || node);
      let role = e.type;
      if (e.type === 'ownership') role = isSource ? 'Subsidiaries' : 'Parents';
      if (e.type === 'supplier')   role = isSource ? 'Supplier Of' : 'Customer Of';
      if (e.type === 'competitor') role = 'Competitor Of';
      return { ticker: tkr, role };
    });

  const mcap = d.marketCap || 0;
  const capStr = fmtCap(mcap);
  const priceStr = d.price != null ? '$' + Number(d.price).toFixed(2) : '—';

  document.getElementById('panel-inner').innerHTML = `
    <div class="panel-header">
      <div>
        <div class="panel-ticker-badge" style="background:${color}22; color:${color}; border:1px solid ${color}55">${d.ticker}</div>
        <div class="panel-name">${d.name}</div>
        <div class="panel-sector">${d.sector}</div>
        <a class="panel-open-stock" href="stock.html?ticker=${encodeURIComponent(d.ticker)}">Open full stock page →</a>
        <button class="panel-add-btn${nodeIsVisible(d) ? ' on-graph' : ''}" id="panel-add-btn">${nodeIsVisible(d) ? '✕ Remove from graph' : '+ Add to graph'}</button>
      </div>
      <button id="panel-close" onclick="closePanel()">
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 1L11 11M11 1L1 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
      </button>
    </div>
    <div class="panel-body">
      <div class="stat-grid">
        <div class="stat-card">
          <div class="stat-label">Market Cap</div>
          <div class="stat-value" id="panel-mcap">${capStr}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Price</div>
          <div class="stat-value price" id="panel-price">${priceStr}</div>
        </div>
      </div>

      <div id="panel-tracks-wrap"></div>

      <div id="panel-about"></div>

      <div id="panel-connections">
      </div>
    </div>
  `;

  panel.classList.add('open');
  setTimeout(() => fitView(allNodes.filter(nodeIsVisible)), 300);

  const addBtn = document.getElementById('panel-add-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      if (pinnedNodes.has(d.id)) {
        removeItem(nodeItem(d));
        addBtn.classList.remove('on-graph');
        addBtn.textContent = '+ Add to graph';
      } else {
        addItem(nodeItem(d));
        addBtn.classList.add('on-graph');
        addBtn.textContent = '✕ Remove from graph';
      }
    });
  }

  // Investment track rows — same renderRow used by the sidebar so the user
  // gets the ↗, ★, +/-, sector·count meta, and chevron-expand for free.
  const tracksWrap = document.getElementById('panel-tracks-wrap');
  if (tracksWrap) {
    const trackIds = (d.tracks && d.tracks.length) ? d.tracks
                   : (d.track ? [d.track] : []);
    const trackObjs = trackIds.map(id => trackById.get(id)).filter(Boolean);
    if (trackObjs.length) {
      const title = document.createElement('div');
      title.className = 'panel-section-title';
      title.textContent = trackObjs.length === 1 ? 'Investment Track' : 'Investment Tracks';
      tracksWrap.appendChild(title);
      const list = document.createElement('div');
      list.className = 'sidebar-list panel-tracks-list';
      trackObjs.forEach(track => list.appendChild(renderRow(
        { ...trackItem(track), color: track.color },
        { /* default actionMode auto, expandable, star, open arrow */ },
      )));
      tracksWrap.appendChild(list);
    }
  }

  // Delegate +/− button clicks in the connections list
  const pConn = document.getElementById('panel-connections');
  if (pConn) {
    pConn.addEventListener('click', e => {
      const btn = e.target.closest('.conn-add-btn');
      if (!btn) return;
      e.stopPropagation();
      const node = allNodes.find(n => n.id === btn.dataset.id);
      if (!node) return;
      if (pinnedNodes.has(node.id)) {
        removeItem(nodeItem(node));
        btn.classList.remove('on-graph');
        btn.innerHTML = ICON_PLUS;
        btn.title = 'Add to graph';
      } else {
        addItem(nodeItem(node));
        btn.classList.add('on-graph');
        btn.innerHTML = ICON_CLOSE;
        btn.title = 'Remove from graph';
      }
    });
  }

  function updateTabs(combinedEdges) {
    const connContainer = document.getElementById('panel-connections');
    if (!connContainer) return;
    
    const unique = [];
    const seen = new Set();
    combinedEdges.forEach(e => {
      if (!e.ticker) return;
      const key = e.ticker + '|' + e.role;
      if (!seen.has(key)) {
        seen.add(key);
        const cn = allNodes.find(n => n.ticker === e.ticker);
        unique.push({
          ticker: e.ticker,
          role: e.role,
          node: cn,
          mcap: cn ? (cn.marketCap || 0) : 0
        });
      }
    });

    const groups = {
      'Supplier Of': [],
      'Customer Of': [],
      'Competitor Of': [],
      'Parents': [],
      'Subsidiaries': []
    };

    unique.forEach(e => {
      if (groups[e.role]) groups[e.role].push(e);
    });

    Object.values(groups).forEach(list => list.sort((a, b) => b.mcap - a.mcap));

    const oldActiveBtn = connContainer.querySelector('.panel-tab-btn.active');
    let activeTab = oldActiveBtn ? oldActiveBtn.dataset.tab : null;
    
    const availableTabs = Object.keys(groups).filter(k => groups[k].length > 0);
    if (!availableTabs.includes(activeTab)) {
      activeTab = availableTabs[0] || null;
    }

    if (!activeTab) {
      connContainer.innerHTML = '<div class="panel-section-title">Connections (0)</div><div class="connections-list"></div>';
      return;
    }

    let html = `<div class="panel-section-title">Connections (${unique.length})</div>`;
    html += '<div class="panel-tabs">';
    availableTabs.forEach(role => {
      const cls = role === activeTab ? 'panel-tab-btn active' : 'panel-tab-btn';
      html += `<button class="${cls}" data-tab="${role}">${role} (${groups[role].length})</button>`;
    });
    html += '</div>';

    availableTabs.forEach(role => {
      const cls = role === activeTab ? 'panel-tab-content active' : 'panel-tab-content';
      html += `<div class="${cls}" id="tab-content-${role.replace(/\s+/g, '')}"><div class="connections-list">`;
      groups[role].forEach(c => {
         const cn = c.node;
         if (!cn) return;
         const ct = tracks.find(t => t.id === cn.track);
         const onGraph = nodeIsVisible(cn);
         html += `
           <div class="conn-item tab-item" onclick="if(!event.target.closest('.conn-add-btn')) selectNodeById('${cn.id}')">
             <span class="conn-ticker" style="color:${ct ? ct.color : 'var(--text-primary)'}">${cn.ticker}</span>
             <span class="conn-name">${cn.name}</span>
             <button class="conn-add-btn${onGraph ? ' on-graph' : ''}" data-id="${cn.id}" title="${onGraph ? 'Remove from graph' : 'Add to graph'}">${onGraph ? ICON_CLOSE : ICON_PLUS}</button>
           </div>
         `;
      });
      html += `</div></div>`;
    });

    connContainer.innerHTML = html;

    connContainer.querySelectorAll('.panel-tab-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        connContainer.querySelectorAll('.panel-tab-btn, .panel-tab-content').forEach(el => el.classList.remove('active'));
        e.target.classList.add('active');
        const contentId = 'tab-content-' + e.target.dataset.tab.replace(/\s+/g, '');
        const contentEl = connContainer.querySelector('#' + contentId);
        if (contentEl) contentEl.classList.add('active');
      });
    });
  }

  // Initial render for graph connections only
  updateTabs(graphConnections);

  // Fetch description on-demand (not in graph payload to keep it small)
  fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}`)
    .then(r => r.ok ? r.json() : null)
    .then(info => {
      const el = document.getElementById('panel-about');
      if (!el) return;
      if (info && info.description) {
        el.innerHTML = `<div class="panel-section-title">About</div><p class="panel-desc">${info.description}</p>`;
      }
    }).catch(() => {});

  Promise.all([
    fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/neighbors?type=ownership`).then(r => r.ok ? r.json() : { edges: [] }),
    fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/neighbors?type=supplier`).then(r => r.ok ? r.json() : { edges: [] }),
    fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/neighbors?type=competitor`).then(r => r.ok ? r.json() : { edges: [] }),
  ]).then(([subData, supData, compData]) => {
    const extra = [
      ...(subData.edges || []).filter(e => e.source === d.ticker).map(e => ({ role: 'Subsidiaries', ticker: e.target })),
      ...(subData.edges || []).filter(e => e.target === d.ticker).map(e => ({ role: 'Parents',      ticker: e.source })),
      ...(supData.edges || []).filter(e => e.source === d.ticker).map(e => ({ role: 'Supplier Of',  ticker: e.target })),
      ...(supData.edges || []).filter(e => e.target === d.ticker).map(e => ({ role: 'Customer Of',  ticker: e.source })),
      ...(compData.edges || []).filter(e => e.source === d.ticker).map(e => ({ role: 'Competitor Of', ticker: e.target })),
      ...(compData.edges || []).filter(e => e.target === d.ticker).map(e => ({ role: 'Competitor Of', ticker: e.source }))
    ];
    updateTabs([...graphConnections, ...extra]);
  }).catch(() => {});
}

function closePanel() {
  panel.classList.remove('open');
  selectedNode = null;
  setTimeout(() => fitView(allNodes.filter(nodeIsVisible)), 300);
}

function selectNodeById(id) {
  const node = allNodes.find(n => n.id === id);
  if (node) openPanel(node);
}

// Close panel on canvas click
document.getElementById('graph-canvas').addEventListener('click', () => {
  if (selectedNode) closePanel();
});


// ── Kick off ──────────────────────────────────────────────────────────────────
// Render the edge legend immediately — it depends only on the static
// EDGE_COLORS constant, so there's no reason to wait on the API.
// Otherwise the user sees an empty styled bubble until /graph responds.
buildEdgeLegend();
init();
