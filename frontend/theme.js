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

  function apply(t) {
    document.documentElement.dataset.theme = t;
    localStorage.setItem(KEY, t);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = t === 'light' ? '☾' : '☀';
  }

  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme || 'light');
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', () => {
        const cur = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        apply(cur);
      });
    }
  });
})();
