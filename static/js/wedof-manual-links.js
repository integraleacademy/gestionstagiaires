(() => {
  const modal = document.querySelector('#wedof-manual-modal');
  const form = document.querySelector('#wedof-manual-form');
  if (!modal || !form) return;

  const sessionSearch = document.querySelector('#wedof-session-search');
  const traineeSearch = document.querySelector('#wedof-trainee-search');
  const sessionResults = document.querySelector('#wedof-session-results');
  const traineeResults = document.querySelector('#wedof-trainee-results');
  const feedback = document.querySelector('#wedof-manual-feedback');
  let folder = {};
  let chosenSession = null;
  let chosenTrainee = null;
  let currentRow = null;
  let timer;

  const esc = value => String(value || '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
  const fr = value => value ? String(value).slice(0, 10).split('-').reverse().join('/') : '—';
  const showFeedback = (message, error = false) => {
    if (!feedback) return;
    feedback.hidden = false;
    feedback.style.background = error ? '#fee2e2' : '#dcfce7';
    feedback.textContent = message;
  };
  async function getJson(url, {timeoutMs = 15000, ...options} = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {...options, signal: controller.signal,
        headers: {Accept: 'application/json', ...(options.headers || {})}});
      let payload;
      try { payload = await response.json(); } catch (_) { throw new Error('Réponse serveur illisible. Réessayez.'); }
      if (!response.ok) {
        const error = new Error(payload.message || 'Recherche indisponible.');
        error.code = payload.code || `http_${response.status}`;
        throw error;
      }
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') {
        const timeoutError = new Error('La recherche locale n’a pas répondu dans le délai prévu. Réessayez.');
        timeoutError.code = 'client_timeout';
        throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
  function renderFolder() {
    const identity = [folder.firstName, folder.lastName].filter(Boolean).join(' ') || folder.identity || '—';
    document.querySelector('#wedof-folder-summary').innerHTML =
      `<strong>Numéro WEDOF :</strong> ${esc(folder.externalId)}<br>` +
      `<strong>État :</strong> ${esc(folder.state) || '—'}<br>` +
      `<strong>Identité :</strong> ${esc(identity)}<br>` +
      `<strong>Email :</strong> ${esc(folder.email) || '—'}<br>` +
      `<strong>Téléphone :</strong> ${esc(folder.phone) || '—'}<br>` +
      `<strong>Dates WEDOF :</strong> ${fr(folder.dateStart)} — ${fr(folder.dateEnd)}`;
    document.querySelector('#wedof-confirm-folder').textContent = `${folder.externalId} — ${identity}`;
  }
  function dateWarnings() {
    const mismatch = Boolean(chosenSession) &&
      (chosenSession.date_start !== folder.dateStart || chosenSession.date_end !== folder.dateEnd);
    document.querySelector('#wedof-date-warning').hidden = !mismatch;
    const confirmation = document.querySelector('#wedof-date-confirm');
    confirmation.hidden = !mismatch;
    confirmation.querySelector('input').required = mismatch;
    document.querySelector('#wedof-archive-warning').hidden = !(chosenSession && chosenSession.archived);
    document.querySelector('#wedof-date-comparison').hidden = !chosenSession;
    document.querySelector('#wedof-remote-dates').textContent = `du ${fr(folder.dateStart)} au ${fr(folder.dateEnd)}`;
    document.querySelector('#wedof-local-dates').textContent = chosenSession
      ? `du ${fr(chosenSession.date_start)} au ${fr(chosenSession.date_end)}` : '—';
  }
  async function sessions(query = '', suggested = false) {
    const params = new URLSearchParams({q: query});
    if (suggested) {
      params.set('suggest_for_trainee', '1');
      params.set('email', folder.email || '');
      params.set('phone', folder.phone || '');
      params.set('first_name', folder.firstName || '');
      params.set('last_name', folder.lastName || '');
    }
    const payload = await getJson(`/admin/wedof/matching/manual/sessions?${params}`, {timeoutMs: 15000});
    sessionResults.innerHTML = '';
    const help = document.querySelector('#wedof-session-help');
    help.textContent = suggested && !payload.items.length
      ? 'Aucune inscription locale correspondante trouvée. Utilisez la recherche ci-dessous.'
      : 'Sélectionnez une session proposée : le stagiaire correspondant sera sélectionné automatiquement.';
    payload.items.forEach(item => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'wedof-choice';
      button.innerHTML = `<strong>${esc(item.name)}</strong> — du ${fr(item.date_start)} au ${fr(item.date_end)}` +
        (item.archived ? ' — <strong>Session archivée</strong>' : '');
      button.addEventListener('click', () => selectSession(item, button));
      sessionResults.append(button);
    });
    return payload.items;
  }
  async function selectSession(item, button) {
    chosenSession = item;
    chosenTrainee = null;
    form.elements.session_id.value = item.id;
    form.elements.trainee_id.value = '';
    traineeSearch.disabled = false;
    traineeResults.innerHTML = '';
    sessionResults.querySelectorAll('button').forEach(element => element.classList.toggle('selected', element === button));
    document.querySelector('#wedof-confirm-session').textContent = item.name;
    document.querySelector('#wedof-confirm-trainee').textContent = '—';
    dateWarnings();
    try {
      await trainees('');
      if (item.suggested_trainee) selectTrainee(item.suggested_trainee);
    } catch (error) { showFeedback(error.message, true); }
  }
  function selectTrainee(item) {
    chosenTrainee = item;
    form.elements.trainee_id.value = item.id;
    traineeResults.querySelectorAll('button').forEach(element =>
      element.classList.toggle('selected', element.dataset.traineeId === item.id));
    document.querySelector('#wedof-confirm-trainee').textContent = `${item.first_name} ${item.last_name}`;
  }
  async function trainees(query = '') {
    if (!chosenSession) return;
    const payload = await getJson(`/admin/wedof/matching/manual/trainees?session_id=${encodeURIComponent(chosenSession.id)}&q=${encodeURIComponent(query)}`, {timeoutMs: 15000});
    traineeResults.innerHTML = '';
    payload.items.forEach(item => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'wedof-choice';
      button.dataset.traineeId = item.id;
      button.textContent = `${item.first_name} ${item.last_name} — ${item.email || '—'} — ${item.phone || '—'}`;
      button.addEventListener('click', () => selectTrainee(item));
      traineeResults.append(button);
    });
  }
  async function openManualModal(button) {
    form.reset();
    chosenSession = chosenTrainee = null;
    currentRow = button.closest('tr');
    folder = {
      externalId: button.dataset.externalId, state: button.dataset.state,
      identity: button.dataset.identity, email: button.dataset.email, phone: button.dataset.phone,
      dateStart: button.dataset.dateStart, dateEnd: button.dataset.dateEnd,
    };
    form.elements.external_id.value = folder.externalId;
    traineeSearch.disabled = true;
    sessionResults.innerHTML = traineeResults.innerHTML = '';
    document.querySelector('#wedof-confirm-session').textContent = '—';
    document.querySelector('#wedof-confirm-trainee').textContent = '—';
    renderFolder();
    dateWarnings();
    modal.showModal();
    sessionSearch.disabled = false;
    const liveStatus = document.querySelector('#wedof-live-status');
    liveStatus.textContent = 'Récupération des informations WEDOF…';
    liveStatus.hidden = false;

    const localPromise = sessions('').then(items => {
      const preset = items.find(item => item.id === button.dataset.sessionId);
      if (preset) return selectSession(preset, sessionResults.children[items.indexOf(preset)]);
      return null;
    }).catch(error => { showFeedback(error.message, true); });
    const remotePromise = getJson(
      `/admin/wedof/matching/manual/folder?external_id=${encodeURIComponent(folder.externalId)}`,
      {timeoutMs: 8000}
    ).then(async detail => {
      folder = {...folder, state: detail.state || folder.state, firstName: detail.first_name,
        lastName: detail.last_name, email: detail.email, phone: detail.phone,
        dateStart: detail.date_start || folder.dateStart, dateEnd: detail.date_end || folder.dateEnd};
      renderFolder();
      dateWarnings();
      liveStatus.textContent = 'Vérification WEDOF en direct effectuée.';
    }).catch(error => {
      liveStatus.textContent = error.code === 'client_timeout'
        ? 'WEDOF met trop de temps à répondre. La recherche locale reste disponible.'
        : 'Vérification WEDOF en direct indisponible — dernier instantané utilisé.';
      showFeedback('Les informations détaillées WEDOF n’ont pas pu être actualisées. Vous pouvez continuer le rattachement à partir du dernier instantané connu.', true);
    });
    await Promise.allSettled([localPromise, remotePromise]);
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-manual-link]');
    if (button) openManualModal(button);
  });
  sessionSearch.addEventListener('input', () => {
    clearTimeout(timer); timer = setTimeout(() => sessions(sessionSearch.value).catch(error => showFeedback(error.message, true)), 180);
  });
  traineeSearch.addEventListener('input', () => {
    clearTimeout(timer); timer = setTimeout(() => trainees(traineeSearch.value).catch(error => showFeedback(error.message, true)), 180);
  });
  document.querySelector('#wedof-modal-cancel').addEventListener('click', () => modal.close());
  form.addEventListener('submit', async event => {
    if (!chosenSession || !chosenTrainee) {
      event.preventDefault();
      showFeedback('Sélectionnez une session et un stagiaire.', true);
      return;
    }
    event.preventDefault();
    window.WedofLoading?.forceHide();
    const loadingToken = window.WedofLoading?.show();
    try {
      const payload = await getJson(form.action, {timeoutMs: 30000, method: 'POST', headers: {
        Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest',
      }, body: new FormData(form)});
      currentRow.querySelector('[data-local-session]').textContent = payload.session;
      currentRow.querySelector('[data-local-trainee]').textContent = payload.trainee;
      const badge = currentRow.querySelector('[data-local-association-badge]');
      badge.textContent = payload.association;
      badge.className = 'wedof-badge is-neutral';
      currentRow.querySelector('[data-manual-link]')?.parentElement.remove();
      const counter = document.querySelector('#wedof-unlinked-count');
      if (counter) counter.textContent = payload.unlinked_count;
      showFeedback(payload.message);
      modal.close();
    } catch (error) {
      showFeedback(error.message, true);
    } finally {
      if (loadingToken) window.WedofLoading?.hide(loadingToken);
    }
  });
  window.addEventListener('pagehide', () => window.WedofLoading?.forceHide());
})();
