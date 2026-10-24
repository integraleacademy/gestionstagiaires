(() => {
  'use strict';
  const root = document.getElementById('afc-documents');
  if (!root) return;
  const $ = id => document.getElementById(id), dialog = $('afc-documents-dialog'), run = $('afc-doc-run');
  const closeButtons = dialog.querySelectorAll('[data-afc-doc-close]'), statuses = new Map();
  let plan = null, documentKind = '', action = '', busy = false, previewVersion = 0, job = null;
  const node = (tag, text) => { const el = document.createElement(tag); if (text) el.textContent = text; return el; };
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
  const failure = (message, details = {}) => Object.assign(new Error(message), details);
  closeButtons.forEach(button => button.addEventListener('click', () => {
    if (!busy) { previewVersion++; dialog.close(); }
  }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); else previewVersion++; });
  window.addEventListener('beforeunload', event => { if (busy) { event.preventDefault(); event.returnValue = ''; } });

  async function json(url, options = {}) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, ...options});
      if (response.redirected || response.status === 401) {
        throw failure('Votre session a expiré. Reconnectez-vous dans un autre onglet, puis cliquez sur Reprendre le traitement.');
      }
      // A proxy or a server restarting may return an HTML page instead of JSON.
      let value = null;
      try { value = JSON.parse(await response.text()); } catch (_) { /* handled below */ }
      if (response.status === 403) {
        throw failure(value?.error || 'Cet accès n’est plus autorisé. Reconnectez-vous puis reprenez le traitement.',
          {csrfExpired: value?.code === 'csrf_expired'});
      }
      if (response.status >= 500 || response.status === 429 || value?.pending || value?.retryable) {
        throw failure(value?.pending ? 'Le document est en cours de préparation.' : 'Le serveur est momentanément indisponible.', {retryable: true});
      }
      if (!response.ok) throw failure(value?.error || 'Ce dossier n’est plus accessible. Rechargez la liste.');
      if (!value || typeof value !== 'object') throw failure('La réponse du serveur n’a pas pu être confirmée.', {retryable: true});
      return value;
    } catch (error) {
      if (error instanceof TypeError || error.name === 'AbortError') {
        throw failure('La connexion au serveur a été interrompue.', {retryable: true});
      }
      throw error;
    } finally { clearTimeout(timeout); }
  }

  async function recover(operation, onWait) {
    const deadline = performance.now() + 180000;
    let attempt = 0;
    for (;;) {
      try { return await operation(); }
      catch (error) {
        if (!error.retryable || performance.now() >= deadline) throw error;
        const wait = Math.min(10000, 1000 * 2 ** Math.min(attempt++, 4));
        onWait(error.message, Math.ceil(wait / 1000));
        await delay(wait);
      }
    }
  }

  root.querySelectorAll('[data-afc-document]').forEach(button => button.addEventListener('click', async () => {
    if (busy) return;
    const version = ++previewVersion;
    documentKind = button.dataset.afcDocument; action = button.dataset.afcAction; plan = null; job = null; statuses.clear();
    const plural = documentKind === 'convention' ? 'conventions' : 'convocations', send = action === 'send';
    const previewUrl = `${root.dataset.previewUrl}?document=${documentKind}&action=${action}`;
    $('afc-doc-title').textContent = `${send ? 'Envoyer' : 'Générer'} les ${plural}`;
    $('afc-doc-description').textContent = send
      ? (documentKind === 'convention' ? 'Chaque stagiaire recevra son lien de signature de la convention par e-mail.' : 'Chaque stagiaire recevra sa convocation personnalisée en pièce jointe par e-mail.')
      : 'Les PDF seront préparés et disponibles dans les fiches stagiaires. Les documents déjà à jour sont conservés. Aucun e-mail ne sera envoyé.';
    $('afc-doc-rows').replaceChildren(); $('afc-doc-feedback').textContent = 'Préparation de la liste…';
    $('afc-doc-progress').hidden = true; run.hidden = false; run.disabled = true; run.textContent = send ? 'Envoyer' : 'Générer';
    if (!dialog.open) dialog.showModal();
    try {
      const nextPlan = await recover(() => json(previewUrl), () => {
        if (version === previewVersion) $('afc-doc-feedback').textContent = 'Le serveur redémarre ou est momentanément indisponible. Chargement automatique dès son retour…';
      });
      if (version !== previewVersion) return;
      plan = nextPlan;
      plan.rows.forEach(row => {
        const tr = node('tr'), identity = node('td'); identity.append(node('strong', row.name), node('small', row.email || 'E-mail non renseigné'));
        const preview = node('td'), link = node('a', 'Aperçu PDF'); link.href = row.preview_url; link.target = '_blank'; link.rel = 'noopener'; preview.append(link);
        const status = node('td', row.eligible ? 'Prête' : row.reason); status.className = row.eligible ? '' : 'is-skipped';
        tr.append(identity, preview, status); $('afc-doc-rows').append(tr); statuses.set(row.id, status);
      });
      const count = plan.rows.filter(row => row.eligible).length, excluded = plan.rows.length - count, label = count === 1 ? documentKind : plural;
      $('afc-doc-feedback').textContent = `${count} ${label} à ${send ? 'envoyer' : 'générer'} · ${excluded} ${excluded === 1 ? 'exclue' : 'exclues'}`;
      run.textContent = `${send ? 'Envoyer' : 'Générer'} ${count} ${label}`; run.disabled = !count;
    } catch (error) { if (version === previewVersion) $('afc-doc-feedback').textContent = error.message; }
  }));

  run.addEventListener('click', async () => {
    if (busy || !plan) return;
    if (!job) job = {rows: plan.rows.filter(row => row.eligible).map(row => ({...row, requestId: crypto.randomUUID()})),
      index: 0, succeeded: 0, failed: 0, skipped: plan.rows.filter(row => !row.eligible).length};
    busy = true; run.disabled = true; closeButtons.forEach(button => { button.disabled = true; });
    const progress = $('afc-doc-progress'); progress.hidden = false; progress.max = job.rows.length; progress.value = job.index;
    let interruption = '';
    while (job.index < job.rows.length) {
      const row = job.rows[job.index], status = statuses.get(row.id);
      status.textContent = 'En cours…'; status.className = '';
      $('afc-doc-feedback').textContent = `${job.index + 1} / ${job.rows.length} · ${row.name} — gardez cette page ouverte.`;
      let refreshes = 0, refreshCsrf = false;
      try {
        const result = await recover(async () => {
          if (refreshCsrf) {
            const fresh = await json(`${root.dataset.previewUrl}?document=${documentKind}&action=${action}`);
            plan.csrf = fresh.csrf; refreshCsrf = false;
          }
          try {
            return await json(row.execute_url, {method: 'POST', body: JSON.stringify({csrf: plan.csrf,
              document: documentKind, action, revision: row.revision, request_id: row.requestId})});
          } catch (error) {
            if (error.csrfExpired && refreshes++ < 2) {
              refreshCsrf = true;
              throw failure('Actualisation de la session…', {retryable: true});
            }
            throw error;
          }
        }, (message, seconds) => {
          status.textContent = 'En attente · reprise automatique';
          $('afc-doc-feedback').textContent = `${message} Nouvelle vérification dans ${seconds} s. Les documents terminés sont conservés.`;
        });
        status.textContent = result.message || result.error || 'Erreur';
        status.className = result.skipped ? 'is-skipped' : result.ok ? 'is-success' : 'is-error';
        if (result.skipped) job.skipped++; else if (result.ok) job.succeeded++; else job.failed++;
        job.index++; progress.value = job.index;
      } catch (error) {
        interruption = error.message; status.textContent = 'En attente de reprise'; status.className = 'is-skipped';
        for (const pending of job.rows.slice(job.index + 1)) statuses.get(pending.id).textContent = 'En attente';
        break;
      }
    }
    const completed = action === 'send' ? 'envoyée' : 'générée', remaining = job.rows.length - job.index;
    $('afc-doc-feedback').textContent = `${job.succeeded} ${completed}${job.succeeded === 1 ? '' : 's'} · ${job.failed} en erreur · ${job.skipped} ${job.skipped === 1 ? 'exclue' : 'exclues'}.`
      + (interruption ? ` ${remaining} en attente. ${interruption} Cliquez sur Reprendre le traitement.` : ' Traitement terminé.');
    busy = false; run.hidden = !interruption; run.disabled = false; run.textContent = 'Reprendre le traitement';
    closeButtons.forEach(button => { button.disabled = false; });
  });
})();
