(function () {
  'use strict';
  const root = document.querySelector('[data-partner-workspace]');
  if (!root) return;
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const search = root.querySelector('[data-pw-search]');
  const kind = root.querySelector('[data-pw-kind]');
  const rows = [...root.querySelectorAll('[data-pw-row]')];
  const noResults = root.querySelector('[data-pw-no-results]');
  function filter() {
    const query = normalize(search ? search.value.trim() : '');
    let visible = 0;
    rows.forEach(row => {
      row.hidden = !(normalize(row.dataset.search || '').includes(query) && (!kind || !kind.value || row.dataset.kind === kind.value));
      if (!row.hidden) visible++;
    });
    if (noResults) noResults.hidden = visible > 0 || rows.length === 0;
  }
  if (search) search.addEventListener('input', filter);
  if (kind) kind.addEventListener('change', filter);

  async function loadRoster(card, refresh) {
    if (card.dataset.loading || (card.dataset.loaded && !refresh)) return;
    const content = card.querySelector('[data-roster-content]');
    const button = card.querySelector('[data-roster-refresh]');
    card.dataset.loading = '1';
    content.setAttribute('aria-busy', 'true');
    button.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(card.dataset.rosterUrl, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok || response.redirected) throw new Error('Suivi indisponible');
      content.innerHTML = await response.text();
      card.dataset.loaded = '1';
    } catch (_) {
      content.replaceChildren();
      const notice = document.createElement('p');
      notice.className = 'pw-notice error';
      notice.textContent = 'Le suivi n’a pas pu être chargé. Cliquez sur « Actualiser la progression » pour réessayer.';
      content.append(notice);
    } finally {
      clearTimeout(timeout);
      delete card.dataset.loading;
      content.removeAttribute('aria-busy');
      button.disabled = false;
    }
  }
  root.querySelectorAll('[data-roster-url]').forEach(card => {
    card.addEventListener('toggle', () => { if (card.open) loadRoster(card, false); });
    card.querySelector('[data-roster-refresh]').addEventListener('click', () => loadRoster(card, true));
  });
  const dialog = root.querySelector('#partner-document');
  const frame = dialog.querySelector('iframe');
  const loader = dialog.querySelector('.pw-dialog-loading');
  let opener, changed = false;
  root.addEventListener('click', event => {
    const link = event.target.closest('[data-pw-dialog]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || !dialog.showModal) return;
    event.preventDefault();
    opener = link;
    dialog.querySelector('h2').textContent = link.dataset.title || 'Détail';
    frame.title = link.dataset.title || 'Détail du dossier';
    loader.hidden = false;
    frame.setAttribute('aria-busy', 'true');
    frame.src = link.href;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
  });
  frame.addEventListener('load', () => {
    if (!dialog.open) return;
    loader.hidden = true;
    frame.removeAttribute('aria-busy');
    // Same-origin embedded forms keep their standard server safeguards. Track
    // an actual submission so that the dossier reflects a saved change on close.
    try { frame.contentDocument.addEventListener('submit', () => { changed = true; }); } catch (_) { /* external invoice */ }
  });
  root.querySelector('[data-dialog-close]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    frame.removeAttribute('src');
    document.body.style.overflow = '';
    if (opener) opener.focus();
    if (changed) window.location.reload();
  });
  root.querySelectorAll('[data-single-submit]').forEach(form => form.addEventListener('submit', event => {
    if (event.defaultPrevented) return;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    button.textContent = 'Envoi en cours…';
  }));
  root.querySelectorAll('.pw-status-form').forEach(form => form.addEventListener('submit', event => {
    if (form.elements.status.value === 'cancelled' && !window.confirm('Annuler cette commande ? Vérifiez son règlement et sa facturation avant de continuer.')) event.preventDefault();
  }));
  let dirty = false;
  root.querySelectorAll('[data-pw-edit]').forEach(form => {
    form.addEventListener('input', () => { dirty = true; });
    form.addEventListener('change', () => { dirty = true; });
    form.addEventListener('submit', () => { dirty = false; });
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
})();
