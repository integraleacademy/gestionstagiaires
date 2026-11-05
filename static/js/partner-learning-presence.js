(() => {
  const roster = document.querySelector('[data-presence-url]');
  if (!roster) return;
  const badges = [...roster.querySelectorAll('[data-learner-presence]')];
  if (!badges.length) return;
  let pending = false;
  async function refresh() {
    if (document.hidden || pending) return;
    pending = true;
    let records = {};
    try {
      const response = await fetch(roster.dataset.presenceUrl, {cache: 'no-store', headers: {Accept: 'application/json'}});
      if (response.ok) records = await response.json();
    } catch { /* A tracking outage must not be displayed as an absence. */ }
    finally { pending = false; }
    for (const badge of badges) {
      const live = records[badge.dataset.learnerPresence];
      badge.dataset.state = live === true ? 'live' : live === false ? 'offline' : 'unknown';
      badge.textContent = live === true ? 'LIVE' : live === false ? 'Hors ligne' : 'État inconnu';
    }
  }
  window.setInterval(refresh, 20000);
  document.addEventListener('visibilitychange', refresh);
})();
