/**
 * main.js — Nexus Frontend
 *
 * Tries the live backend first (GET /graph). If unreachable or empty,
 * falls back to ./data/mock.json so the demo still renders.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

// ── Edge colors by relationship type ─────────────────────────────────────────
const EDGE_COLORS = {
  competitor:  '#ef4444',  // red
  supplier:    '#eab308',  // yellow
  subsidiary:  '#3b82f6',  // blue
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
let hiddenTracks  = new Set();
let pinnedNodes   = new Set();   // individual node IDs shown regardless of track state
let excludedNodes = new Set();   // individual node IDs explicitly hidden regardless of track state
let searchQuery   = '';
let selectedNode  = null;
let simulation, svg, linkGroup, nodeGroup, zoomBehavior;

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

function getUserId() {
  let uid = localStorage.getItem('nexus_user_id');
  if (!uid) {
    uid = crypto.randomUUID();
    localStorage.setItem('nexus_user_id', uid);
  }
  return uid;
}

const STATE_KEY = `nexus_graph_state_${getUserId()}`;
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
  const data = await loadGraphData();
  tracks   = data.tracks;
  allNodes = data.nodes.map(n => ({ ...n }));   // shallow copy so D3 can mutate
  allEdges = data.edges.map(e => ({ ...e }));

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
  buildSidebar(tracks, allNodes);
  buildGraph();
  buildEdgeLegend();
  updateNodeCount();
  applyVisibility();
  renderPinnedList();

  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', onSearch);
  searchInput.addEventListener('focus', () => { if (searchInput.value.trim()) onSearch({ target: searchInput }); });
  searchInput.addEventListener('blur', () => setTimeout(hideSearchDropdown, 150));
  document.getElementById('track-select-all')?.addEventListener('click', selectAllTracks);
  document.getElementById('track-clear-all')?.addEventListener('click', clearAllTracks);
  document.getElementById('pinned-add-all')?.addEventListener('click', () => {
    allNodes.forEach(n => { pinnedNodes.add(n.id); excludedNodes.delete(n.id); });
    applyVisibility({ skipFit: true });
    renderPinnedList();
  });
  document.getElementById('pinned-clear-all')?.addEventListener('click', () => {
    if (selectedNode) closePanel();
    pinnedNodes.clear();
    applyVisibility({ skipFit: true });
    renderPinnedList();
  });
}

function selectAllTracks() {
  hiddenTracks.clear();
  document.querySelectorAll('#track-list .track-item').forEach(el => {
    el.classList.add('active');
    el.classList.remove('muted');
    const btn = el.querySelector('.track-toggle-btn');
    if (btn) { btn.textContent = '✕'; btn.title = 'Remove from graph'; }
  });
  applyVisibility();
}

function clearAllTracks() {
  hiddenTracks = new Set(tracks.map(t => t.id));
  document.querySelectorAll('#track-list .track-item').forEach(el => {
    el.classList.remove('active');
    el.classList.add('muted');
    const btn = el.querySelector('.track-toggle-btn');
    if (btn) { btn.textContent = '+'; btn.title = 'Add to graph'; }
  });
  applyVisibility();
}

// ── Inject track colours as CSS vars (in case they differ from defaults) ──────
function buildTrackCSS(tracks) {
  const root = document.documentElement;
  tracks.forEach(t => {
    root.style.setProperty(`--track-${t.id}`, t.color);
  });
}

// ── Left Sidebar ──────────────────────────────────────────────────────────────
function buildSidebar(tracks, nodes) {
  const list = document.getElementById('track-list');
  list.innerHTML = '';

  const sorted = [...tracks].sort((a, b) => {
    const aActive = !hiddenTracks.has(a.id);
    const bActive = !hiddenTracks.has(b.id);
    if (aActive !== bActive) return aActive ? -1 : 1;
    return a.label.localeCompare(b.label);
  });

  sorted.forEach(track => {
    const trackNodes = nodes.filter(n => n.track === track.id);
    const isHidden = hiddenTracks.has(track.id);

    const wrapper = document.createElement('div');
    wrapper.className = 'pinned-item';

    const item = document.createElement('a');
    item.className = 'track-item ' + (isHidden ? 'muted' : 'active');
    item.dataset.track = track.id;
    item.href = `track.html?slug=${encodeURIComponent(track.id)}`;
    item.innerHTML = `
      <span class="track-dot" style="background:${track.color}; box-shadow:0 0 6px ${track.color}66"></span>
      <span class="track-name">${track.label}</span>
      <button class="pinned-chevron-btn track-chevron-btn" title="Show companies">▾</button>
      <button class="track-toggle-btn" title="${isHidden ? 'Add to graph' : 'Remove from graph'}">${isHidden ? '+' : '✕'}</button>
    `;

    const dropdown = document.createElement('div');
    dropdown.className = 'pinned-dropdown';
    dropdown.style.display = 'none';

    const chevronBtn = item.querySelector('.track-chevron-btn');
    const toggleBtn  = item.querySelector('.track-toggle-btn');

    const buildTrackDropdown = () => {
      dropdown.innerHTML = '';
      if (!trackNodes.length) {
        dropdown.innerHTML = '<div class="pinned-dropdown-empty">No companies</div>';
        return;
      }

      const trackHeader = document.createElement('div');
      trackHeader.className = 'pinned-rel-header';
      const trackLabel = document.createElement('span');
      trackLabel.className = 'pinned-rel-label';
      trackLabel.style.color = track.color;
      trackLabel.textContent = 'Companies';
      const trackAllBtn = document.createElement('button');
      trackAllBtn.className = 'pinned-rel-all-btn';
      trackAllBtn.textContent = 'All';
      const trackClearBtn = document.createElement('button');
      trackClearBtn.className = 'pinned-rel-all-btn pinned-rel-clear-btn';
      trackClearBtn.textContent = 'Clear';
      const trackBtnGroup = document.createElement('div');
      trackBtnGroup.className = 'pinned-rel-btn-group';
      trackBtnGroup.appendChild(trackAllBtn);
      trackBtnGroup.appendChild(trackClearBtn);
      trackHeader.appendChild(trackLabel);
      trackHeader.appendChild(trackBtnGroup);
      dropdown.appendChild(trackHeader);

      const trackRowNodes = [];
      trackNodes.slice().sort((a, b) => a.ticker.localeCompare(b.ticker)).forEach(n => {
        const isPinned = pinnedNodes.has(n.id);
        const row = document.createElement('div');
        row.className = 'pinned-rel-item';
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.gap = '6px';
        row.innerHTML = `
          <span class="pinned-rel-ticker" style="color:${track.color}">${n.ticker}</span>
          <span class="pinned-rel-name">${n.name}</span>
          <button class="track-toggle-btn track-company-toggle" style="margin-left:auto;flex-shrink:0" title="${isPinned ? 'Remove from graph' : 'Add to graph'}">${isPinned ? '✕' : '+'}</button>
        `;
        const compToggle = row.querySelector('.track-company-toggle');
        if (isPinned) {
          compToggle.style.color = '#ef4444';
          compToggle.style.borderColor = '#ef4444';
        } else {
          compToggle.style.color = '#10b981';
          compToggle.style.borderColor = '#10b981';
        }
        compToggle.addEventListener('click', e => {
          e.stopPropagation();
          if (pinnedNodes.has(n.id)) {
            pinnedNodes.delete(n.id);
            excludedNodes.add(n.id);
          } else {
            pinnedNodes.add(n.id);
            excludedNodes.delete(n.id);
          }
          applyVisibility({ skipFit: true });
          renderPinnedList();
          buildTrackDropdown();
        });
        row.addEventListener('click', e => {
          if (e.target.closest('.track-company-toggle')) return;
          openPanel(n);
        });
        trackRowNodes.push({ node: n, row });
        dropdown.appendChild(row);
      });

      trackAllBtn.addEventListener('click', () => {
        let added = false;
        trackRowNodes.forEach(({ node }) => {
          if (!pinnedNodes.has(node.id)) {
            pinnedNodes.add(node.id);
            excludedNodes.delete(node.id);
            added = true;
          }
        });
        if (added) { applyVisibility({ skipFit: true }); renderPinnedList(); buildTrackDropdown(); }
      });

      trackClearBtn.addEventListener('click', () => {
        let removed = false;
        trackRowNodes.forEach(({ node }) => {
          if (pinnedNodes.has(node.id)) {
            pinnedNodes.delete(node.id);
            excludedNodes.add(node.id);
            removed = true;
          }
        });
        if (removed) { applyVisibility({ skipFit: true }); renderPinnedList(); buildTrackDropdown(); }
      });
    };

    item.addEventListener('click', e => {
      if (e.target.closest('.track-toggle-btn') && !e.target.closest('.track-chevron-btn')) {
        e.preventDefault();
        e.stopPropagation();
        toggleTrack(track.id);
        const nowHidden = hiddenTracks.has(track.id);
        toggleBtn.textContent = nowHidden ? '+' : '✕';
        toggleBtn.title = nowHidden ? 'Add to graph' : 'Remove from graph';
        item.className = 'track-item ' + (nowHidden ? 'muted' : 'active');
        return;
      }
      if (e.target.closest('.track-chevron-btn')) {
        e.preventDefault();
        e.stopPropagation();
        if (dropdown.style.display !== 'none') {
          dropdown.style.display = 'none';
          chevronBtn.classList.remove('open');
        } else {
          dropdown.style.display = 'block';
          chevronBtn.classList.add('open');
          buildTrackDropdown();
        }
        return;
      }
    });

    wrapper.appendChild(item);
    wrapper.appendChild(dropdown);
    list.appendChild(wrapper);
  });
}

// Re-sort existing pinned-item rows in-place without rebuilding them.
// Pinned nodes go first, then alphabetical by ticker within each group.
// Also updates each row's button/class to reflect current pin state.
function resortPinnedList() {
  const list = document.getElementById('pinned-list');
  if (!list) return;
  const wrappers = [...list.querySelectorAll(':scope > .pinned-item')];
  wrappers.forEach(w => {
    const isPinned = pinnedNodes.has(w.dataset.id);
    const row = w.querySelector('.track-item');
    const btn = w.querySelector('.pinned-toggle');
    if (row) row.className = 'track-item ' + (isPinned ? 'active' : 'muted');
    if (btn) { btn.textContent = isPinned ? '✕' : '+'; btn.title = isPinned ? 'Remove from graph' : 'Add to graph'; }
  });
  const pinned   = wrappers.filter(w =>  pinnedNodes.has(w.dataset.id));
  const unpinned = wrappers.filter(w => !pinnedNodes.has(w.dataset.id));
  pinned.sort((a, b)   => a.dataset.ticker.localeCompare(b.dataset.ticker));
  unpinned.sort((a, b) => a.dataset.ticker.localeCompare(b.dataset.ticker));
  [...pinned, ...unpinned].forEach(w => list.appendChild(w));
}

function renderPinnedList(keepOpenTicker) {
  const list = document.getElementById('pinned-list');
  if (!list) return;

  list.innerHTML = '';

  // Show all nodes, pinned ones first, then alphabetical by ticker
  const sorted = [...allNodes].sort((a, b) => {
    const ap = pinnedNodes.has(a.id), bp = pinnedNodes.has(b.id);
    if (ap !== bp) return ap ? -1 : 1;
    return a.ticker.localeCompare(b.ticker);
  });

  sorted.forEach(n => {
    const isPinned = pinnedNodes.has(n.id);
    const wrapper = document.createElement('div');
    wrapper.className = 'pinned-item';
    wrapper.dataset.id = n.id;
    wrapper.dataset.ticker = n.ticker;

    const row = document.createElement('div');
    row.className = 'track-item ' + (isPinned ? 'active' : 'muted');
    row.innerHTML = `
      <span class="pinned-ticker">${n.ticker}</span>
      <span class="pinned-name">${n.name}</span>
      <button class="pinned-chevron-btn" title="Show relationships">▾</button>
      <button class="track-toggle-btn pinned-toggle" title="${isPinned ? 'Remove from graph' : 'Add to graph'}">${isPinned ? '✕' : '+'}</button>
    `;

    const dropdown = document.createElement('div');
    dropdown.className = 'pinned-dropdown';
    dropdown.style.display = 'none';
    dropdown.innerHTML = `<div class="pinned-dropdown-loading">Loading…</div>`;

    let loaded = false;
    const toggleBtn = row.querySelector('.pinned-toggle');
    const chevronBtn = row.querySelector('.pinned-chevron-btn');

    row.addEventListener('click', e => {
      if (e.target.closest('.pinned-toggle') || e.target.closest('.pinned-chevron-btn')) return;
      selectedNode = n;
      openPanel(n);
    });

    toggleBtn.addEventListener('click', e => {
      e.stopPropagation();
      const wasPinned = pinnedNodes.has(n.id);
      if (wasPinned) {
        pinnedNodes.delete(n.id);
        excludedNodes.add(n.id);
        if (selectedNode && selectedNode.id === n.id) {
          const existing = document.getElementById('panel-add-btn');
          if (!existing) {
            const btn = document.createElement('button');
            btn.className = 'panel-add-btn';
            btn.id = 'panel-add-btn';
            btn.textContent = '+ Add to graph';
            btn.addEventListener('click', () => {
              selectSearchNode(selectedNode);
              renderPinnedList();
              btn.remove();
            });
            const stockLink = document.querySelector('.panel-open-stock');
            if (stockLink) stockLink.insertAdjacentElement('afterend', btn);
          }
        }
      } else {
        pinnedNodes.add(n.id);
        excludedNodes.delete(n.id);
      }

      applyVisibility({ skipFit: true });
      resortPinnedList();
    });

    const openDropdown = () => {
      dropdown.style.display = 'block';
      chevronBtn.classList.add('open');
      if (!loaded) {
        loaded = true;
        loadPinnedRelationships(n.ticker, dropdown);
      }
    };

    chevronBtn.addEventListener('click', e => {
      e.stopPropagation();
      if (dropdown.style.display !== 'none') {
        dropdown.style.display = 'none';
        chevronBtn.classList.remove('open');
      } else {
        openDropdown();
      }
    });

    if (keepOpenTicker && n.ticker === keepOpenTicker) {
      openDropdown();
    }

    wrapper.appendChild(row);
    wrapper.appendChild(dropdown);
    list.appendChild(wrapper);
  });
}

function loadPinnedRelationships(ticker, container) {
  const id = ticker.toLowerCase();

  // Competitors come from allEdges (generated from shared tracks, not stored in DB)
  const competitors = allEdges
    .filter(e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source;
      const t = typeof e.target === 'object' ? e.target.id : e.target;
      return e.type === 'competitor' && (s === id || t === id);
    })
    .map(e => {
      const s = typeof e.source === 'object' ? e.source.ticker : e.source;
      const t = typeof e.target === 'object' ? e.target.ticker : e.target;
      return s.toLowerCase() === id ? t : s;
    });

  Promise.all([
    fetch(`${API_BASE}/companies/${encodeURIComponent(ticker)}/neighbors?type=supplier`).then(r => r.ok ? r.json() : { edges: [] }),
    fetch(`${API_BASE}/companies/${encodeURIComponent(ticker)}/neighbors?type=subsidiary`).then(r => r.ok ? r.json() : { edges: [] }),
  ]).then(([supData, subData]) => {
    const supplies_to  = (supData.edges  || []).filter(e => e.source === ticker).map(e => e.target);
    const supplied_by  = (supData.edges  || []).filter(e => e.target === ticker).map(e => e.source);
    const subsidiaries = (subData.edges  || []).filter(e => e.source === ticker).map(e => e.target);
    const parents      = (subData.edges  || []).filter(e => e.target === ticker).map(e => e.source);

    const sections = [
      { label: 'Competitors',  color: EDGE_COLORS.competitor, tickers: competitors },
      { label: 'Customers',    color: EDGE_COLORS.supplier,   tickers: supplies_to },
      { label: 'Suppliers',    color: EDGE_COLORS.supplier,   tickers: supplied_by },
      { label: 'Subsidiaries', color: EDGE_COLORS.subsidiary, tickers: subsidiaries },
      { label: 'Parent',       color: EDGE_COLORS.subsidiary, tickers: parents },
    ].filter(s => s.tickers.length > 0);

    if (!sections.length) {
      container.innerHTML = `<div class="pinned-dropdown-empty">No relationships found</div>`;
      return;
    }

    container.innerHTML = '';
    sections.forEach(s => {
      const section = document.createElement('div');
      section.className = 'pinned-rel-section';

      const header = document.createElement('div');
      header.className = 'pinned-rel-header';
      const labelEl = document.createElement('span');
      labelEl.className = 'pinned-rel-label';
      labelEl.style.color = s.color;
      labelEl.textContent = s.label;
      const allBtn = document.createElement('button');
      allBtn.className = 'pinned-rel-all-btn';
      allBtn.textContent = 'All';
      const clearBtn = document.createElement('button');
      clearBtn.className = 'pinned-rel-all-btn pinned-rel-clear-btn';
      clearBtn.textContent = 'Clear';
      const btnGroup = document.createElement('div');
      btnGroup.className = 'pinned-rel-btn-group';
      btnGroup.appendChild(allBtn);
      btnGroup.appendChild(clearBtn);
      header.appendChild(labelEl);
      header.appendChild(btnGroup);
      section.appendChild(header);

      const sectionNodes = [];
      s.tickers.forEach(tk => {
        const node = allNodes.find(n => n.ticker === tk || n.ticker === tk.toUpperCase() || n.id === tk.toLowerCase());
        const displayTicker = node ? node.ticker : tk.toUpperCase();
        const displayName = node ? node.name : '';
        const item = document.createElement('div');
        item.className = 'pinned-rel-item';
        const onGraph = node && pinnedNodes.has(node.id);
        item.innerHTML = `<span class="pinned-rel-ticker">${displayTicker}</span>${displayName ? `<span class="pinned-rel-name">${displayName}</span>` : ''}${node ? `<button class="conn-add-btn${onGraph ? ' on-graph' : ''}" style="margin-left:auto;flex-shrink:0" title="${onGraph ? 'Remove from graph' : 'Add to graph'}">${onGraph ? '✕' : '+'}</button>` : ''}`;
        if (node) {
          sectionNodes.push({ node, item });
          const btn = item.querySelector('.conn-add-btn');
          btn.addEventListener('click', e => {
            e.stopPropagation();
            if (pinnedNodes.has(node.id)) {
              pinnedNodes.delete(node.id);
              excludedNodes.add(node.id);
              btn.classList.remove('on-graph');
              btn.textContent = '+';
              btn.title = 'Add to graph';
            } else {
              pinnedNodes.add(node.id);
              excludedNodes.delete(node.id);
              btn.classList.add('on-graph');
              btn.textContent = '✕';
              btn.title = 'Remove from graph';
            }
            applyVisibility({ skipFit: true });
            resortPinnedList();
          });
          item.addEventListener('click', e => {
            if (e.target.closest('.conn-add-btn')) return;
            openPanel(node);
          });
        }
        section.appendChild(item);
      });

      allBtn.addEventListener('click', () => {
        let added = false;
        sectionNodes.forEach(({ node, item }) => {
          if (!pinnedNodes.has(node.id)) {
            pinnedNodes.add(node.id);
            excludedNodes.delete(node.id);
            const btn = item.querySelector('.conn-add-btn');
            if (btn) { btn.classList.add('on-graph'); btn.textContent = '✕'; btn.title = 'Remove from graph'; }
            added = true;
          }
        });
        if (added) {
          applyVisibility({ skipFit: true });
          resortPinnedList();
        }
      });

      clearBtn.addEventListener('click', () => {
        let removed = false;
        sectionNodes.forEach(({ node, item }) => {
          if (pinnedNodes.has(node.id)) {
            pinnedNodes.delete(node.id);
            excludedNodes.add(node.id);
            const btn = item.querySelector('.conn-add-btn');
            if (btn) { btn.classList.remove('on-graph'); btn.textContent = '+'; btn.title = 'Add to graph'; }
            removed = true;
          }
        });
        if (removed) {
          applyVisibility({ skipFit: true });
          resortPinnedList();
        }
      });

      container.appendChild(section);
    });
  }).catch(() => {
    container.innerHTML = `<div class="pinned-dropdown-empty">Failed to load</div>`;
  });
}

function buildEdgeLegend() {
  const container = document.getElementById('edge-legend');
  container.innerHTML = '';
  Object.entries(EDGE_COLORS).forEach(([type, color]) => {
    const item = document.createElement('div');
    item.className = 'edge-legend-item';
    const ARROW_LABELS = {
      subsidiary: ['Parent', 'Subsidiary'],
      supplier:   ['Supplier', 'Customer'],
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
  if (hiddenTracks.has(trackId)) {
    hiddenTracks.delete(trackId);
  } else {
    hiddenTracks.add(trackId);
  }
  buildSidebar(tracks, allNodes);
  applyVisibility();
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
  // Show the track if it's hidden
  if (hiddenTracks.has(trackId)) {
    hiddenTracks.delete(trackId);
    const item = document.querySelector(`.track-item[data-track="${trackId}"]`);
    if (item) { item.classList.add('active'); item.classList.remove('muted'); }
    applyVisibility();
  }
  document.getElementById('search-input').value = '';
  searchQuery = '';
  hideSearchDropdown();
}

function selectSearchNode(n) {
  pinnedNodes.add(n.id);
  excludedNodes.delete(n.id);
  applyVisibility({ skipFit: true });
  renderPinnedList();

  // Fit all visible nodes once the new node has a position
  setTimeout(() => {
    fitView(allNodes.filter(nodeIsVisible));
  }, 120);

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
}

function updateNodeCount() {}

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
  const t = tracks.find(t => t.id === pickId);
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
    updateNodeCount();
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
    .attr('marker-end', d => (d.type === 'subsidiary' || d.type === 'supplier') ? `url(#arrow-${d.type})` : null);

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

  nodeEl.append('circle')
    .attr('class', 'node-glow')
    .attr('r', d => nodeRadius(d) + 4)
    .attr('fill', 'none')
    .attr('stroke', d => trackColor(d))
    .attr('stroke-width', 1)
    .attr('opacity', 0.25);

  nodeEl.append('circle')
    .attr('class', 'node-body')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => trackColor(d) + '44')
    .attr('stroke', d => trackColor(d))
    .attr('stroke-width', 1.5);

  nodeEl.append('text')
    .attr('class', 'node-label')
    .text(d => d.ticker)
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .attr('font-family', "'Space Mono', monospace")
    .attr('font-size', d => Math.max(8.5, Math.min(10, nodeRadius(d) * 0.6)))
    .attr('fill', d => trackColor(d))
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

  updateNodeCount();
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
  const t = tracks.find(t => t.id === d.track);
  tooltip.innerHTML = `
    <div class="tt-ticker" style="color:${t ? t.color : '#fff'}">${d.ticker}</div>
    <div class="tt-name">${d.name}</div>
    <div class="tt-meta">${d.sector} · ${fmtCap(d.marketCap)}</div>
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
      if (e.type === 'subsidiary') role = isSource ? 'Parent Of' : 'Subsidiary Of';
      if (e.type === 'supplier')   role = isSource ? 'Supplier Of' : 'Customer Of';
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

      ${t ? `
        <div class="panel-section-title">Investment Track</div>
        <a class="track-badge track-badge--link" href="track.html?slug=${encodeURIComponent(t.id)}" style="--badge-color:${color}">
          ${t.label}
        </a>
      ` : ''}

      ${d.description ? `
        <div class="panel-section-title">About</div>
        <p class="panel-desc">${d.description}</p>
      ` : ''}

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
        pinnedNodes.delete(d.id);
        excludedNodes.add(d.id);
        applyVisibility({ skipFit: true });
        renderPinnedList();
        addBtn.classList.remove('on-graph');
        addBtn.textContent = '+ Add to graph';
      } else {
        excludedNodes.delete(d.id);
        selectSearchNode(d);
        renderPinnedList();
        addBtn.classList.add('on-graph');
        addBtn.textContent = '✕ Remove from graph';
      }
    });
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
        pinnedNodes.delete(node.id);
        excludedNodes.add(node.id);
        applyVisibility({ skipFit: true });
        renderPinnedList();
        btn.classList.remove('on-graph');
        btn.textContent = '+';
        btn.title = 'Add to graph';
      } else {
        excludedNodes.delete(node.id);
        selectSearchNode(node);
        renderPinnedList();
        btn.classList.add('on-graph');
        btn.textContent = '✕';
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
      'Subsidiary Of': [],
      'Parent Of': []
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
             <button class="conn-add-btn${onGraph ? ' on-graph' : ''}" data-id="${cn.id}" title="${onGraph ? 'Remove from graph' : 'Add to graph'}">${onGraph ? '✕' : '+'}</button>
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

  Promise.all([
    fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/neighbors?type=subsidiary`).then(r => r.ok ? r.json() : { edges: [] }),
    fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/neighbors?type=supplier`).then(r => r.ok ? r.json() : { edges: [] }),
  ]).then(([subData, supData]) => {
    const extra = [
      ...(subData.edges || []).filter(e => e.source === d.ticker).map(e => ({ role: 'Parent Of',    ticker: e.target })),
      ...(subData.edges || []).filter(e => e.target === d.ticker).map(e => ({ role: 'Subsidiary Of', ticker: e.source })),
      ...(supData.edges || []).filter(e => e.source === d.ticker).map(e => ({ role: 'Supplier Of',  ticker: e.target })),
      ...(supData.edges || []).filter(e => e.target === d.ticker).map(e => ({ role: 'Customer Of',  ticker: e.source })),
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
init();
