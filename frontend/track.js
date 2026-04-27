/**
 * track.js — Nexus investment track detail page.
 *
 * Reads ?slug=... from the URL, fetches /tracks/<slug> from the backend,
 * and renders the track hero + sortable company table + news grid.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

const params = new URLSearchParams(window.location.search);
const slug = params.get('slug');

let track = null;
let sortKey = 'market_cap';

let allNewsItems = [];
let citedIndices = new Set();
let activeTicker = 'all';
let newsSort = 'cited';

function fmtMoney(n) {
  if (n == null) return '—';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toFixed(0)}`;
}

function fmtNum(n, digits = 2) {
  if (n == null) return '—';
  return Number(n).toFixed(digits);
}

function fmtDate(t) {
  if (!t) return '';
  const d = typeof t === 'number' ? new Date(t * 1000) : new Date(t);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function init() {
  if (window.nexusAuthReady) await window.nexusAuthReady;
  if (!slug) {
    document.getElementById('track-title').textContent = 'No track selected';
    return;
  }

  let res;
  try {
    res = await fetch(`${API_BASE}/tracks/${encodeURIComponent(slug)}`);
  } catch (err) {
    renderError(`Backend unreachable at ${API_BASE}. Is main.py running?`);
    return;
  }

  if (res.status === 404) { renderError(`Track "${slug}" not found.`); return; }
  if (!res.ok) { renderError(`Backend error: ${res.status}`); return; }

  track = await res.json();
  render();
  loadNews();

  document.getElementById('sort-select').addEventListener('change', (e) => {
    sortKey = e.target.value;
    renderTable();
  });

  document.getElementById('news-sort-select').addEventListener('change', (e) => {
    newsSort = e.target.value;
    renderNews();
  });
}

async function loadNews() {
  try {
    const r = await fetch(`${API_BASE}/tracks/${encodeURIComponent(slug)}/news`);
    if (!r.ok) throw new Error(r.status);
    allNewsItems = await r.json();

    // Tag news items as cited based on their original (pre-sort) index.
    allNewsItems.forEach((n, idx) => { n._origIndex = idx; });

    buildTickerPills();
    renderNews();

    // Fetch summary in parallel so we can flag cited cards & re-sort
    if (slug) loadSummary();
  } catch (err) {
    document.getElementById('news-list').innerHTML =
      `<div class="news-empty">News unavailable (${escapeHtml(String(err.message || err))}).</div>`;
  }
}

function loadSummary() {
  if (!window.renderAISummary) return;
  window.renderAISummary({
    kind: 'track',
    key: slug,
    onData(data) {
      // Replace the news list with the summary's sources — that's the
      // ground truth for what citation indices refer to. Otherwise a
      // cached summary's `[N]` can land on the wrong card (or none)
      // when the per-ticker article set diverges between requests.
      if (Array.isArray(data.sources) && data.sources.length) {
        allNewsItems = data.sources.map((s, idx) => ({ ...s, _origIndex: idx }));
        buildTickerPills();
      }
      const cited = new Set();
      for (const b of (data.bullets || [])) {
        for (const i of (b.source_indices || [])) cited.add(i - 1);
      }
      citedIndices = cited;
      allNewsItems.forEach(n => {
        n.cited = citedIndices.has(n._origIndex);
      });
      renderNews();
    },
  });
}

function buildTickerPills() {
  // Each article can be tagged with multiple tickers (when several
  // constituents' news queries returned the same canonical URL — e.g.
  // an Intel/Nvidia partnership piece). Flatten them all into the
  // filter set.
  const everyTicker = new Set();
  for (const n of allNewsItems) {
    for (const t of (n.tickers || (n.ticker ? [n.ticker] : []))) {
      if (t) everyTicker.add(t);
    }
  }
  const tickers = ['all', ...everyTicker];
  const group = document.getElementById('ticker-filter-group');
  group.innerHTML = tickers.map(t => `
    <button class="ticker-pill${t === activeTicker ? ' active' : ''}" data-ticker="${escapeHtml(t)}">
      ${t === 'all' ? 'ALL' : escapeHtml(t)}
    </button>
  `).join('');

  group.querySelectorAll('.ticker-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      activeTicker = btn.dataset.ticker;
      group.querySelectorAll('.ticker-pill').forEach(b => b.classList.toggle('active', b === btn));
      renderNews();
    });
  });
}

function sortedNews() {
  let items = activeTicker === 'all'
    ? [...allNewsItems]
    : allNewsItems.filter(n => {
        const tags = n.tickers || (n.ticker ? [n.ticker] : []);
        return tags.includes(activeTicker);
      });

  if (newsSort === 'cited') {
    items.sort((a, b) => {
      const aC = !!(a.cited || a.referenced);
      const bC = !!(b.cited || b.referenced);
      if (aC !== bC) return bC ? 1 : -1;
      return (b.published || 0) - (a.published || 0);
    });
  } else if (newsSort === 'newest') {
    items.sort((a, b) => (b.published || 0) - (a.published || 0));
  } else {
    items.sort((a, b) => (a.published || 0) - (b.published || 0));
  }
  return items;
}

function renderNews() {
  const wrap = document.getElementById('news-list');
  const items = sortedNews();

  const sub = document.getElementById('news-count-sub');
  if (sub) sub.textContent = `${items.length} article${items.length !== 1 ? 's' : ''} across ${activeTicker === 'all' ? 'all tickers' : activeTicker}`;

  if (!items.length) {
    wrap.innerHTML = '<div class="news-empty">No news found.</div>';
    return;
  }

  wrap.innerHTML = items.map((n) => {
    const isCited = !!(n.cited || n.referenced);
    const tags = (n.tickers && n.tickers.length)
      ? n.tickers
      : (n.ticker ? [n.ticker] : []);
    const tickerPills = tags
      .map(t => `<span class="news-ticker-pill">${escapeHtml(t)}</span>`)
      .join('');
    const source = n.publisher ? escapeHtml(n.publisher) : '';
    const date = fmtDate(n.published);
    const link = n.link ? escapeHtml(n.link) : '#';
    const title = escapeHtml(n.title || '');
    const summary = n.summary ? escapeHtml(n.summary) : '';

    const image = n.image ? escapeHtml(n.image) : '';
    const number = (n._origIndex != null) ? (n._origIndex + 1) : '';

    return `
      <a class="news-item${isCited ? ' cited' : ''}" id="news-card-${n._origIndex}"
         href="${link}" target="_blank" rel="noopener">
        ${image ? `<div class="news-thumb"><img src="${image}" alt="" loading="lazy" onerror="this.parentElement.style.display='none'"/></div>` : ''}
        <div class="news-item-body">
          <div class="news-item-meta">
            ${number !== '' ? `<span class="news-num">${number}</span>` : ''}
            ${tickerPills}
            ${source ? `<span class="news-source">${source}</span>` : ''}
            ${date ? `<span class="news-dot">·</span><span class="news-date">${date}</span>` : ''}
            ${isCited ? `
              <span class="cited-badge">
                <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 17l-6.2 4.3 2.4-7.4L2 9.4h7.6z"/></svg>
                Cited
              </span>
            ` : ''}
          </div>
          <div class="news-title">${title}</div>
          ${summary ? `<div class="news-summary">${summary}</div>` : ''}
        </div>
        <span class="news-external-icon" aria-hidden="true">↗</span>
      </a>
    `;
  }).join('');
}

function renderError(msg) {
  document.getElementById('track-title').textContent = 'Error';
  document.getElementById('track-description').textContent = msg;
}

function render() {
  document.title = `Nexus — ${track.name}`;

  // Track accent override (still emerald-leaning by default)
  if (track.color) {
    document.documentElement.style.setProperty('--track-accent', track.color);
  }

  // Split title across two lines like the mockup ("Aerospace" + italic "Others")
  const titleEl = document.getElementById('track-title');
  const name = track.name || '';
  const splitIdx = name.lastIndexOf(' ');
  if (splitIdx > 0 && splitIdx < name.length - 1) {
    const top = name.slice(0, splitIdx);
    const bot = name.slice(splitIdx + 1);
    titleEl.innerHTML = `${escapeHtml(top)}<span class="hero-title-italic">${escapeHtml(bot)}</span>`;
  } else {
    titleEl.textContent = name;
  }

  const desc = track.description || `Companies in the ${track.name} investment track.`;
  document.getElementById('track-description').textContent = desc;

  document.getElementById('track-count').textContent = track.company_count ?? '—';

  const leaderEl = document.getElementById('track-leader');
  leaderEl.textContent = track.market_leader ? track.market_leader.ticker : '—';

  renderCompanyChips();
  startCyclingStats();
  renderTable();
}

function renderCompanyChips() {
  const wrap = document.getElementById('track-company-chips');
  if (!wrap) return;
  const cs = track.companies || [];
  wrap.innerHTML = cs.map(c => `
    <a href="stock.html?ticker=${encodeURIComponent(c.ticker)}" class="hero-track-chip">
      <span class="hero-track-dot"></span>
      <span>${escapeHtml(c.ticker)}</span>
      <span class="hero-action-arrow">↗</span>
    </a>
  `).join('');
}

// ── Cycling stats (Δ 1D + P/E, weighted ↔ equal-weighted, every 3s) ──
const CYCLE_MS = 3000;
let cycleTimer = null;
let cycleMode = 'W';     // 'W' = market-cap weighted, 'E' = equal-weighted

function aggregate(field, weighted) {
  const cs = (track.companies || []).filter(c => c[field] != null && Number.isFinite(c[field]));
  if (!cs.length) return null;
  if (!weighted) {
    const sum = cs.reduce((a, c) => a + Number(c[field]), 0);
    return sum / cs.length;
  }
  let totalW = 0, totalV = 0;
  for (const c of cs) {
    const w = Number(c.market_cap) > 0 ? Number(c.market_cap) : 0;
    if (!w) continue;
    totalW += w;
    totalV += w * Number(c[field]);
  }
  if (!totalW) return null;
  return totalV / totalW;
}

function fmtPct(v) {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function paintCyclingChips() {
  const weighted = cycleMode === 'W';
  const change = aggregate('change_pct', weighted);
  const pe     = aggregate('pe_ratio',   weighted);

  const chEl = document.getElementById('track-change');
  chEl.textContent = fmtPct(change);
  chEl.classList.toggle('change-pos', change != null && change >= 0);
  chEl.classList.toggle('change-neg', change != null && change <  0);

  document.getElementById('track-pe').textContent = pe == null ? '—' : pe.toFixed(1);

  for (const tag of document.querySelectorAll('.cycle-mode')) {
    tag.dataset.mode = cycleMode;
    tag.textContent  = cycleMode;
  }
}

function startCyclingStats() {
  if (cycleTimer) clearInterval(cycleTimer);
  paintCyclingChips();

  // Restart the progress-bar animation in lockstep with each tick.
  const restartBars = () => {
    for (const bar of document.querySelectorAll('.cycle-bar-fill')) {
      bar.style.animation = 'none';
      void bar.offsetWidth;     // force reflow
      bar.style.animation = '';
    }
  };
  restartBars();

  cycleTimer = setInterval(() => {
    cycleMode = cycleMode === 'W' ? 'E' : 'W';
    // Crossfade values: dim → swap → fade in
    const items = document.querySelectorAll('.hero-meta-item.is-cycling');
    items.forEach(el => el.classList.add('cycle-fading'));
    setTimeout(() => {
      paintCyclingChips();
      items.forEach(el => el.classList.remove('cycle-fading'));
      restartBars();
    }, 200);
  }, CYCLE_MS);
}

function comparator(a, b) {
  const av = a[sortKey];
  const bv = b[sortKey];
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  if (typeof av === 'string') return av.localeCompare(bv);
  return bv - av;
}

function renderTable() {
  const wrap = document.getElementById('company-table-wrap');
  const rows = [...(track.companies || [])].sort(comparator);

  const sub = document.getElementById('company-count-sub');
  if (sub) sub.textContent = `${rows.length} stock${rows.length !== 1 ? 's' : ''} in this track`;

  if (rows.length === 0) {
    wrap.innerHTML = '<div class="empty">No companies linked to this track yet.</div>';
    return;
  }

  wrap.innerHTML = `
    <table class="company-table">
      <thead>
        <tr>
          <th class="col-row-idx">#</th>
          <th>Ticker</th>
          <th>Company</th>
          <th class="col-num">Price</th>
          <th class="col-num">Δ 1D</th>
          <th class="col-trend">Trend</th>
          <th class="col-range">52w Range</th>
          <th class="col-num">Mkt Cap</th>
          <th class="col-num col-pe">P/E</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((c, i) => buildRow(c, i)).join('')}
      </tbody>
    </table>
  `;
}

function buildRow(c, i) {
  const change = c.change_pct ?? c.change ?? null;
  const changeClass = change == null ? '' : (change >= 0 ? 'change-pos' : 'change-neg');
  const changeStr = change == null
    ? '—'
    : `${change >= 0 ? '+' : ''}${Number(change).toFixed(2)}%`;

  const sparklineCell = c.sparkline
    ? `<td class="col-trend">${buildSparkline(c.sparkline, change)}</td>`
    : `<td class="col-trend"><span class="cell-pe-empty">—</span></td>`;

  const rangeCell = (c.week52_low != null && c.week52_high != null && c.price != null)
    ? `<td class="col-range">${build52wRange(c.week52_low, c.week52_high, c.price, change)}</td>`
    : `<td class="col-range"><span class="cell-pe-empty">—</span></td>`;

  const pe = c.pe_ratio != null
    ? `<span class="cell-pe">${fmtNum(c.pe_ratio, 1)}</span>`
    : `<span class="cell-pe-empty" title="Unprofitable — no P/E">—</span>`;

  return `
    <tr>
      <td class="col-row-idx">${String(i + 1).padStart(2, '0')}</td>
      <td>
        <a href="stock.html?ticker=${encodeURIComponent(c.ticker)}" class="ticker-cell">
          <span class="ticker-sym">${escapeHtml(c.ticker)}</span>
          <span class="ticker-arrow">↗</span>
        </a>
      </td>
      <td class="col-name">${escapeHtml(c.name || '')}</td>
      <td class="col-num">${c.price != null ? `$${fmtNum(c.price)}` : '—'}</td>
      <td class="col-num ${changeClass}">${changeStr}</td>
      ${sparklineCell}
      ${rangeCell}
      <td class="col-num">${fmtMoney(c.market_cap)}</td>
      <td class="col-num col-pe">${pe}</td>
    </tr>
  `;
}

function build52wRange(lo, hi, price, change) {
  const span = hi - lo;
  if (!(span > 0)) return '<span class="cell-pe-empty">—</span>';
  const pct = Math.max(0, Math.min(1, (price - lo) / span)) * 100;
  const positive = change == null || change >= 0;
  const cls = positive ? 'range-pos' : 'range-neg';
  const tip = `52w low ${fmtMoney(lo)} → high ${fmtMoney(hi)} · current ${fmtMoney(price)}`;
  return `
    <div class="range-bar ${cls}" title="${escapeHtml(tip)}">
      <div class="range-track"></div>
      <div class="range-marker" style="left:${pct.toFixed(1)}%"></div>
    </div>
  `;
}

function buildSparkline(data, change) {
  if (!Array.isArray(data) || data.length < 2) return '<span class="cell-pe-empty">—</span>';

  const W = 100;
  const H = 32;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = H - ((v - min) / range) * (H - 4) - 2;
    return [x, y];
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' ');
  const lastPt = points[points.length - 1];

  const positive = change == null || change >= 0;
  const color = positive ? '#34d399' : '#f87171';

  return `
    <svg class="sparkline-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
      <path d="${linePath}" fill="none" stroke="${color}" stroke-width="1.75"
            stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${lastPt[0].toFixed(1)}" cy="${lastPt[1].toFixed(1)}" r="2.5" fill="${color}"/>
    </svg>
  `;
}

init();
