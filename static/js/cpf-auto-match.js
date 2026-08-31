(() => {
  function initCpfAutoMatch() {
    const root = document.querySelector('[data-cpf-auto-match]');
    if (!root || root.dataset.readOnly === 'true' || root.dataset.cpfAutoMatchInitialized === 'true') return;
    root.dataset.cpfAutoMatchInitialized = 'true';

  const status = root.querySelector('[data-cpf-match-status]');
  const message = root.querySelector('[data-cpf-match-message]');
  const retry = root.querySelector('[data-cpf-match-retry]');
  const liveSearch = root.querySelector('[data-cpf-match-live]');
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

  function setStatus(tone, text) {
    status.className = `cpf-match-status ${tone === 'loading' ? 'is-loading' : `is-${tone}`}`;
    message.textContent = text;
    retry.disabled = tone === 'loading';
    liveSearch.disabled = tone === 'loading';
  }

  function refreshAfterAssociation(redirectUrl) {
    try {
      const current = new URL(window.location.href);
      const target = new URL(redirectUrl || current.href, current.href);
      const samePage = target.origin === current.origin
        && target.pathname === current.pathname
        && target.search === current.search;
      if (!samePage) {
        window.location.assign(target.href);
        return;
      }
      // Changer uniquement l'ancre ne recharge pas la fiche : les suggestions
      // et le bouton resteraient donc figés malgré l'association enregistrée.
      window.history.replaceState(null, '', target.href);
    } catch (_error) {
      // Une URL de redirection absente ou invalide ne doit pas empêcher le
      // rechargement de l'état désormais enregistré côté serveur.
    }
    window.location.reload();
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
      button.textContent = 'Dossier associé';
      suggestions.querySelectorAll('button').forEach(item => { item.disabled = true; });
      window.setTimeout(() => refreshAfterAssociation(payload.redirect_url), 300);
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      setStatus('error', error.message);
    } finally {
      running = false;
    }
  }

  async function search(source = 'cache') {
    if (running) return;
    running = true;
    suggestions.innerHTML = '';
    const isLive = source === 'wedof';
    setStatus(
      'loading',
      isLive
        ? 'Recherche WEDOF en cours à partir du nom, des coordonnées et des dates de formation…'
        : 'Comparaison avec les derniers dossiers présents dans le cache WEDOF…',
    );
    try {
      const payload = await post(isLive ? root.dataset.liveSearchUrl : root.dataset.searchUrl);
      if (payload.status === 'associated') {
        setStatus('success', payload.message || 'Le bon dossier CPF a été associé automatiquement.');
        window.setTimeout(() => refreshAfterAssociation(payload.redirect_url), 300);
        return;
      }
      const items = Array.isArray(payload.candidates) ? payload.candidates : [];
      renderCandidates(items);
      setStatus(items.length ? 'success' : 'neutral', payload.message);
    } catch (error) {
      setStatus('error', error.message);
    } finally {
      running = false;
    }
  }

  retry.addEventListener('click', () => search('cache'));
  liveSearch.addEventListener('click', () => search('wedof'));
  suggestions.addEventListener('click', event => {
    const button = event.target.closest('[data-cpf-associate]');
    if (button) associate(button);
  });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCpfAutoMatch, {once: true});
  } else {
    initCpfAutoMatch();
  }
})();
