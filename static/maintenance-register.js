/* Registration alone does not request notification permission. */
(() => {
  // This script only runs on a successfully loaded application page. A fallback
  // document deliberately keeps the marker so a failed return cannot loop.
  try { sessionStorage.removeItem('integrale-maintenance-return'); } catch (_) {}
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.register('/service-worker.js', {
    scope: '/',
    updateViaCache: 'none',
  }).catch(() => {
    // The site remains usable if the browser disallows service workers.
  });
})();
