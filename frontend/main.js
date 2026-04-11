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
  partnership: 'rgba(255,255,255,0.18)',
  competitor:  'rgba(239,68,68,0.35)',
  supplier:    'rgba(245,158,11,0.35)',
  investor:    'rgba(16,185,129,0.35)',
};

// ── State ─────────────────────────────────────────────────────────────────────
let allNodes = [], allEdges = [], tracks = [];
let hiddenTracks = new Set();
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

  document.getElementById('search-input').addEventListener('input', onSearch);
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

function buildEdgeLegend() {
  const container = document.getElementById('edge-legend');
  container.innerHTML = '';
  Object.entries(EDGE_COLORS).forEach(([type, color]) => {
    const item = document.createElement('div');
    item.className = 'edge-legend-item';
    item.innerHTML = `
      <span class="edge-swatch" style="background:${color.replace('rgba', 'rgb').replace(/,\s*[\d.]+\)/, ')')}"></span>
      <span>${type.charAt(0).toUpperCase() + type.slice(1)}</span>
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

function onSearch(e) {
  searchQuery = e.target.value.trim().toLowerCase();
  applyVisibility();
}

function applyVisibility() {
  if (!nodeGroup) return;

  // Disable hover/click on hidden node groups so invisible Amazons don't
  // capture the cursor.
  nodeGroup.selectAll('.node-g').each(function(d) {
    d3.select(this).style('pointer-events', nodeIsVisible(d) ? 'auto' : 'none');
  });

  nodeGroup.selectAll('circle').each(function(d) {
    const visible = nodeIsVisible(d);
    const matched = searchQuery.length > 0
      ? d.name.toLowerCase().includes(searchQuery) || d.ticker.toLowerCase().includes(searchQuery)
      : true;

    const el = d3.select(this);
    el.transition().duration(200)
      .attr('opacity', !visible ? 0 : (searchQuery && !matched ? 0.1 : 1))
      .attr('r', searchQuery && matched && visible ? d._baseR * 1.4 : d._baseR)
      .attr('fill', trackColor(d) + '33')
      .attr('stroke', trackColor(d))
      .style('pointer-events', visible ? 'auto' : 'none');
  });

  nodeGroup.selectAll('text').each(function(d) {
    const visible = nodeIsVisible(d);
    const matched = searchQuery.length > 0
      ? d.name.toLowerCase().includes(searchQuery) || d.ticker.toLowerCase().includes(searchQuery)
      : true;
    d3.select(this)
      .transition().duration(200)
      .attr('opacity', !visible ? 0 : (searchQuery && !matched ? 0 : 1))
      .attr('fill', trackColor(d));
  });

  linkGroup.selectAll('line').each(function(d) {
    const srcNode = typeof d.source === 'object' ? d.source : allNodes.find(n => n.id === d.source);
    const tgtNode = typeof d.target === 'object' ? d.target : allNodes.find(n => n.id === d.target);
    const visible = srcNode && tgtNode && nodeIsVisible(srcNode) && nodeIsVisible(tgtNode);
    d3.select(this)
      .transition().duration(200)
      .attr('opacity', visible ? 0.6 : 0);
  });

  updateNodeCount();
}

function updateNodeCount() {
  const visible = allNodes.filter(nodeIsVisible).length;
  const countEl = document.getElementById('node-count');
  if (countEl) countEl.innerHTML = `<span>${visible}</span> / ${allNodes.length} companies`;
}

// ── D3 Graph ──────────────────────────────────────────────────────────────────
function nodeRadius(d) {
  // scale by log(marketCap), clamped between 8–28px
  const r = Math.max(8, Math.min(28, 7 + Math.log(d.marketCap) * 2.2));
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
  // Strict multi-track shape from the new /graph endpoint
  if (Array.isArray(d.tracks)) {
    return d.tracks.length > 0 && d.tracks.some(id => !hiddenTracks.has(id));
  }
  // Legacy single-track fallback (backend not yet restarted): never show
  // companies that have no real track assignment.
  if (!d.track || d.track === 'uncategorized') return false;
  return !hiddenTracks.has(d.track);
}

function buildGraph() {
  const container = document.getElementById('graph-canvas');
  const W = container.clientWidth;
  const H = container.clientHeight;

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
  const zoomLayer = svg.append('g').attr('class', 'zoom-layer');

  zoomBehavior = d3.zoom()
    .scaleExtent([0.2, 4])
    .on('zoom', e => zoomLayer.attr('transform', e.transform));

  svg.call(zoomBehavior);

  // Double-click to reset zoom
  svg.on('dblclick.zoom', () => {
    svg.transition().duration(500)
      .call(zoomBehavior.transform, d3.zoomIdentity);
  });

  // ── Simulation ──
  simulation = d3.forceSimulation(allNodes)
    .force('link', d3.forceLink(allEdges).id(d => d.id).distance(90).strength(0.4))
    .force('charge', d3.forceManyBody().strength(-260))
    .force('center', d3.forceCenter(W / 2, H / 2))
    .force('collision', d3.forceCollide().radius(d => nodeRadius(d) + 12))
    .alphaDecay(0.028);

  // ── Links ──
  linkGroup = zoomLayer.append('g').attr('class', 'links');
  linkGroup.selectAll('line')
    .data(allEdges)
    .enter().append('line')
    .attr('stroke', d => EDGE_COLORS[d.type] || 'rgba(255,255,255,0.12)')
    .attr('stroke-width', 1.5)
    .attr('opacity', 0.6);

  // ── Nodes ──
  nodeGroup = zoomLayer.append('g').attr('class', 'nodes');
  const nodeEl = nodeGroup.selectAll('g')
    .data(allNodes)
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

  // Glow ring
  nodeEl.append('circle')
    .attr('r', d => nodeRadius(d) + 5)
    .attr('fill', 'none')
    .attr('stroke', d => trackColor(d))
    .attr('stroke-width', 1)
    .attr('opacity', 0.25);

  // Main circle
  nodeEl.append('circle')
    .attr('r', d => nodeRadius(d))
    .attr('fill', d => {
      const c = trackColor(d);
      return `radial-gradient(circle, ${c}44, ${c}11)`;
    })
    .attr('fill', d => trackColor(d) + '33')
    .attr('stroke', d => trackColor(d))
    .attr('stroke-width', 1.5);

  // Ticker label
  nodeEl.append('text')
    .text(d => d.ticker)
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .attr('font-family', "'Space Mono', monospace")
    .attr('font-size', d => Math.max(7, Math.min(10, nodeRadius(d) * 0.75)))
    .attr('fill', d => trackColor(d))
    .attr('pointer-events', 'none');

  simulation.on('tick', () => {
    linkGroup.selectAll('line')
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

    nodeGroup.selectAll('.node-g')
      .attr('transform', d => `translate(${d.x},${d.y})`);
  });
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
    <div class="tt-meta">${d.sector} · $${d.marketCap >= 1000 ? (d.marketCap/1000).toFixed(1)+'T' : d.marketCap+'B'}</div>
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
  selectedNode = d;
  openPanel(d);
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
  const capStr = mcap >= 1000
    ? '$' + (mcap / 1000).toFixed(2) + 'T'
    : '$' + mcap.toFixed(0) + 'B';
  const priceStr = d.price != null ? '$' + Number(d.price).toFixed(2) : '—';

  document.getElementById('panel-inner').innerHTML = `
    <div class="panel-header">
      <div>
        <div class="panel-ticker-badge" style="background:${color}22; color:${color}; border:1px solid ${color}55">${d.ticker}</div>
        <div class="panel-name">${d.name}</div>
        <div class="panel-sector">${d.sector}</div>
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
          <div class="stat-value">${capStr}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Price</div>
          <div class="stat-value price">${priceStr}</div>
        </div>
      </div>

      <div class="panel-section-title">Investment Track</div>
      <div class="track-badge" style="background:${color}22; border:1px solid ${color}44; color:${color}">
        <span class="dot"></span>
        ${t ? t.label : d.track}
      </div>

      <a class="panel-open-stock" href="stock.html?ticker=${encodeURIComponent(d.ticker)}">
        Open full stock page →
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
