/**
 * track.js — Nexus investment track detail page.
 *
 * Reads ?slug=... from the URL, fetches /tracks/<slug> from the backend,
 * and renders the track hero + sortable company table.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

const params = new URLSearchParams(window.location.search);
const slug = params.get('slug');

let track = null;
let sortKey = 'market_cap';

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

async function init() {
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
  if (res.status === 404) {
    renderError(`Track "${slug}" not found.`);
    return;
  }
  if (!res.ok) {
    renderError(`Backend error: ${res.status}`);
    return;
  }
  track = await res.json();
  render();
  loadNews();

  document.getElementById('sort-select').addEventListener('change', (e) => {
    sortKey = e.target.value;
    renderTable();
  });
}

async function loadNews() {
  const wrap = document.getElementById('news-list');
  try {
    const r = await fetch(`${API_BASE}/tracks/${encodeURIComponent(slug)}/news`);
    if (!r.ok) throw new Error(r.status);
    const items = await r.json();
    if (!items.length) {
      wrap.innerHTML = '<div class="news-empty">No news returned for this track.</div>';
      return;
    }
    wrap.innerHTML = items.map(n => `
      <a class="news-item" href="${n.link || '#'}" target="_blank" rel="noopener">
        <div class="news-title">${escapeHtml(n.title || '')}</div>
        <div class="news-meta">
          ${escapeHtml(n.publisher || '')} ${n.published ? '· ' + escapeHtml(fmtDate(n.published)) : ''}
          ${n.ticker ? '· <span class="news-ticker">' + escapeHtml(n.ticker) + '</span>' : ''}
        </div>
        ${n.summary ? `<div class="news-summary">${escapeHtml(n.summary)}</div>` : ''}
      </a>
    `).join('');
  } catch (err) {
    wrap.innerHTML = `<div class="news-empty">News unavailable (${err.message || err}).</div>`;
  }
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

function renderError(msg) {
  document.getElementById('track-title').textContent = 'Error';
  document.getElementById('track-description').textContent = msg;
}

function render() {
  document.title = `Nexus — ${track.name}`;
  document.documentElement.style.setProperty('--track-accent', track.color || '#00d4ff');
  document.getElementById('track-title').textContent = track.name;

  const desc = track.description || `Companies in the ${track.name} investment track.`;
  document.getElementById('track-description').textContent = desc;

  document.getElementById('track-count').textContent = `${track.company_count} companies`;
  if (track.market_leader) {
    const ml = track.market_leader;
    document.getElementById('track-leader').textContent =
      `Leader: ${ml.ticker} (${fmtMoney(ml.market_cap)})`;
  } else {
    document.getElementById('track-leader').textContent = '';
  }

  renderTable();
}

function comparator(a, b) {
  const av = a[sortKey];
  const bv = b[sortKey];
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  if (typeof av === 'string') return av.localeCompare(bv);
  return bv - av; // numeric desc
}

function renderTable() {
  const wrap = document.getElementById('company-table-wrap');
  const rows = [...track.companies].sort(comparator);

  if (rows.length === 0) {
    wrap.innerHTML = '<div class="empty">No companies linked to this track yet.</div>';
    return;
  }

  wrap.innerHTML = `
    <table class="company-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Ticker</th>
          <th>Name</th>
          <th>Sector</th>
          <th class="num">Price</th>
          <th class="num">Market Cap</th>
          <th class="num">P/E</th>
        </tr>
      </thead>
      <tbody>
        ${rows.map((c, i) => `
          <tr>
            <td class="dim">${i + 1}</td>
            <td><strong>${c.ticker}</strong></td>
            <td>${c.name || ''}</td>
            <td class="dim">${c.sector || '—'}</td>
            <td class="num">${c.price != null ? `$${fmtNum(c.price)}` : '—'}</td>
            <td class="num">${fmtMoney(c.market_cap)}</td>
            <td class="num">${fmtNum(c.pe_ratio, 1)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

init();
