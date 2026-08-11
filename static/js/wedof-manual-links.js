(() => {
  const modal = document.querySelector('#wedof-manual-modal');
  const form = document.querySelector('#wedof-manual-form');
  if (!modal || !form) return;

  const searchInput = document.querySelector('#wedof-global-trainee-search');
  const results = document.querySelector('#wedof-enrolment-results');
  const resultsStatus = document.querySelector('#wedof-enrolment-status');
  const liveStatus = document.querySelector('#wedof-live-status');
  const modalAlert = document.querySelector('#wedof-modal-alert');
  const review = document.querySelector('#wedof-association-review');
  const reviewTitle = document.querySelector('#wedof-association-review-title');
  const reviewTrainee = document.querySelector('#wedof-review-trainee');
  const reviewSession = document.querySelector('#wedof-review-session');
  const reviewRemoteDates = document.querySelector('#wedof-review-remote-dates');
  const reviewLocalDates = document.querySelector('#wedof-review-local-dates');
  const reviewConfirm = document.querySelector('#wedof-review-confirm');
  const feedback = document.querySelector('#wedof-manual-feedback');

  let folder = {};
  let selectedEnrolment = null;
  let currentRow = null;
  let searchTimer = null;
  let searchSequence = 0;
  let searchWasEdited = false;

  const esc = value => String(value || '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
  const fr = value => value ? String(value).slice(0, 10).split('-').reverse().join('/') : '—';
  const identity = item => [item.first_name, item.last_name].filter(Boolean).join(' ').trim() || 'Stagiaire sans nom';
  const initials = item => [item.first_name, item.last_name]
    .filter(Boolean).map(value => String(value).trim().charAt(0)).join('').slice(0, 2).toUpperCase() || 'ST';

  function setModalAlert(message = '', type = 'info') {
    if (!modalAlert) return;
    modalAlert.hidden = !message;
    modalAlert.className = `wedof-modal-alert is-${type}`;
    modalAlert.textContent = message;
  }

  function showPageFeedback(message, error = false) {
    if (!feedback) return;
    feedback.hidden = false;
    feedback.className = `wedof-toast ${error ? 'is-error' : 'is-success'}`;
    feedback.textContent = message;
    window.setTimeout(() => { feedback.hidden = true; }, 7000);
  }

  async function getJson(url, {timeoutMs = 15000, ...options} = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        ...options,
        signal: controller.signal,
        headers: {Accept: 'application/json', ...(options.headers || {})},
      });
      let payload;
      try {
        payload = await response.json();
      } catch (_) {
        throw new Error('Réponse serveur illisible. Réessayez.');
      }
      if (!response.ok) {
        const error = new Error(payload.message || payload.error || 'Recherche indisponible.');
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
      window.clearTimeout(timeout);
    }
  }

  function renderFolder() {
    const folderIdentity = [folder.firstName, folder.lastName].filter(Boolean).join(' ').trim()
      || folder.identity || '—';
    document.querySelector('#wedof-folder-summary').innerHTML = `
      <div><span>Numéro WEDOF</span><strong>${esc(folder.externalId) || '—'}</strong></div>
      <div><span>Candidat</span><strong>${esc(folderIdentity)}</strong></div>
      <div><span>Coordonnées</span><strong>${esc(folder.email) || '—'}</strong><small>${esc(folder.phone) || '—'}</small></div>
      <div><span>Période WEDOF</span><strong>Du ${fr(folder.dateStart)} au ${fr(folder.dateEnd)}</strong></div>`;
  }

  function buildSearchUrl(query = '') {
    const params = new URLSearchParams({
      q: query,
      email: folder.email || '',
      phone: folder.phone || '',
      first_name: folder.firstName || '',
      last_name: folder.lastName || '',
      date_start: folder.dateStart || '',
      date_end: folder.dateEnd || '',
      limit: '30',
    });
    return `/admin/wedof/matching/manual/enrolments?${params}`;
  }

  function renderResults(items, {automatic = false, autoAssociate = false, total = items.length} = {}) {
    results.innerHTML = '';
    results.setAttribute('aria-busy', 'false');
    if (!items.length) {
      resultsStatus.textContent = automatic
        ? 'Aucun stagiaire correspondant n’a été trouvé automatiquement. Recherchez son nom, son e-mail ou son téléphone.'
        : 'Aucun stagiaire ne correspond à cette recherche.';
      results.innerHTML = '<div class="wedof-empty-search"><strong>Aucun résultat</strong><span>Vérifiez l’orthographe ou essayez avec l’e-mail ou le téléphone.</span></div>';
      return;
    }
    resultsStatus.textContent = `${total} inscription${total > 1 ? 's' : ''} trouvée${total > 1 ? 's' : ''}. Cliquez sur « Associer » en face de la bonne session.`;
    items.forEach(item => {
      const card = document.createElement('article');
      card.className = 'wedof-enrolment-card';
      if (item.session_archived) card.classList.add('is-archived');
      card.innerHTML = `
        <div class="wedof-enrolment-person">
          <span class="wedof-avatar" aria-hidden="true">${esc(initials(item))}</span>
          <div><strong>${esc(identity(item))}</strong><span>${esc(item.email) || 'E-mail non renseigné'}${item.phone ? ` · ${esc(item.phone)}` : ''}</span></div>
        </div>
        <div class="wedof-enrolment-session">
          <span class="wedof-enrolment-kicker">${esc(item.session_training_type) || 'Session locale'}${item.session_archived ? ' · Archivée' : ''}</span>
          <strong>${esc(item.session_name)}</strong>
          <span>Du ${fr(item.session_date_start)} au ${fr(item.session_date_end)}</span>
        </div>
        <span class="wedof-match-reason">${esc(item.match_reason)}</span>
        <button type="button" class="btn btn-blue wedof-associate-button">Associer</button>`;
      card.querySelector('.wedof-associate-button').addEventListener('click', event => {
        chooseEnrolment(item, event.currentTarget);
      });
      results.append(card);
    });
    if (automatic && autoAssociate && total === 1 && items.length === 1 && items[0].exact_identity_match) {
      resultsStatus.textContent = 'Correspondance exacte unique trouvée. Association automatique en cours…';
      const button = results.querySelector('.wedof-associate-button');
      submitAssociation(items[0], button, hasDateMismatch(items[0]));
    }
  }

  async function searchEnrolments(query = '', {automatic = false, autoAssociate = false} = {}) {
    const sequence = ++searchSequence;
    selectedEnrolment = null;
    review.hidden = true;
    results.setAttribute('aria-busy', 'true');
    results.innerHTML = '<div class="wedof-search-loading"><span></span><strong>Recherche dans la base stagiaires…</strong></div>';
    resultsStatus.textContent = 'Recherche en cours…';
    setModalAlert();
    try {
      const payload = await getJson(buildSearchUrl(query), {timeoutMs: 15000});
      if (sequence !== searchSequence) return;
      renderResults(payload.items || [], {
        automatic,
        autoAssociate,
        total: payload.total ?? (payload.items || []).length,
      });
    } catch (error) {
      if (sequence !== searchSequence) return;
      results.setAttribute('aria-busy', 'false');
      results.innerHTML = '';
      resultsStatus.textContent = 'La recherche locale est momentanément indisponible.';
      setModalAlert(error.message, 'error');
    }
  }

  function hasDateMismatch(item) {
    return item.session_date_start !== folder.dateStart || item.session_date_end !== folder.dateEnd;
  }

  function chooseEnrolment(item, button) {
    selectedEnrolment = item;
    form.elements.session_id.value = item.session_id;
    form.elements.trainee_id.value = item.trainee_id;
    form.elements.confirm_date_mismatch.value = '';

    results.querySelectorAll('.wedof-enrolment-card').forEach(card => card.classList.remove('is-selected'));
    button.closest('.wedof-enrolment-card')?.classList.add('is-selected');

    const mismatch = hasDateMismatch(item);
    if (!mismatch && !item.session_archived) {
      submitAssociation(item, button, false);
      return;
    }

    review.hidden = false;
    reviewTitle.textContent = item.session_archived
      ? 'Vérification nécessaire : cette session est archivée'
      : 'Vérification nécessaire : les dates sont différentes';
    reviewTrainee.textContent = identity(item);
    reviewSession.textContent = item.session_name;
    reviewRemoteDates.textContent = `Du ${fr(folder.dateStart)} au ${fr(folder.dateEnd)}`;
    reviewLocalDates.textContent = `Du ${fr(item.session_date_start)} au ${fr(item.session_date_end)}`;
    reviewConfirm.textContent = mismatch ? 'Associer malgré les dates différentes' : 'Associer à cette session archivée';
    review.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  function updateDashboardRow(payload) {
    if (!currentRow) return;
    currentRow.querySelector('[data-local-session]').textContent = payload.session;
    currentRow.querySelector('[data-local-trainee]').textContent = payload.trainee;
    const badge = currentRow.querySelector('[data-local-association-badge]');
    badge.textContent = payload.association;
    badge.className = 'wedof-badge is-neutral';
    currentRow.querySelector('[data-manual-link]')?.closest('.wedof-manual-action')?.remove();
    currentRow.dataset.wedofUnlinked = 'false';
    const counter = document.querySelector('#wedof-unlinked-count');
    if (counter) counter.textContent = payload.unlinked_count;
  }

  async function submitAssociation(item, button, confirmMismatch) {
    form.elements.session_id.value = item.session_id;
    form.elements.trainee_id.value = item.trainee_id;
    form.elements.confirm_date_mismatch.value = confirmMismatch ? '1' : '';
    const previousText = button?.textContent;
    if (button) {
      button.disabled = true;
      button.textContent = 'Association…';
    }
    setModalAlert();
    window.WedofLoading?.forceHide();
    const loadingToken = window.WedofLoading?.show();
    try {
      const payload = await getJson(form.action, {
        timeoutMs: 30000,
        method: 'POST',
        headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        body: new FormData(form),
      });
      updateDashboardRow(payload);
      showPageFeedback(payload.message);
      modal.close();
    } catch (error) {
      setModalAlert(error.message, 'error');
      if (button) {
        button.disabled = false;
        button.textContent = previousText;
      }
    } finally {
      if (loadingToken) window.WedofLoading?.hide(loadingToken);
    }
  }

  async function openManualModal(button) {
    form.reset();
    selectedEnrolment = null;
    currentRow = button.closest('tr');
    searchWasEdited = false;
    review.hidden = true;
    setModalAlert();
    results.innerHTML = '';
    folder = {
      externalId: button.dataset.externalId,
      state: button.dataset.state,
      identity: button.dataset.identity,
      firstName: button.dataset.firstName,
      lastName: button.dataset.lastName,
      email: button.dataset.email,
      phone: button.dataset.phone,
      dateStart: button.dataset.dateStart,
      dateEnd: button.dataset.dateEnd,
    };
    form.elements.external_id.value = folder.externalId;
    renderFolder();
    searchInput.value = [folder.firstName, folder.lastName].filter(Boolean).join(' ').trim() || folder.identity || '';
    liveStatus.textContent = 'Vérification du dossier WEDOF en cours…';
    liveStatus.className = 'wedof-live-status is-loading';
    modal.showModal();

    const initialSearch = searchEnrolments('', {automatic: true});
    const remoteRefresh = getJson(
      `/admin/wedof/matching/manual/folder?external_id=${encodeURIComponent(folder.externalId)}`,
      {timeoutMs: 8000}
    ).then(async detail => {
      folder = {
        ...folder,
        state: detail.state || folder.state,
        firstName: detail.first_name || folder.firstName,
        lastName: detail.last_name || folder.lastName,
        email: detail.email || folder.email,
        phone: detail.phone || folder.phone,
        dateStart: detail.date_start || folder.dateStart,
        dateEnd: detail.date_end || folder.dateEnd,
      };
      renderFolder();
      if (!searchWasEdited) {
        searchInput.value = [folder.firstName, folder.lastName].filter(Boolean).join(' ').trim() || folder.identity || '';
        await searchEnrolments('', {automatic: true, autoAssociate: true});
      }
      liveStatus.textContent = 'Informations WEDOF vérifiées en direct';
      liveStatus.className = 'wedof-live-status is-success';
    }).catch(error => {
      liveStatus.textContent = error.code === 'client_timeout'
        ? 'WEDOF met trop de temps à répondre · dernier instantané utilisé'
        : 'WEDOF indisponible · dernier instantané utilisé';
      liveStatus.className = 'wedof-live-status is-warning';
    });
    await Promise.allSettled([initialSearch, remoteRefresh]);
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-manual-link]');
    if (button) openManualModal(button);
  });

  searchInput.addEventListener('input', () => {
    searchWasEdited = true;
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      searchEnrolments(searchInput.value.trim(), {automatic: false});
    }, 180);
  });

  reviewConfirm.addEventListener('click', () => {
    if (!selectedEnrolment) return;
    submitAssociation(selectedEnrolment, reviewConfirm, hasDateMismatch(selectedEnrolment));
  });
  document.querySelector('#wedof-modal-cancel').addEventListener('click', () => modal.close());
  form.addEventListener('submit', event => event.preventDefault());
  window.addEventListener('pagehide', () => window.WedofLoading?.forceHide());
})();
