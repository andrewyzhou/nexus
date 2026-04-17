/**
 * auth.js — Firebase gating for /nexus.
 *
 * Flow (kept simple for a no-build setup):
 *   1. Monkey-patch window.fetch synchronously so any outbound call to
 *      NEXUS_API waits on an auth-ready promise and, once ready, attaches
 *      an `Authorization: Bearer <firebase-id-token>` header.
 *   2. Hit /nexus/api/config to learn whether auth is actually required
 *      and fetch the Firebase client config.
 *   3. If auth is required, init Firebase (compat SDK, loaded in HTML),
 *      wait for the auth state. If signed in → resolve; if not signed in,
 *      bounce to the iPick login URL with a return= query arg.
 *
 * The rest of the app calls `await window.nexusAuthReady` at the top of
 * its init() so nothing fetches before the token is in place.
 */
(function () {
  const authReady = new Promise((resolve, reject) => {
    window.__nexusAuthResolve = resolve;
    window.__nexusAuthReject  = reject;
  });
  window.nexusAuthReady = authReady;

  // Synchronously patch fetch — we don't know yet whether auth is on, but
  // if it is, the gated await below blocks the patched fetch until the
  // ID token is available. For /config the gate is a no-op (it resolves
  // as soon as config is read).
  const _origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    init = init || {};
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const base = window.NEXUS_API || '';
    const isApi = base && url.indexOf(base) === 0;
    // Bootstrap call that auth.js itself makes — don't self-deadlock.
    const isConfig = isApi && url.replace(/\/+$/, '').endsWith('/config');

    if (isApi && !isConfig) {
      await window.nexusAuthReady;
      if (window.__nexusUser) {
        const token = await window.__nexusUser.getIdToken();
        const headers = new Headers(init.headers || {});
        headers.set('Authorization', 'Bearer ' + token);
        init.headers = headers;
      }
    }
    return _origFetch(input, init);
  };

  async function bootstrap() {
    const base = window.NEXUS_API || '';
    let cfg = null;
    try {
      const res = await _origFetch(base + '/config');
      if (res.ok) cfg = await res.json();
    } catch (e) {
      console.warn('[nexus] config fetch failed, assuming auth disabled:', e);
    }

    if (!cfg || !cfg.requireAuth) {
      console.info('[nexus] auth disabled');
      window.__nexusAuthResolve();
      return;
    }

    if (typeof firebase === 'undefined') {
      console.error('[nexus] Firebase SDK not loaded. Check <script> tags.');
      window.__nexusAuthResolve();
      return;
    }

    firebase.initializeApp({
      apiKey:     cfg.firebase.apiKey,
      authDomain: cfg.firebase.authDomain,
      projectId:  cfg.firebase.projectId,
    });

    firebase.auth().onAuthStateChanged((user) => {
      if (user) {
        window.__nexusUser = user;
        console.info('[nexus] authed as', user.email || user.uid);
        window.__nexusAuthResolve();
      } else {
        const login = cfg.loginUrl || 'https://www.ipick.ai';
        const returnTo = encodeURIComponent(window.location.href);
        console.info('[nexus] not signed in, redirecting to', login);
        // Give other scripts a tick to log, then jump.
        setTimeout(() => {
          window.location.href = login + (login.indexOf('?') >= 0 ? '&' : '?') + 'return=' + returnTo;
        }, 50);
      }
    });
  }

  bootstrap();
})();
