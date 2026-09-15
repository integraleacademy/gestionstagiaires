(() => {
  const dialog = document.getElementById('apsDigiformaBulkDialog');
  const open = document.getElementById('btnImportDigiforma');
  if (!dialog || !open) return;
  const input = document.getElementById('apsDigiformaFiles');
  const start = document.getElementById('apsBulkStart');
  const status = document.getElementById('apsBulkStatus');
  const progress = document.getElementById('apsBulkProgress');
  const results = document.getElementById('apsBulkResults');
  const closeButtons = dialog.querySelectorAll('[data-aps-bulk-close]');
  let running = false;
  let files = [];
  let rows = [];
  let refreshOnClose = false;

  open.addEventListener('click', () => dialog.showModal());
  closeButtons.forEach(button => button.addEventListener('click', () => {
    if (!running) dialog.close();
  }));
  dialog.addEventListener('cancel', event => { if (running) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    if (refreshOnClose) window.location.reload();
  });
  window.addEventListener('beforeunload', event => {
    if (running) { event.preventDefault(); event.returnValue = ''; }
  });

  input.addEventListener('change', () => {
    files = Array.from(input.files || []);
    results.replaceChildren();
    progress.hidden = true;
    rows = files.map(file => {
      const row = document.createElement('li');
      const name = document.createElement('strong');
      const detail = document.createElement('span');
      name.textContent = file.name;
      detail.textContent = 'En attente';
      row.append(name, detail);
      results.append(row);
      return {row, detail};
    });
    status.textContent = `${files.length} fichier(s) sélectionné(s).`;
    start.disabled = !files.length;
    start.textContent = `Importer les ${files.length} relevé(s)`;
  });

  start.addEventListener('click', async () => {
    if (running || !files.length) return;
    running = true;
    start.disabled = true;
    input.disabled = true;
    closeButtons.forEach(button => { button.disabled = true; });
    progress.hidden = false;
    progress.max = files.length;
    progress.value = 0;
    let imported = 0, replaced = 0, errors = 0;
    try {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const {row, detail} = rows[index];
        status.textContent = `Import en cours : ${index + 1} / ${files.length}. Gardez cette page ouverte.`;
        detail.textContent = 'Lecture du PDF et recherche du stagiaire…';
        try {
          if (!file.name.toLowerCase().endsWith('.pdf')) throw new Error('Ce fichier n’est pas un PDF.');
          // Leave room for multipart headers within the existing request limit.
          if (file.size > Number(dialog.dataset.maxBytes) - 65536) throw new Error('Ce PDF est trop volumineux. Réduisez sa taille puis réessayez.');
          const form = new FormData();
          form.append('digiforma_pdf', file);
          const response = await fetch(dialog.dataset.uploadUrl, {
            method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}, body: form,
          });
          const contentType = response.headers.get('content-type') || '';
          const payload = contentType.includes('application/json') ? await response.json() : {};
          if (response.status === 401 || response.status === 403 || response.redirected) {
            throw Object.assign(new Error(payload.error || 'Votre session a expiré ou vos droits ne permettent plus cet import. Reconnectez-vous.'), {stopBatch: true});
          }
          if (!response.ok || !payload.ok) throw new Error(payload.error || 'Import impossible. Vérifiez ce fichier puis réessayez.');
          row.dataset.status = payload.status;
          if (payload.status === 'replaced') replaced += 1;
          else imported += 1;
          refreshOnClose = true;
          detail.textContent = `${payload.message} ${payload.trainee_name} · ${payload.duration} / 62 heures · Suivi : ${payload.attendance_rate}`;
          const link = document.createElement('a');
          link.href = payload.trainee_url;
          link.textContent = 'Ouvrir la fiche du stagiaire';
          link.target = '_blank';
          link.rel = 'noopener';
          row.append(link);
        } catch (error) {
          errors += 1;
          row.dataset.status = 'error';
          detail.textContent = error.message || 'Connexion interrompue. Réessayez ce relevé.';
          if (error.stopBatch) {
            for (let remaining = index + 1; remaining < files.length; remaining += 1) {
              rows[remaining].detail.textContent = 'Non traité : reconnectez-vous puis relancez l’import.';
              rows[remaining].row.dataset.status = 'error';
              errors += 1;
            }
            break;
          }
        }
        progress.value = index + 1;
      }
    } finally {
      running = false;
      input.disabled = false;
      closeButtons.forEach(button => { button.disabled = false; });
      status.textContent = `Import terminé : ${imported} nouveau(x), ${replaced} remplacé(s), ${errors} à vérifier.`;
      start.textContent = 'Import terminé';
    }
  });
})();
