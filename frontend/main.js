/**
 * main.js — Nexus Frontend
 *
 * Tries the live backend first (GET /graph). If unreachable or empty,
 * falls back to ./data/mock.json so the demo still renders.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001';

// ── Edge colors by relationship type ─────────────────────────────────────────
const EDGE_COLORS = {
  competitor:  '#ef4444',
  supplier:    '#f59e0b',
  subsidiary:  '#10b981',
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
let hiddenTracks = new Set();
let pinnedNodes  = new Set();   // individual node IDs shown regardless of track state
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

async function init() {
  const data = await loadGraphData();
  tracks   = data.tracks;
  allNodes = data.nodes.map(n => ({ ...n }));   // shallow copy so D3 can mutate
  allEdges = data.edges.map(e => ({ ...e }));

  // Default state: nothing selected — user picks tracks from the sidebar.
  hiddenTracks = new Set(tracks.map(t => t.id));

  const badge = document.getElementById('source-badge');
  if (badge) badge.textContent = data._source === 'api' ? 'live' : 'demo';

  buildTrackCSS(tracks);
  buildSidebar(tracks, allNodes);
  buildGraph();
  buildEdgeLegend();
  updateNodeCount();
  applyVisibility();

  const searchInput = document.getElementById('search-input');
  searchInput.addEventListener('input', onSearch);
  searchInput.addEventListener('focus', () => { if (searchInput.value.trim()) onSearch({ target: searchInput }); });
  searchInput.addEventListener('blur', () => setTimeout(hideSearchDropdown, 150));
  document.getElementById('track-select-all')?.addEventListener('click', selectAllTracks);
  document.getElementById('track-clear-all')?.addEventListener('click', clearAllTracks);
}

function selectAllTracks() {
  hiddenTracks.clear();
  document.querySelectorAll('.track-item').forEach(el => {
    el.classList.add('active');
    el.classList.remove('muted');
  });
  applyVisibility();
}

function clearAllTracks() {
  // Close panel first (before pinnedNodes is cleared so closePanel's own guard skips the extra applyVisibility)
  panel.classList.remove('open');
  selectedNode = null;
  pinnedNodes.clear();
  hiddenTracks = new Set(tracks.map(t => t.id));
  document.querySelectorAll('.track-item').forEach(el => {
    el.classList.remove('active');
    el.classList.add('muted');
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

  tracks.forEach(track => {
    const count = nodes.filter(n => n.track === track.id).length;
    const item  = document.createElement('div');
    const isHidden = hiddenTracks.has(track.id);
    item.className = 'track-item ' + (isHidden ? 'muted' : 'active');
    item.dataset.track = track.id;
    item.innerHTML = `
      <span class="track-dot" style="background:${track.color}; box-shadow:0 0 6px ${track.color}66"></span>
      <span class="track-name">${track.label}</span>
      <span class="track-count">${count}</span>
      <a class="track-open" href="track.html?slug=${encodeURIComponent(track.id)}" title="Open track page">→</a>
    `;
    item.addEventListener('click', (e) => {
      if (e.target.classList.contains('track-open')) return;
      toggleTrack(track.id, item);
    });
    list.appendChild(item);
  });
}

function renderPinnedList() {
  const section = document.getElementById('pinned-section');
  const list    = document.getElementById('pinned-list');
  if (!section || !list) return;

  list.innerHTML = '';
  if (pinnedNodes.size === 0) { section.style.display = 'none'; return; }
  section.style.display = '';

  pinnedNodes.forEach(id => {
    const n = allNodes.find(n => n.id === id);
    if (!n) return;
    const t = tracks.find(t => t.id === n.track);
    const color = t ? t.color : '#888';
    const item = document.createElement('div');
    item.className = 'track-item active';
    item.title = 'Click to remove from graph';
    item.innerHTML = `
      <span class="track-dot" style="background:${color}; box-shadow:0 0 6px ${color}66"></span>
      <span class="track-name">${n.ticker} <span class="track-count">${n.name}</span></span>
    `;
    item.addEventListener('click', () => {
      pinnedNodes.delete(id);
      if (selectedNode && selectedNode.id === id) closePanel();
      applyVisibility({ skipFit: true });
      renderPinnedList();
    });
    list.appendChild(item);
  });
}

function buildEdgeLegend() {
  const container = document.getElementById('edge-legend');
  container.innerHTML = '';
  Object.entries(EDGE_COLORS).forEach(([type, color]) => {
    const item = document.createElement('div');
    item.className = 'edge-legend-item';
    item.innerHTML = `
      <span class="edge-swatch" style="background:${color}"></span>
      <span class="edge-legend-label">${type.charAt(0).toUpperCase() + type.slice(1)}</span>
    `;
    container.appendChild(item);
  });
}

function toggleTrack(trackId, itemEl) {
  if (hiddenTracks.has(trackId)) {
    hiddenTracks.delete(trackId);
    itemEl.classList.remove('muted');
    itemEl.classList.add('active');
  } else {
    hiddenTracks.add(trackId);
    itemEl.classList.remove('active');
    itemEl.classList.add('muted');
  }
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
  renderGraph(opts);
}

function updateNodeCount() {
  const visible = allNodes.filter(nodeIsVisible).length;
  const countEl = document.getElementById('node-count');
  if (countEl) countEl.innerHTML = `<span>${visible}</span> / ${allNodes.length} companies`;
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
  const t = tracks.find(t => t.id === pickId);
  return t ? t.color : '#666';
}

function nodeIsVisible(d) {
  if (pinnedNodes.has(d.id)) return true;
  if (Array.isArray(d.tracks)) {
    return d.tracks.length > 0 && d.tracks.some(id => !hiddenTracks.has(id));
  }
  if (!d.track || d.track === 'uncategorized') return false;
  return !hiddenTracks.has(d.track);
}

let zoomLayer;

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
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', color.replace(/rgba?\([^,]+,[^,]+,[^,]+,?\s*[\d.]*\)/, color));
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
 */
