/**
 * theme.js — light/dark theme switcher.
 *
 * Default: light (per Meeting 8 spec). User choice persists in localStorage.
 * Add a button with id="theme-toggle" anywhere in the page to enable toggling.
 */
(function () {
  const KEY = 'nexus-theme';
  const stored = localStorage.getItem(KEY);
  const theme = stored || 'light';
  document.documentElement.dataset.theme = theme;

  // ︎ = Unicode text variation selector — forces glyph to render as
  // monochrome text rather than a color emoji on iOS/Android.
  function themeIcon(t) { return t === 'light' ? '☾︎' : '☀︎'; }

  function apply(t) {
    // Suppress all transitions during the theme flip so the swap is
    // instant rather than a wave of background/color animations across
    // every surface. Re-enabled on the next frame.
    const root = document.documentElement;
    root.classList.add('theme-switching');
    root.dataset.theme = t;
    localStorage.setItem(KEY, t);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = themeIcon(t);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => root.classList.remove('theme-switching'));
    });
  }

  // Set icon immediately (no flash) if the button is already in the DOM.
  // Also runs again on DOMContentLoaded as a guarantee for deferred scripts.
  function syncBtn() {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = themeIcon(document.documentElement.dataset.theme || 'light');
  }
  syncBtn();
  document.addEventListener('DOMContentLoaded', () => {
    syncBtn();
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const cur = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        apply(cur);
      });
    }
  });
})();
