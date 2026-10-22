(() => {
  'use strict';
  const dialog = document.getElementById('securityExamDialog');
  const openButton = document.getElementById('btnA3pExamDossier');
  if (!dialog || !openButton) return;
  const base = dialog.dataset.url;
  const form = document.getElementById('securityExamCalendar');
  const status = document.getElementById('securityExamStatus');
  const candidates = document.getElementById('securityExamCandidates');
  const dateKeys = ['training_start_date', 'training_end_date', 'exam_date', 'epi_training_date'];
  const labels = ['début de formation', 'fin de formation', 'examen', 'formation EPI'];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let data = null, busy = false, dirty = false;
  const checks = () => [...candidates.querySelectorAll('[data-security-select]')];
  function message(text, error = false) {
    status.textContent = text;
    status.className = 'exam-status ' + (error ? 'error' : 'success');
  }
  function showTab(name) {
    if (name !== 'organization' && !dialog.dispatchEvent(new Event('exam-jury-before-leave', {cancelable:true}))) return;
    dialog.querySelectorAll('[data-security-panel]').forEach(el => { el.hidden = el.dataset.securityPanel !== name; });
    dialog.querySelectorAll('[data-security-tab]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.securityTab === name)));
    if (name === 'organization') dialog.dispatchEvent(new Event('exam-jury-load'));
  }
  async function api(url, payload) {
    const options = {credentials:'same-origin', headers:{Accept:'application/json'}};
    if (payload) { options.method = 'POST'; options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(payload); }
    const response = await fetch(url, options);
    let result;
    try { result = await response.json(); } catch { throw new Error('La réponse est indisponible. Rechargez la page ou reconnectez-vous.'); }
    if (!response.ok || result.ok === false) throw new Error(result.message || result.error || 'Cette action n’a pas pu être effectuée.');
    return result;
  }
  async function action(work) {
    if (busy) return;
    busy = true;
    dialog.querySelectorAll('[data-lock]').forEach(el => { el.disabled = true; });
    try { await work(); } catch (error) { message(error.message, true); }
    finally {
      busy = false;
      dialog.querySelectorAll('[data-lock]').forEach(el => { el.disabled = !data || !!data.read_only; });
      // Refreshing is a read operation, including for view-only administrators.
      dialog.querySelector('[data-security-refresh]').disabled = !data;
    }
  }
  function selectionCount() {
    const count = checks().filter(el => el.checked).length;
    document.getElementById('securityExamSelection').textContent = `${count} candidat(s) sélectionné(s)`;
    document.getElementById('securityExamToggle').textContent = count ? 'Tout désélectionner' : 'Tout sélectionner';
  }
  function render(selected) {
    const missing = dateKeys.filter(key => !data[key]);
    document.getElementById('securityExamCount').textContent = `${data.candidates.length} dossier(s) candidat(s)`;
    const note = document.getElementById('securityExamCalendarNote');
    note.hidden = !missing.length;
    note.textContent = missing.length ? 'Les dossiers sont consultables. Complétez le calendrier avant impression : ' + missing.map(key => labels[dateKeys.indexOf(key)]).join(', ') + '.' : '';
    candidates.innerHTML = data.candidates.map(row => `<article class="exam-card" data-security-candidate="${esc(row.id)}">
      <div class="exam-candidate-top"><div><div class="exam-candidate-name">${esc(row.first_name)} ${esc(row.last_name)}</div><span class="exam-muted">${data.pages} pages · Dossier examen ${esc(data.training)}</span></div>
      <div class="exam-actions"><a class="btn btn-primary" data-security-pdf href="${esc(row.dossier_url)}" target="_blank" rel="noopener">Dossier examen PDF</a><a class="btn btn-outline" data-security-pdf href="${esc(row.dossier_url)}?download=1" target="_blank" rel="noopener">Télécharger</a></div></div>
      <div class="exam-chips"><span class="exam-chip">Convocations</span><span class="exam-chip">Attestations</span><span class="exam-chip">Suivi et évaluation</span><span class="exam-chip ${row.has_photo ? 'ok' : 'warn'}">${row.has_photo ? '✓ Photo présente' : 'Photo à ajouter'}</span>${missing.length ? '<span class="exam-chip warn">Calendrier à compléter</span>' : ''}</div>
      <div class="exam-actions"><a href="${esc(row.edit_url)}" target="_blank" rel="noopener">Ouvrir la fiche du candidat</a></div>
      ${data.read_only ? '' : `<label class="exam-check security-exam-selection"><input type="checkbox" data-security-select data-lock value="${esc(row.id)}" ${selected.has(row.id) ? 'checked' : ''}>Inclure dans le téléchargement groupé</label>`}
      </article>`).join('') || '<p class="exam-empty">Aucun candidat actif dans cette session.</p>';
    dateKeys.forEach(key => { form.elements[key].value = data[key] || ''; });
    form.querySelector('fieldset').disabled = data.read_only;
    document.getElementById('securityExamBulk').hidden = data.read_only || !data.candidates.length;
    const generation = data.generation || {};
    document.getElementById('securityExamArchive').hidden = !generation.available;
    if (generation.available) {
      const when = generation.created_at ? new Date(generation.created_at).toLocaleString('fr-FR', {timeZone:'Europe/Paris',dateStyle:'short',timeStyle:'short'}) : '';
      document.getElementById('securityExamArchiveMeta').textContent = `${generation.candidate_count} dossier(s)${when ? ' · Généré le ' + when : ''}. Ce ZIP reprend les informations de cette génération. Préparez un nouveau ZIP après une modification.` + (generation.current_style ? '' : ' Ancienne présentation.');
      document.getElementById('securityExamArchiveLink').href = data.download_url;
    }
    dirty = false;
    selectionCount();
  }
  async function load(keepSelection = false) {
    const selected = keepSelection ? new Set(checks().filter(el => el.checked).map(el => el.value)) : null;
    data = await api(base);
    render(selected || new Set(data.selected_trainee_ids.length ? data.selected_trainee_ids : data.candidates.map(row => row.id)));
    dialog.querySelectorAll('[data-lock]').forEach(el => { el.disabled = busy || data.read_only; });
  }
  openButton.addEventListener('click', () => {
    dialog.showModal();
    showTab('candidates');
    if (busy) return;
    data = null;
    candidates.textContent = 'Chargement des dossiers…';
    document.getElementById('securityExamBulk').hidden = true;
    document.getElementById('securityExamCalendarNote').hidden = true;
    message('Chargement…');
    action(async () => { await load(); message(''); });
  });
  dialog.addEventListener('exam-jury-saved', () => {
    action(async () => { await load(true); message('La date d’examen a été mise à jour dans le calendrier et les dossiers.'); });
  });
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!data || !form.reportValidity()) return;
    const values = Object.fromEntries(dateKeys.map(key => [key, form.elements[key].value]));
    action(async () => {
      await api(base, {...values, csrf:data.csrf, revision:data.revision});
      await load(true);
      showTab('candidates');
      message('Calendrier enregistré. Les dossiers individuels utilisent ces dates.');
    });
  });
  candidates.addEventListener('change', selectionCount);
  dialog.addEventListener('click', event => {
    const target = event.target.closest('button,a');
    if (!target) return;
    if (target.hasAttribute('data-security-close')) dialog.close();
    if (target.dataset.securityTab) {
      if (dirty && target.dataset.securityTab !== 'calendar') { message('Enregistrez le calendrier avant de changer de rubrique.', true); return; }
      showTab(target.dataset.securityTab);
    }
    if (target.hasAttribute('data-security-pdf') && (dirty || busy)) {
      event.preventDefault();
      if (dirty) { showTab('calendar'); message('Enregistrez le calendrier avant d’ouvrir un dossier.', true); }
      else message('Veuillez patienter pendant l’opération en cours.');
    }
    if (target.hasAttribute('data-security-refresh')) {
      if (dirty) { showTab('calendar'); message('Enregistrez le calendrier avant d’actualiser.', true); return; }
      action(async () => { await load(true); message('Dossiers actualisés.'); });
    }
    if (target.id === 'securityExamToggle') {
      const select = !checks().some(el => el.checked);
      checks().forEach(el => { el.checked = select; });
      selectionCount();
    }
    if (target.id === 'securityExamGenerate' && data) {
      if (dirty || dateKeys.some(key => !data[key])) { showTab('calendar'); message('Complétez et enregistrez les quatre dates avant de préparer le ZIP.', true); return; }
      const selected = checks().filter(el => el.checked).map(el => el.value);
      if (!selected.length) { message('Sélectionnez au moins un candidat pour le téléchargement groupé.', true); return; }
      action(async () => {
        document.getElementById('securityExamProgress').hidden = false;
        message('Préparation du téléchargement groupé…');
        try {
          const result = await api(base + '/generate', {...Object.fromEntries(dateKeys.map(key => [key,data[key]])), selected_trainee_ids:selected});
          await load(true);
          message(`${result.candidate_count} dossier(s) prêt(s). Le ZIP est disponible ci-dessous.`);
        } finally { document.getElementById('securityExamProgress').hidden = true; }
      });
    }
  });
})();
