/* Registration alone does not request notification permission. */
(() => {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  navigator.serviceWorker.register('/service-worker.js', {
    scope: '/',
    updateViaCache: 'none',
  }).catch(() => {
    // The site remains usable if the browser disallows service workers.
  });
})();
