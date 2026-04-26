/**
 * summary.js — AI summary loader shared by stock.html and track.html.
 *
 * Backend response shapes:
 *   company:
 *     { headline, bullets:[{ text, source_indices }], sources:[{...}],
 *       generated_at, cached, model }
 *   track:
 *     { headline, bullets:[{ tickers, text, source_indices }],
 *       sources:[{ index, ticker, ... }], generated_at, cached, model }
 *
 * Citation behavior preserved across both: clicking a [N] marker scrolls
 * to news-card-<N-1> (0-based) and flashes a highlight. Bullets in the
 * track variant render a ticker pill prefix.
 *
 * Freshness:
 *   "Analyzed today"      — generated_at < 24h. Green chip.
 *   "Analyzed N days ago" — 1-6 days. Gray chip.
 *   "Analyzed N days ago" — 7+ days. Orange chip + auto-regenerates on
 *                            load (no click needed).
 */
(function () {
  const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
    || 'http://localhost:5001/nexus/api';

  // Anything older than this auto-regenerates the next time the page loads.
  // Set high enough that the persistent cache isn't thrashed, low enough
  // that a stale brief doesn't survive across multiple visits.
  const STALE_DAYS_AUTO_REGEN = 7;

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function renderInlineMd(src) {
    if (!src) return '';
    let out = escapeHtml(src);
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');
    if (typeof DOMPurify !== 'undefined') {
      out = DOMPurify.sanitize(out, {
        ALLOWED_TAGS: ['strong', 'em', 'b', 'i'],
        ALLOWED_ATTR: [],
      });
    }
    return out;
  }

  function ageDays(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (isNaN(d)) return null;
    return Math.max(0, (Date.now() - d.getTime()) / 86400000);
  }

  function relTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60)     return 'now';
    if (sec < 3600)   return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400)  return `${Math.floor(sec / 3600)}h ago`;
    if (sec < 604800) return `${Math.floor(sec / 86400)}d ago`;
    return `on ${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`;
  }

  /**
   * Returns { label, state } for the freshness chip.
   * states: 'fresh' (green), 'recent' (gray), 'stale' (orange).
   * The 'stale' state also triggers an auto-regen on the next runSummary.
   */
  function freshness(iso) {
    const days = ageDays(iso);
    if (days == null) return { label: 'Analyzing…', state: 'fresh' };
    if (days < 1) return { label: 'Analyzed today', state: 'fresh' };
    const n = Math.floor(days);
    const phrase = n === 1 ? 'Analyzed 1 day ago' : `Analyzed ${n} days ago`;
    return { label: phrase, state: days >= STALE_DAYS_AUTO_REGEN ? 'stale' : 'recent' };
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
   * Track-mode bullets prefix a ticker pill (or pills) before the text.
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
      ? `<p class="summary-headline">${renderInlineMd(headline)}</p>`
      : '';

    const bulletsHtml = bullets.length
      ? `<ul class="summary-bullets">${bullets.map(b => {
          const indices = Array.isArray(b.source_indices) ? b.source_indices : [];
          const cites = indices.map(i =>
            `<a href="#" class="citation" data-card-idx="${i - 1}">[${i}]</a>`
          ).join('');
          const tickers = Array.isArray(b.tickers) ? b.tickers : [];
          const tickerPrefix = tickers.length
            ? `<span class="bullet-tickers">${tickers.map(t =>
                `<span class="bullet-ticker-pill">${escapeHtml(t)}</span>`
              ).join('')}</span>`
            : '';
          const text = renderInlineMd((b.text || '').trim());
          return `<li>${tickerPrefix}${text}${cites ? `&nbsp;<span class="citations-inline">${cites}</span>` : ''}</li>`;
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
    if (el) {
      if (!data || !data.headline) {
        el.textContent = '';
      } else {
        const stamp = data.generated_at ? relTime(data.generated_at) : '';
        el.textContent = stamp === 'now'
          ? 'updated now'
          : (stamp ? `updated ${stamp}` : (data.cached ? 'cached' : 'freshly generated'));
      }
    }
    const chip = document.getElementById('summary-fresh-chip');
    if (chip) {
      if (!data || !data.headline) {
        chip.style.display = 'none';
      } else {
        const f = freshness(data.generated_at);
        chip.style.display = '';
        chip.dataset.state = f.state;
        const labelEl = chip.querySelector('.fresh-chip-label');
        if (labelEl) labelEl.textContent = f.label;
      }
    }
  }

  let _lastArgs = null;
  let _lastData = null;
  let _stampTimer = null;

  function startStampTicker() {
    if (_stampTimer) clearInterval(_stampTimer);
    _stampTimer = setInterval(() => setStatus(_lastData), 30 * 1000);
  }

  async function runSummary({ kind, key, force, onData, _autoRegenAttempted }) {
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

      // Auto-regen: if we didn't force and what came back is older than
      // STALE_DAYS_AUTO_REGEN, kick off a fresh generation in the
      // background. We render the stale version first so the user sees
      // SOMETHING immediately, then quietly swap it. One-shot so we
      // don't loop if the regen also returns stale (shouldn't happen,
      // but belt-and-suspenders).
      if (!force && !_autoRegenAttempted) {
        const days = ageDays(data.generated_at);
        if (days != null && days >= STALE_DAYS_AUTO_REGEN) {
          runSummary({ kind, key, force: true, onData,
                       _autoRegenAttempted: true });
        }
      }
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
