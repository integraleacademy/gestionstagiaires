(() => {
  const root = document.querySelector('[data-cpf-auto-match]');
  if (!root || root.dataset.readOnly === 'true') return;

  const status = root.querySelector('[data-cpf-match-status]');
  const message = root.querySelector('[data-cpf-match-message]');
  const retry = root.querySelector('[data-cpf-match-retry]');
  const suggestions = root.querySelector('[data-cpf-suggestions]');
  let running = false;

  const escapeHtml = value => String(value || '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[character]));
  const formatDate = value => {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return match ? `${match[3]}/${match[2]}/${match[1]}` : '—';
  };
  const stateLabel = value => ({
    accepted: 'Accepté',
    inTraining: 'En formation',
    serviceDoneDeclared: 'Service fait déclaré',
    serviceDoneValidated: 'Service fait validé',
  }[value] || value || 'Statut non communiqué');

  function setStatus(tone, text, showRetry = false) {
    status.className = `cpf-match-status ${tone === 'loading' ? 'is-loading' : `is-${tone}`}`;
    message.textContent = text;
    retry.hidden = !showRetry;
  }

  async function post(url, body = null) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(url, {
        method: 'POST',
        body,
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
        },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message || 'La recherche WEDOF n’a pas pu aboutir.');
      }
      return payload;
    } catch (error) {
      if (error.name === 'AbortError') {
        throw new Error('La recherche WEDOF prend trop de temps. Relancez-la dans quelques instants.');
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function renderCandidates(items) {
    suggestions.innerHTML = items.map(item => {
      const fullName = [item.first_name, item.last_name].filter(Boolean).join(' ').trim() || 'Identité non communiquée';
      const training = item.training_title || 'Formation non communiquée';
      const matches = (item.match_reasons || [])
        .map(label => `<span>${escapeHtml(label)}</span>`).join('');
      const warnings = (item.mismatches || [])
        .map(label => `<span class="is-warning">${escapeHtml(label)}</span>`).join('');
      const conflict = item.linked_elsewhere
        ? '<div class="cpf-suggestion__conflict">Ce dossier est déjà associé à une autre inscription.</div>'
        : '';
      const button = item.can_associate
        ? `<button class="btn btn-primary" type="button" data-cpf-associate="${escapeHtml(item.external_id)}">Associer ce dossier</button>`
        : '<button class="btn btn-outline" type="button" disabled>Déjà associé ailleurs</button>';
      return `<article class="cpf-suggestion">
        <div>
          <div class="cpf-suggestion__top">
            <strong>Dossier ${escapeHtml(item.external_id)}</strong>
            <span class="cpf-suggestion__state">${escapeHtml(stateLabel(item.state))}</span>
          </div>
          <div class="cpf-suggestion__meta">
            <span>${escapeHtml(fullName)}</span>
            <span>${escapeHtml(item.email || 'E-mail non communiqué')}</span>
            <span>${escapeHtml(item.phone || 'Téléphone non communiqué')}</span>
            <span>${escapeHtml(training)}</span>
            <span>Du ${formatDate(item.start_date)} au ${formatDate(item.end_date)}</span>
          </div>
          <div class="cpf-suggestion__matches">${matches}${warnings}</div>
          ${conflict}
        </div>
        ${button}
      </article>`;
    }).join('');
  }

  async function associate(button) {
    if (running) return;
    running = true;
    const externalId = button.dataset.cpfAssociate || '';
    const original = button.textContent;
    button.disabled = true;
    button.textContent = 'Association en cours…';
    setStatus('loading', `Vérification finale du dossier ${externalId}…`);
    try {
      const body = new URLSearchParams({external_id: externalId});
      const payload = await post(root.dataset.associateUrl, body);
      setStatus('success', payload.message || 'Dossier CPF associé.');
      suggestions.querySelectorAll('button').forEach(item => { item.disabled = true; });
      window.setTimeout(() => window.location.assign(payload.redirect_url), 500);
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      setStatus('error', error.message, true);
    } finally {
      running = false;
    }
  }

  async function search() {
    if (running) return;
    running = true;
    suggestions.innerHTML = '';
    setStatus('loading', 'Comparaison de l’e-mail, du téléphone, de l’identité et des dates avec WEDOF…');
    try {
      const payload = await post(root.dataset.searchUrl);
      if (payload.status === 'associated') {
        setStatus('success', payload.message || 'Le bon dossier CPF a été associé automatiquement.');
        window.setTimeout(() => window.location.assign(payload.redirect_url), 500);
        return;
      }
      const items = Array.isArray(payload.candidates) ? payload.candidates : [];
      renderCandidates(items);
      setStatus('neutral', payload.message, true);
    } catch (error) {
      setStatus('error', error.message, true);
    } finally {
      running = false;
    }
  }

  retry.addEventListener('click', search);
  suggestions.addEventListener('click', event => {
    const button = event.target.closest('[data-cpf-associate]');
    if (button) associate(button);
  });
  search();
})();
