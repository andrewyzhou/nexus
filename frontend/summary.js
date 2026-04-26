/**
 * summary.js — AI summary loader shared by stock.html and track.html.
 *
 * Backend response shape:
 *   {
 *     headline: "two-sentence narrative",
 *     bullets:  [{ text, source_indices: [1,2] }, ...],
 *     sources:  [{ index, title, url, publisher, published, image }, ...],
 *     generated_at: "2026-04-26T...",
 *     cached: bool, model: "claude-haiku-4-5-20251001"
 *   }
 *
 * Citation behavior preserved from previous version: clicking a [N] marker
 * scrolls to the corresponding news card and flashes a highlight. The card
 * id is `news-card-<index-1>` (0-based) since stock.js renders the same
 * ordered list returned by /companies/<ticker>/news.
 */
(function () {
  const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
    || 'http://localhost:5001/nexus/api';

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function relTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60)        return `${Math.floor(sec)}s ago`;
    if (sec < 3600)      return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400)     return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 604800)    return `${Math.floor(sec / 86400)}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  async function postJSON(path) {
    const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  function jumpToCard(idx /* 0-based */) {
    const card = document.getElementById(`news-card-${idx}`);
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.add('news-highlight');
    setTimeout(() => card.classList.remove('news-highlight'), 2400);
  }

  /**
   * Render the headline paragraph + bulleted list.
   * Each bullet gets inline `[N]` markers — one per source_index — that
   * scroll to news-card-<N-1> and highlight it (preserving the old UX).
   */
  function renderSummary(data) {
    const wrap = document.getElementById('ai-summary');
    if (!wrap) return;

    const bullets = Array.isArray(data.bullets) ? data.bullets : [];
    const headline = (data.headline || '').trim();

    if (!headline && !bullets.length) {
      wrap.innerHTML = `
        <div class="news-empty">
          No summary available. ${(!data.sources || !data.sources.length)
            ? 'No news articles to summarize.'
            : 'AI service unreachable — try refreshing.'}
        </div>`;
      return;
    }

    const headlineHtml = headline
      ? `<p class="summary-headline">${escapeHtml(headline)}</p>`
      : '';

    const bulletsHtml = bullets.length
      ? `<ul class="summary-bullets">${bullets.map(b => {
          const indices = Array.isArray(b.source_indices) ? b.source_indices : [];
          const cites = indices.map(i =>
            `<a href="#" class="citation" data-card-idx="${i - 1}">[${i}]</a>`
          ).join('');
          return `<li>${escapeHtml(b.text || '')}<span class="citations-inline">${cites}</span></li>`;
        }).join('')}</ul>`
      : '';

    wrap.innerHTML = `${headlineHtml}${bulletsHtml}`;

    wrap.querySelectorAll('.citation').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const i = Number(el.dataset.cardIdx);
        if (Number.isFinite(i)) jumpToCard(i);
      });
    });
  }

  function setStatus(data) {
    const el = document.getElementById('summary-status');
    if (!el) return;
    if (!data || !data.headline) { el.textContent = ''; return; }
    const stamp = data.generated_at ? relTime(data.generated_at) : '';
    if (stamp) el.textContent = `updated ${stamp}${data.cached ? ' · cached' : ''}`;
    else el.textContent = data.cached ? 'cached' : 'freshly generated';
  }

  let _lastArgs = null;
  let _lastData = null;
  let _stampTimer = null;

  function startStampTicker() {
    if (_stampTimer) clearInterval(_stampTimer);
    _stampTimer = setInterval(() => setStatus(_lastData), 30 * 1000);
  }

  async function runSummary({ kind, key, force, onData }) {
    const wrap = document.getElementById('ai-summary');
    const status = document.getElementById('summary-status');
    if (!wrap) return;

    const base = kind === 'track'
      ? `/tracks/${encodeURIComponent(key)}/summary`
      : `/companies/${encodeURIComponent(key)}/summary`;
    const path = force ? `${base}?force=1` : base;

    wrap.innerHTML = `<div class="summary-skeleton">
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>`;
    if (status) status.textContent = 'generating…';

    try {
      const data = await postJSON(path);
      _lastData = data;
      renderSummary(data);
      setStatus(data);
      startStampTicker();
      if (typeof onData === 'function') onData(data);
    } catch (err) {
      wrap.innerHTML = `<div class="news-empty">Summary unavailable (${escapeHtml(err.message)}).</div>`;
      if (status) status.textContent = '';
    }
  }

  window.renderAISummary = function renderAISummary(args) {
    _lastArgs = { kind: args.kind, key: args.key, onData: args.onData };
    return runSummary(args);
  };

  document.addEventListener('click', (e) => {
    if (e.target.closest('.ai-regenerate') && _lastArgs) {
      runSummary({ ..._lastArgs, force: true });
    }
  });
})();