function fitView(nodes) {
  if (!nodes || nodes.length === 0) return;
  const container = document.getElementById('graph-canvas');
  const W = container.clientWidth;
  const H = container.clientHeight;

  const xs = nodes.map(n => n.x).filter(v => isFinite(v));
  const ys = nodes.map(n => n.y).filter(v => isFinite(v));
  if (!xs.length) return;

  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 40;
  const bW = (maxX - minX) || 1;
  const bH = (maxY - minY) || 1;

  const scale = Math.min(
    (W - pad * 2) / bW,
    (H - pad * 2) / bH,
    1.4   // don't zoom in past 1.4×
  );
  const tx = W / 2 - scale * (minX + maxX) / 2;
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

  simulation = d3.forceSimulation(visibleNodes)
    .force('link', d3.forceLink(visibleEdges).id(d => d.id).distance(65).strength(0.5))
    .force('charge', d3.forceManyBody().strength(-320))
    // forceX/Y apply per-node gravity so isolated clusters don't drift away.
    // forceCenter only corrects the centroid — it can't stop components from flying apart.
    .force('x', d3.forceX(W / 2).strength(0.05))
    .force('y', d3.forceY(H / 2).strength(0.05))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 20))
    .alphaDecay(0.028);

  linkGroup.selectAll('line')
    .data(visibleEdges)
    .enter().append('line')
    .attr('stroke', d => EDGE_COLORS[d.type] || '#888')
    .attr('stroke-width', 1.5)
    .attr('stroke-opacity', 1);

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
    linkGroup.selectAll('line').each(function(d) {
      const dx = d.target.x - d.source.x;
      const dy = d.target.y - d.source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / dist, uy = dy / dist;
      const sr = d.source._baseR || 16;
      const tr = d.target._baseR || 16;
      d3.select(this)
        .attr('x1', d.source.x + ux * sr)
        .attr('y1', d.source.y + uy * sr)
        .attr('x2', d.target.x - ux * tr)
        .attr('y2', d.target.y - uy * tr);
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
  const color = t ? t.color : '#666';

  // Find connections
  const connections = allEdges
    .filter(e => e.source.id === d.id || e.target.id === d.id)
    .map(e => ({
      node: e.source.id === d.id ? e.target : e.source,
      type: e.type,
    }));

  const mcap = d.marketCap || 0;
  const capStr = fmtCap(mcap);
  const priceStr = d.price != null ? '$' + Number(d.price).toFixed(2) : '—';

  // Fetch live data and update price/market cap in the panel
  fetch(`${API_BASE}/companies/${encodeURIComponent(d.ticker)}/live`)
    .then(r => r.ok ? r.json() : null)
    .then(live => {
      if (!live || !panel.classList.contains('open')) return;
      const mcEl = document.getElementById('panel-mcap');
      const prEl = document.getElementById('panel-price');
      if (mcEl && live.marketCap != null) mcEl.textContent = fmtCap(live.marketCap / 1e9);
      if (prEl && live.price != null) prEl.textContent = '$' + Number(live.price).toFixed(2);
    })
    .catch(() => {});

  document.getElementById('panel-inner').innerHTML = `
    <div class="panel-header">
      <div>
        <div class="panel-ticker-badge" style="background:${color}22; color:${color}; border:1px solid ${color}55">${d.ticker}</div>
        <div class="panel-name">${d.name}</div>
        <div class="panel-sector">${d.sector}</div>
        <a class="panel-open-stock" href="stock.html?ticker=${encodeURIComponent(d.ticker)}">Open full stock page →</a>
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

      <div class="panel-section-title">Investment Track</div>
      <a class="track-badge track-badge--link" href="track.html?slug=${encodeURIComponent(t ? t.id : d.track)}" style="--badge-color:${color}">
        ${t ? t.label : d.track}
      </a>

      <div class="panel-section-title">About</div>
      <p class="panel-desc">${d.description}</p>

      ${connections.length ? `
        <div class="panel-section-title">Connections (${connections.length})</div>
        <div class="connections-list">
          ${connections.map(c => {
            const cn = typeof c.node === 'object' ? c.node : allNodes.find(n => n.id === c.node);
            if (!cn) return '';
            const ct = tracks.find(t => t.id === cn.track);
            return `
              <div class="conn-item" onclick="selectNodeById('${cn.id}')">
                <span class="conn-ticker" style="color:${ct ? ct.color : '#fff'}">${cn.ticker}</span>
                <span>${cn.name.length > 16 ? cn.name.slice(0, 16) + '…' : cn.name}</span>
                <span class="conn-type">${c.type}</span>
              </div>
            `;
          }).join('')}
        </div>
      ` : ''}
    </div>
  `;

  panel.classList.add('open');
}

function closePanel() {
  panel.classList.remove('open');
  selectedNode = null;
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
