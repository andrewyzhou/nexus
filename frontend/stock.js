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
  if (window.nexusAuthReady) await window.nexusAuthReady;
  if (!ticker) {
    document.getElementById('stock-title').textContent = 'No ticker specified';
    return;
  }
  document.getElementById('stock-title').textContent = ticker;

  const [liveRes, newsRes, dbRes] = await Promise.allSettled([
    fetch(`${API_BASE}/companies/${ticker}/live`).then(r => r.ok ? r.json() : Promise.reject(r.status)),
    fetch(`${API_BASE}/companies/${ticker}/news`).then(r => r.ok ? r.json() : []),
    fetch(`${API_BASE}/companies/${ticker}`).then(r => r.ok ? r.json() : null),
  ]);

  if (liveRes.status === 'fulfilled') {
    renderStock(liveRes.value, dbRes.status === 'fulfilled' ? dbRes.value : null);
  } else {
    document.getElementById('stock-description').textContent =
      `Backend unreachable or unknown ticker (${liveRes.reason}). Is main.py running?`;
  }

  renderNews(newsRes.status === 'fulfilled' ? newsRes.value : []);
  renderChart(ticker);
  }


function renderStock(d, dbData) {
  document.title = `Nexus — ${d.ticker} ${d.companyName || ''}`;
  document.getElementById('stock-title').textContent = `${d.companyName || d.ticker} (${d.ticker})`;
  document.getElementById('stock-description').textContent = d.description || '';
  const websiteEl = document.getElementById('stock-website');
  const websiteWrap = document.getElementById('stock-website-wrap');
  if (d.website) {
    websiteEl.href = d.website;
    websiteWrap.style.display = 'block';
  }
  
  const trackEl = document.getElementById('stock-track');
  if (dbData && dbData.investment_track) {
    const tr = dbData.investment_track;
    trackEl.innerHTML = `
      <a href="track.html?slug=${tr.slug}" style="
        display: inline-flex; 
        align-items: center;
        gap: 6px;
        padding: 8px 16px; 
        background: rgba(0, 212, 255, 0.12); 
        border: 1px solid rgba(0, 212, 255, 0.3); 
        border-radius: 8px; 
        color: var(--track-accent, #00d4ff); 
        font-weight: 600; 
        font-size: 13px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        cursor: pointer; 
        text-decoration: none;
        transition: all 0.2s ease;
      " onmouseover="this.style.background='rgba(0, 212, 255, 0.2)'" onmouseout="this.style.background='rgba(0, 212, 255, 0.12)'">
        <span>${tr.name}</span>
        <span style="font-size: 14px;">↗&#xFE0E;</span>
      </a>
    `;
  } else {
    trackEl.textContent = d.sector ? `${d.sector} · ${d.industry || ''}` : 'Stock';
  }

  function setPill(id, text) {
    const el = document.getElementById(id);
    if (!text || text === '—' || text === 'P/E —' || text === 'Market Cap —') {
      el.style.display = 'none';
    } else {
      el.textContent = text;
    }
  }

  const change = d.changePercent != null ? ` (${(d.changePercent * 100).toFixed(2)}%)` : '';
  setPill('stock-price', d.price != null ? `$${fmtNum(d.price)}${change}` : null);
  setPill('stock-mcap', d.marketCap != null ? `Market Cap ${fmtMoney(d.marketCap)}` : null);
  setPill('stock-pe', d.trailingPE != null ? `P/E ${fmtNum(d.trailingPE, 1)}` : null);
  setPill('stock-sector', d.country || null);

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
  // Stable `id="news-card-<i>"` per card — the AI summary's citation
  // links scroll to these indices.
  wrap.innerHTML = items.map((n, i) => `
    <a class="news-item" id="news-card-${i}" href="${n.link || '#'}" target="_blank" rel="noopener">
      <div class="news-title">${escapeHtml(n.title || '')}</div>
      <div class="news-meta">
        ${escapeHtml(n.publisher || '')} ${n.published ? '· ' + escapeHtml(fmtDate(n.published)) : ''}
        ${n.ticker ? '· <span class="news-ticker">' + escapeHtml(n.ticker) + '</span>' : ''}
      </div>
      ${n.summary ? `<div class="news-summary">${escapeHtml(n.summary)}</div>` : ''}
    </a>
  `).join('');

  // Kick off the AI summary now that news cards exist in the DOM.
  if (window.renderAISummary && ticker) {
    window.renderAISummary({ kind: 'company', key: ticker });
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

init();

function renderChart(ticker) {
  const script = document.createElement('script');
  script.type = 'text/javascript';
  script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async = true;
  script.innerHTML = JSON.stringify({
    allow_symbol_change: false,
    calendar: false,
    details: false,
    hide_side_toolbar: true,
    hide_top_toolbar: false,
    hide_legend: false,
    hide_volume: false,
    hotlist: false,
    interval: "D",
    locale: "en",
    save_image: true,
    style: "1",
    symbol: ticker,  
    theme: "light",
    timezone: "Etc/UTC",
    backgroundColor: "#ffffff",
    gridColor: "rgba(46, 46, 46, 0.06)",
    autosize: true
  });

  document.querySelector('.tradingview-widget-container').appendChild(script);
}