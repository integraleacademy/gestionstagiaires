(() => {
  'use strict';
  const root = document.getElementById('afcHours');
  if (!root) return;
  let state = JSON.parse(document.getElementById('afcHoursState').textContent);
  const rows = [...root.querySelectorAll('[data-trainee]')];
  const dateFields = [...root.querySelectorAll('[data-entry-date]')];
  const overrideFields = [...root.querySelectorAll('[data-start-override]')];
  const message = document.getElementById('afcHoursMessage');
  const exportButton = document.getElementById('afcHoursExport');
  const saveButton = document.getElementById('afcHoursSave');
  const fillButton = document.getElementById('afcHoursFill');
  const suggestButton = document.getElementById('afcHoursSuggest');
  let busy = false;
  let dirty = false;
  const formatDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.split('-').reverse().join('/') : 'À renseigner';
  const dates = () => Object.fromEntries(dateFields.map(input => [input.dataset.entryDate, input.value]));
  const profiles = () => Object.fromEntries(rows.map(row => {
    const value = row.querySelector('[data-ran-choice]').value;
    return [row.dataset.trainee, value === '' ? null : value === 'planning' ? 'planning' : Number(value)];
  }));
  function showMessage(text, error = false) {
    message.textContent = text;
    message.classList.toggle('afc-hours-message-error', error);
  }
  function refresh() {
    const currentDates = dates();
    const counts = {'54': 0, '40': 0, '0': 0};
    let pending = 0;
    let missingDate = false;
    for (const row of rows) {
      const choice = row.querySelector('[data-ran-choice]').value;
      const start = row.querySelector('[data-row-start]');
      row.classList.toggle('is-pending', choice === '');
      if (choice === '') {
        pending++;
        start.textContent = 'À définir';
        row.querySelector('[data-row-total]').textContent = '—';
      } else {
        const entryDate = row.querySelector('[data-start-override]')?.value || currentDates[choice];
        const planned = choice === 'planning';
        const hours = planned ? state.planned_hours?.[entryDate] : Number(choice);
        if (hours in counts) counts[hours]++;
        if (planned) {
          row.querySelector('option[value="planning"]').textContent =
            Number.isInteger(hours) ? `Selon la date d’entrée · ${hours} h` : 'Selon la date d’entrée';
          if (!Number.isInteger(hours)) row.querySelector('details').open = true;
        }
        start.textContent = formatDate(entryDate);
        row.querySelector('[data-row-total]').textContent = Number.isInteger(hours) ? `${339 + hours} h` : '—';
        if (planned ? !Number.isInteger(hours) : !currentDates[choice]) missingDate = true;
      }
    }
    for (const hours of ['54', '40', '0']) {
      root.querySelector(`[data-count="${hours}"]`).textContent = counts[hours];
      root.querySelector(`[data-profile-date="${hours}"]`).textContent = `Début : ${formatDate(currentDates[hours])}`;
    }
    const matches = !state.target || Object.keys(counts).every(key => counts[key] === state.target[key]);
    const invalidDate = [...dateFields, ...overrideFields].some(input => !input.checkValidity());
    const conflicts = state.read_only && state.rows.some(row => row.date_conflict);
    const ready = rows.length > 0 && pending === 0 && !missingDate && !invalidDate && !conflicts;
    exportButton.disabled = busy || !ready;
    if (saveButton) saveButton.disabled = busy || rows.length === 0;
    if (fillButton) fillButton.disabled = busy || pending === 0;
    if (suggestButton) suggestButton.disabled = busy || !state.suggestion?.profiles;
    document.getElementById('afcHoursProgress').textContent = pending ? `${pending} profil${pending > 1 ? 's' : ''} à choisir sur ${rows.length}` : `${rows.length} profils renseignés`;
    if (!busy) {
      if (!rows.length) showMessage('Ajoutez des candidats à la session pour préparer l’export.');
      else if (pending) showMessage(state.suggestion?.issue || 'Sélectionnez les profils à 40 h et sans RAN, puis complétez les autres à 54 h.');
      else if (missingDate || invalidDate) showMessage('Complétez les dates d’entrée dans le calendrier.', true);
      else if (conflicts) showMessage('Une date individuelle a changé. Un administrateur doit enregistrer les profils.', true);
      else if (!matches) showMessage('Répartition adaptée aux parcours individuels. ' + (dirty ? 'Enregistrez pour appliquer les dates aux dossiers.' : 'Les heures enregistrées peuvent être exportées.'));
      else showMessage(dirty ? 'Répartition prête. Enregistrez pour appliquer les dates aux dossiers.' : 'Répartition prête pour l’export.');
    }
    return ready;
  }
  async function save() {
    const response = await fetch(root.dataset.saveUrl, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({csrf: state.csrf, revision: state.revision, dates: dates(), profiles: profiles(),
        start_overrides: Object.fromEntries(rows.map(row => [row.dataset.trainee, row.querySelector('[data-start-override]')?.value || '']))})
    });
    const result = await response.json().catch(() => null);
    if (!response.ok || !result?.ok) throw new Error(result?.error || 'Enregistrement impossible. Rechargez la page et réessayez.');
    state = result.state;
    dirty = false;
  }
  async function run(exportFile) {
    if (busy) return;
    if (exportFile && !refresh()) return;
    busy = true;
    refresh();
    rows.forEach(row => { row.querySelector('select').disabled = true; });
    [...dateFields, ...overrideFields].forEach(input => { input.disabled = true; });
    showMessage(exportFile ? 'Préparation du fichier Excel…' : 'Enregistrement des profils…');
    let error = null;
    try {
      if (!state.read_only) await save();
      if (exportFile) {
        const response = await fetch(`${root.dataset.exportUrl}?revision=${encodeURIComponent(state.revision)}`);
        if (!response.ok || !response.headers.get('Content-Type')?.includes('spreadsheetml')) {
          const failure = await response.json().catch(() => null);
          throw new Error(failure?.error || 'Export impossible. Vérifiez votre connexion et réessayez.');
        }
        const blobUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = blobUrl;
        link.download = 'AFC_heures_formation.xlsx';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 10000);
      }
    } catch (failure) { error = failure.message; }
    finally {
      busy = false;
      rows.forEach(row => { row.querySelector('select').disabled = state.read_only; });
      [...dateFields, ...overrideFields].forEach(input => { input.disabled = state.read_only; });
      const ready = refresh();
      if (error) showMessage(error, true);
      else if (exportFile) showMessage('Le fichier Excel a été téléchargé. Les profils et les dates sont enregistrés.');
      else if (ready) showMessage('Profils et dates enregistrés. Vous pouvez exporter le tableau Excel.');
      else showMessage(`Choix enregistrés. ${message.textContent}`);
    }
  }
  for (const row of rows) row.querySelector('select').addEventListener('change', () => { dirty = true; refresh(); });
  for (const input of [...dateFields, ...overrideFields]) input.addEventListener('change', () => { dirty = true; refresh(); });
  fillButton?.addEventListener('click', () => {
    for (const row of rows) {
      const select = row.querySelector('select');
      if (select.value === '') select.value = '54';
    }
    dirty = true;
    refresh();
  });
  function applySuggestion(onlyUnset) {
    if (!state.suggestion?.profiles || state.read_only) return;
    for (const row of rows) {
      const select = row.querySelector('select');
      if (select.value !== 'planning' && (!onlyUnset || select.value === '')) {
        select.value = String(state.suggestion.profiles[row.dataset.trainee]);
        dirty = true;
      }
    }
    refresh();
  }
  suggestButton?.addEventListener('click', () => applySuggestion(false));
  saveButton?.addEventListener('click', () => run(false));
  exportButton.addEventListener('click', () => run(true));
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  // Propose the test-based allocation without changing records on a GET.
  // Partial saved work remains untouched until the user clicks the explicit button.
  if (state.rows.length && state.rows.every(row => row.ran_hours === null)) applySuggestion(true);
  refresh();
})();
