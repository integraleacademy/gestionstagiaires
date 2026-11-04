(() => {
  'use strict';
  const container = document.querySelector('[data-aps-roster-url]');
  if (!container) return;
  let busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(container.dataset.apsRosterUrl, {headers: {Accept: 'application/json'}, cache: 'no-store'});
      if (!response.ok) throw new Error('Suivi indisponible');
      const payload = await response.json();
      if (!payload.ok || !payload.rows) throw new Error('Suivi indisponible');
      document.querySelectorAll('[data-aps-roster-trainee]').forEach(cell => {
        const html = payload.rows[cell.dataset.apsRosterTrainee];
        if (typeof html === 'string') cell.innerHTML = html;
      });
    } catch (_error) {
      document.querySelectorAll('[data-aps-roster-trainee]').forEach(cell => {
        const status = cell.querySelector('.aps-live-status');
        if (status) { status.className = 'aps-live-status is-unknown'; status.textContent = 'Actualisation indisponible'; }
        else if (!cell.querySelector('.aps-followup')) cell.textContent = 'Suivi temporairement indisponible';
      });
    } finally { busy = false; }
  }
  refresh();
  setInterval(refresh, 30000);
  document.addEventListener('visibilitychange', refresh);
})();
