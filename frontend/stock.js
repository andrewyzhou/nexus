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

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
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

  stockNewsItems = newsRes.status === 'fulfilled' ? newsRes.value : [];
  renderNews(stockNewsItems);
  loadSummary();
  renderChart(ticker);
}

function loadSummary() {
  if (!window.renderAISummary || !ticker) return;
  window.renderAISummary({
    kind: 'company',
    key: ticker,
    onData(data) {
      if (!data || !data.citations) return;
      const cited = new Set(data.citations.map(c => c.article_index));
      renderNews(stockNewsItems, cited);
    },
  });
}

function splitTitleIntoTwoLines(name) {
  // Mockup pattern: last word in italic + slate. Skip if it looks weird
  // (single word, or last "word" is just a stock-class suffix like "(A)").
  if (!name) return name;
  const trimmed = name.replace(/\s+(Inc\.?|Corp\.?|Corporation|Ltd\.?|Limited|Holdings|Co\.?|Company|PLC|S\.A\.|N\.V\.)$/i, '');
  const idx = trimmed.lastIndexOf(' ');
  if (idx <= 0 || idx > trimmed.length - 2) return escapeHtml(name);
  const top = trimmed.slice(0, idx);
  const bot = trimmed.slice(idx + 1);
  // If the suffix we trimmed is non-empty, append it back to the italic line
  const suffix = name.slice(trimmed.length);
  return `${escapeHtml(top)}<span class="hero-title-italic">${escapeHtml(bot + suffix)}</span>`;
}

function renderStock(d, dbData) {
  document.title = `Nexus — ${d.ticker} ${d.companyName || ''}`;

  // Title — company name with last word italicized
  const titleEl = document.getElementById('stock-title');
  titleEl.innerHTML = splitTitleIntoTwoLines(d.companyName || d.ticker);

  // Eyebrow — ticker + sector or just ticker
  const eyebrowEl = document.getElementById('stock-eyebrow');
  eyebrowEl.textContent = d.sector ? `${d.ticker} · ${d.sector}` : d.ticker;

  // Description — cap at 3 sentences to avoid walls of text
  const descEl = document.getElementById('stock-description');
  if (d.description) {
    const sentences = d.description.match(/[^.!?]*[.!?]+/g) || [];
    descEl.textContent = sentences.length > 3
      ? sentences.slice(0, 3).join('').trim()
      : d.description;
  } else {
    descEl.textContent = '';
  }

  // Hero actions: website + track link
  const websiteEl = document.getElementById('stock-website');
  if (d.website) {
    websiteEl.href = d.website;
    websiteEl.style.display = 'inline-flex';
  } else {
    websiteEl.style.display = 'none';
  }

  const trackChipEl = document.getElementById('stock-track-link');
  const trackNameEl = document.getElementById('stock-track-name');
  if (dbData && dbData.investment_track) {
    const tr = dbData.investment_track;
    trackChipEl.href = `track.html?slug=${tr.slug}`;
    trackNameEl.textContent = tr.name;
    trackChipEl.style.display = 'inline-flex';
    if (tr.color) {
      document.documentElement.style.setProperty('--track-accent', tr.color);
    }
  } else {
    trackChipEl.style.display = 'none';
  }

  // Hero meta strip
  const priceEl = document.getElementById('stock-meta-price');
  const changeEl = document.getElementById('stock-meta-change');
  const mcapEl = document.getElementById('stock-meta-mcap');
  const peEl = document.getElementById('stock-meta-pe');

  priceEl.textContent = d.price != null ? `$${fmtNum(d.price)}` : '—';

  if (d.changePercent != null) {
    const pct = d.changePercent * 100;
    changeEl.textContent = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
    changeEl.className = 'hero-meta-change ' + (pct >= 0 ? 'change-pos' : 'change-neg');
  } else {
    changeEl.textContent = '';
  }

  mcapEl.textContent = d.marketCap != null ? fmtMoney(d.marketCap) : '—';
  peEl.textContent = d.trailingPE != null ? fmtNum(d.trailingPE, 1) : '—';

  // Key stats grid
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
  ].filter(([, v]) => v !== '—');

  document.getElementById('stats-grid').innerHTML = stats.map(([k, v]) => `
    <div class="stat-cell">
      <div class="stat-label">${escapeHtml(k)}</div>
      <div class="stat-val">${escapeHtml(v)}</div>
    </div>
  `).join('');
}

let stockNewsItems = [];

function renderNews(items, citedSet) {
  const wrap = document.getElementById('news-list');
  const sub = document.getElementById('news-count-sub');

  if (!items || items.length === 0) {
    wrap.innerHTML = '<div class="news-empty">No news returned for this ticker.</div>';
    if (sub) sub.textContent = '';
    return;
  }

  if (sub) sub.textContent = `${items.length} article${items.length !== 1 ? 's' : ''}`;

  // id="news-card-<i>" uses the original array index so summary.js citation
  // clicks always resolve to the correct card regardless of any future reorder.
  wrap.innerHTML = items.map((n, i) => {
    const isCited = citedSet ? citedSet.has(i) : false;
    const t = n.ticker ? escapeHtml(n.ticker) : '';
    const source = n.publisher ? escapeHtml(n.publisher) : '';
    const date = fmtDate(n.published);
    const link = n.link ? escapeHtml(n.link) : '#';
    const title = escapeHtml(n.title || '');
    const summary = n.summary ? escapeHtml(n.summary) : '';

    return `
      <a class="news-item${isCited ? ' cited' : ''}" id="news-card-${i}" href="${link}" target="_blank" rel="noopener">
        <div class="news-item-body">
          <div class="news-item-meta">
            ${t ? `<span class="news-ticker-pill">${t}</span>` : ''}
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

function buildChartScript(ticker) {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
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
    interval: 'D',
    locale: 'en',
    save_image: true,
    style: '1',
    symbol: ticker,
    theme: isLight ? 'light' : 'dark',
    timezone: 'Etc/UTC',
    backgroundColor: isLight ? '#ffffff' : '#030712',
    gridColor: isLight ? 'rgba(46, 46, 46, 0.06)' : 'rgba(255, 255, 255, 0.04)',
    autosize: true,
  });
  return script;
}

function renderChart(ticker) {
  const container = document.querySelector('.tradingview-widget-container');
  container.appendChild(buildChartScript(ticker));

  // Re-render when theme toggles (TradingView doesn't support live theme updates)
  const observer = new MutationObserver(() => {
    container.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    container.appendChild(buildChartScript(ticker));
  });
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

init();
