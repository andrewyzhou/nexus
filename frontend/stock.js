/**
 * stock.js — per-stock detail page.
 * Hits /companies/<ticker>/live for fresh Yahoo Finance data and
 * /companies/<ticker>/news for headlines.
 */
const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
  || 'http://localhost:5001/nexus/api';

const params = new URLSearchParams(window.location.search);
const ticker = (params.get('ticker') || '').toUpperCase();

function fmtMoney(n) {
  if (n == null) return '—';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `$${(n / 1e6).toFixed(1)}M`;
  return `$${Number(n).toFixed(0)}`;
}
function fmtNum(n, d = 2) {
  if (n == null) return '—';
  return Number(n).toFixed(d);
}
function fmtDate(t) {
  if (!t) return '';
  const d = typeof t === 'number' ? new Date(t * 1000) : new Date(t);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

async function init() {
  if (!ticker) {
    document.getElementById('stock-title').textContent = 'No ticker specified';
    return;
  }
  document.getElementById('stock-title').textContent = ticker;

  const [liveRes, newsRes] = await Promise.allSettled([
    fetch(`${API_BASE}/companies/${ticker}/live`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
    fetch(`${API_BASE}/companies/${ticker}/news`).then(r => r.ok ? r.json() : []),
  ]);

  if (liveRes.status === 'fulfilled') {
    renderStock(liveRes.value);
  } else {
    document.getElementById('stock-description').textContent =
      `Backend unreachable or unknown ticker (${liveRes.reason}). Is main.py running?`;
  }

  renderNews(newsRes.status === 'fulfilled' ? newsRes.value : []);
}

function renderStock(d) {
  document.title = `Nexus — ${d.ticker} ${d.companyName || ''}`;
  document.getElementById('stock-title').textContent = `${d.companyName || d.ticker} (${d.ticker})`;
  document.getElementById('stock-description').textContent = d.description || '';
  const websiteEl = document.getElementById('stock-website');
  const websiteWrap = document.getElementById('stock-website-wrap');
  if (d.website) {
    websiteEl.href = d.website;
    websiteWrap.style.display = 'block';
  }
  document.getElementById('stock-track').textContent =
    d.sector ? `${d.sector} · ${d.industry || ''}` : 'Stock';

  const change = d.changePercent != null ? ` (${(d.changePercent * 100).toFixed(2)}%)` : '';
  document.getElementById('stock-price').textContent = d.price != null
    ? `$${fmtNum(d.price)}${change}`
    : 'Price —';
  document.getElementById('stock-mcap').textContent = `Market Cap ${fmtMoney(d.marketCap)}`;
  document.getElementById('stock-pe').textContent = `P/E ${fmtNum(d.trailingPE, 1)}`;
  document.getElementById('stock-sector').textContent = d.country || '';

  const stats = [
    ['Open',           d.open != null ? `$${fmtNum(d.open)}` : '—'],
    ['Previous close', d.previousClose != null ? `$${fmtNum(d.previousClose)}` : '—'],
    ['Day high',       d.dayHigh != null ? `$${fmtNum(d.dayHigh)}` : '—'],
    ['Day low',        d.dayLow != null ? `$${fmtNum(d.dayLow)}` : '—'],
    ['52 Week High',   d.fiftyTwoWeekHigh != null ? `$${fmtNum(d.fiftyTwoWeekHigh)}` : '—'],
    ['52 Week Low',    d.fiftyTwoWeekLow != null ? `$${fmtNum(d.fiftyTwoWeekLow)}` : '—'],
    ['Volume',         d.volume != null ? d.volume.toLocaleString() : '—'],
    ['Avg volume',     d.avgVolume != null ? d.avgVolume.toLocaleString() : '—'],
    ['EPS (TTM)',      fmtNum(d.trailingEPS)],
    ['Forward P/E',    fmtNum(d.forwardPE, 1)],
    ['Dividend yield', d.dividendYield != null ? `${(d.dividendYield * 100).toFixed(2)}%` : '—'],
    ['Beta',           fmtNum(d.beta)],
    ['Employees',      d.fullTimeEmployees != null ? d.fullTimeEmployees.toLocaleString() : '—'],
  ];

  document.getElementById('stats-grid').innerHTML = stats.filter(([, v]) => v !== '—').map(([k, v]) => `
    <div class="stat-cell">
      <div class="stat-label">${k}</div>
      <div class="stat-val">${v}</div>
    </div>
  `).join('');
}

function renderNews(items) {
  const wrap = document.getElementById('news-list');
  if (!items || items.length === 0) {
    wrap.innerHTML = '<div class="news-empty">No news returned for this ticker.</div>';
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
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

init();
