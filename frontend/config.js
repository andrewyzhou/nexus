/**
 * config.js — injects window.NEXUS_API so main.js / track.js / stock.js
 * don't hard-code the backend URL.
 *
 * Loaded BEFORE any app script. Logic:
 *   - local dev (localhost / 127.0.0.1): the frontend runs on :8000 via
 *     `python -m http.server` and the backend runs on :5001. We send all
 *     API calls to http://localhost:5001/nexus/api.
 *   - anywhere else: assume nginx proxies /nexus/api/* → backend on the
 *     same origin, so use a relative URL.
 *
 * Override by setting window.NEXUS_API BEFORE this script runs (useful
 * when testing a remote backend from localhost, etc.).
 */
(function () {
  if (window.NEXUS_API) return;  // caller already set it

  var host = window.location.hostname;
  if (host === 'localhost' || host === '127.0.0.1' || host === '') {
    window.NEXUS_API = 'http://localhost:5001/nexus/api';
  } else {
    window.NEXUS_API = '/nexus/api';
  }
})();
