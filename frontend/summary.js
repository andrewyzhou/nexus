/**
 * summary.js — AI summary loader shared by stock.html and track.html.
 *
 * Usage from stock.js / track.js:
 *   renderAISummary({ kind: 'company', key: 'NVDA' });
 *   renderAISummary({ kind: 'track',   key: slug });
 *
 * Expects these DOM elements in the page:
 *   #ai-summary       — summary body container
 *   #summary-status   — small status text (e.g. "cached", "updated 2 min ago")
 *   .news-item#news-card-<i> — news cards with stable ids, already rendered
 *                              by the page's own renderNews() before we run
 *
 * The summary loads automatically on page load. We wait a tick for the news
 * list to render first so citation clicks can find the card to scroll to.
 */
(function () {
  const API_BASE = (typeof window !== 'undefined' && window.NEXUS_API)
    || 'http://localhost:5001/nexus/api';

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  /**
   * Parse Claude's markdown prose into sanitized HTML.
   * Falls back to escaped plain text if marked/DOMPurify aren't loaded
   * (e.g. CDN blocked on the user's network).
   */
  function renderMarkdown(src) {
    if (!src) return '';
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
      return `<p class="summary-text">${escapeHtml(src)}</p>`;
    }
    // marked: GFM basics, no raw HTML passthrough
    const html = marked.parse(src, {
      gfm: true,
      breaks: false,
      headerIds: false,
      mangle: false,
    });
    // Strip anything not on an allowlist. We don't expect headings/code
    // here but allow them defensively; drop scripts + iframes outright.
    return DOMPurify.sanitize(html, {
      ALLOWED_TAGS: ['p', 'strong', 'em', 'b', 'i', 'ul', 'ol', 'li',
                     'br', 'code', 'pre', 'blockquote', 'a', 'span'],
      ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    });
  }

  async function postJSON(path) {
    const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /**
   * Render plain prose with a trailing row of clickable [N] markers that
   * scroll to the corresponding news card. Simpler than inlining markers
   * inside the sentence (which would need prose-text search) and makes
   * the citation row visually distinct.
   */
  function renderSummary(data) {
    const wrap = document.getElementById('ai-summary');
    if (!wrap) return;

    if (!data.summary) {
      wrap.innerHTML = `
        <div class="news-empty">
          No summary available. ${data.used_articles === 0
            ? 'No news articles to summarize.'
            : 'AI service unreachable — try refreshing.'}
        </div>`;
      return;
    }

    const prose = renderMarkdown(data.summary);
    const marks = (data.citations || []).map(c => `
      <a href="#" class="citation" data-article-index="${c.article_index}"
         title="${escapeHtml(c.cited_text || '')}">[${c.ref}]</a>
    `).join(' ');

    wrap.innerHTML = `
      <div class="summary-text">${prose}</div>
      ${marks ? `<div class="citations-row"><span class="dim small">Sources:</span> ${marks}</div>` : ''}
      <div class="summary-foot dim small">
        Citations scroll to the article above.
      </div>
    `;

    wrap.querySelectorAll('.citation').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        const idx = Number(el.dataset.articleIndex);
        if (!Number.isFinite(idx)) return;
        const card = document.getElementById(`news-card-${idx}`);
        if (!card) return;
        card.scrollIntoView({ behavior: 'smooth', block: 'center' });
        card.classList.add('news-highlight');
        setTimeout(() => card.classList.remove('news-highlight'), 2400);
      });
    });
  }

  let _lastArgs = null;

  async function runSummary({ kind, key, onData }) {
    const wrap = document.getElementById('ai-summary');
    const status = document.getElementById('summary-status');
    if (!wrap) return;

    const path = kind === 'track'
      ? `/tracks/${encodeURIComponent(key)}/summary`
      : `/companies/${encodeURIComponent(key)}/summary`;

    wrap.innerHTML = `<div class="summary-skeleton">
      <div class="skeleton-line"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line short"></div>
    </div>`;
    if (status) status.textContent = 'generating…';

    try {
      const data = await postJSON(path);
      renderSummary(data);
      if (status) status.textContent = data.cached ? 'cached · refreshes every 15 min' : 'freshly generated';
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
      runSummary(_lastArgs);
    }
  });
})();
