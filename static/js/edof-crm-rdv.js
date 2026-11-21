/* Rendez-vous téléphoniques CRM visibles en lecture seule dans Intégrale EDOF. */
(() => {
  const page = document.querySelector('[data-edof-crm-rdv-url]');
  const nodes = Array.from(document.querySelectorAll('[data-edof-crm-rdv]'));
  if (!page || !nodes.length) return;

  const folderIds = [...new Set(nodes.map(node => node.dataset.edofCrmRdv).filter(Boolean))];
  const crmHome = 'https://assistance-alw9.onrender.com/crm/pistes';
  const dateFormat = new Intl.DateTimeFormat('fr-FR', {
    timeZone: 'Europe/Paris', weekday: 'short', day: 'numeric', month: 'short',
    year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  let running = false;
  let checked = false;

  function addLink(node, url, label) {
    let resolved;
    try { resolved = new URL(url, location.origin); } catch (_) { return; }
    if (resolved.origin !== 'https://assistance-alw9.onrender.com' ||
        !resolved.pathname.startsWith('/crm/')) return;
    const link = document.createElement('a');
    link.href = resolved.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = label;
    node.append(link);
  }

  function paint(node, item) {
    const state = item?.status || 'unavailable';
    node.textContent = '';
    node.dataset.rdvStatus = state;
    const title = document.createElement('strong');
    title.className = 'edof-crm-rdv-status';
    if (state === 'scheduled') {
      title.textContent = 'RDV prévu';
      node.append(title);
      const start = Date.parse(item.start_at || '');
      const details = document.createElement('span');
      details.className = 'edof-crm-rdv-date';
      details.textContent = Number.isFinite(start) ? dateFormat.format(new Date(start)) : 'Horaire à vérifier';
      node.append(details);
      if (item.host) {
        const who = document.createElement('small');
        who.textContent = 'Avec ' + item.host;
        node.append(who);
      }
      addLink(node, item.crm_url, 'Voir le rendez-vous dans le CRM');
    } else if (state === 'none') {
      title.textContent = 'Aucun RDV prévu';
      node.append(title);
      if (item.crm_url) addLink(node, item.crm_url, 'Fiche CRM');
    } else if (state === 'unmatched') {
      title.textContent = 'Rapprochement à vérifier';
      node.append(title);
      addLink(node, crmHome, 'Ouvrir le CRM');
    } else {
      title.textContent = 'CRM indisponible';
      node.append(title);
      addLink(node, crmHome, 'Vérifier dans le CRM');
    }
  }

  async function refresh() {
    if (running || document.visibilityState === 'hidden') return;
    running = true;
    try {
      const endpoint = new URL(page.dataset.edofCrmRdvUrl, location.origin);
      folderIds.forEach(id => endpoint.searchParams.append('folder', id));
      const controller = new AbortController();
      const abortAfter = setTimeout(() => controller.abort(), 13000);
      let response;
      try {
        response = await fetch(endpoint.href, {
          headers: {Accept: 'application/json'},
          credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        });
      } finally {
        clearTimeout(abortAfter);
      }
      if (!response.ok) throw new Error('CRM temporarily unavailable');
      const payload = await response.json();
      if (payload.ok !== true || !payload.appointments) throw new Error('Incomplete CRM response');
      nodes.forEach(node => paint(node, payload.appointments[node.dataset.edofCrmRdv]));
    } catch (_) {
      if (!checked) nodes.forEach(node => paint(node, {status: 'unavailable'}));
    } finally {
      checked = true;
      running = false;
    }
  }

  refresh();
  window.setInterval(refresh, 120000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') refresh();
  });
})();
