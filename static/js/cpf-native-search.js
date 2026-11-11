(() => {
  function init() {
    const root = document.querySelector('[data-cpf-native-search]');
    if (!root || root.dataset.initialized) return;
    root.dataset.initialized = 'true';
    const status = root.querySelector('[data-native-status]');
    const message = root.querySelector('[data-native-message]');
    const searchButton = root.querySelector('[data-native-search]');
    const resultBox = root.querySelector('[data-native-results]');
    const candidates = root.querySelector('[data-native-candidates]');
    const queryForm = root.querySelector('[data-native-query]');
    const pagination = root.querySelector('[data-native-pagination]');
    const notice = root.querySelector('[data-native-notice]');
    let busy = false, csrf = '', query = '', page = 1, pages = 1, associated = false;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
    const date = value => {
      const parts = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
      return parts ? `${parts[3]}/${parts[2]}/${parts[1]}` : 'Non communiquée';
    };
    function state(tone, text) {
      status.className = `cpf-match-status is-${tone}`;
      message.textContent = text;
    }
    function lock(value) {
      busy = value;
      root.setAttribute('aria-busy', String(value));
      root.querySelectorAll('button').forEach(button => {
        button.disabled = value || associated || button.dataset.unavailable === 'true';
      });
    }
    async function request(url, body) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch(url, {
          method: body ? 'POST' : 'GET', body, signal: controller.signal,
          headers: {Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        });
        const payload = await response.json().catch(() => null);
        if (!payload) throw new Error('La session a peut-être expiré. Actualisez la fiche puis réessayez.');
        if (!response.ok || payload.ok === false) throw new Error(payload.message || 'La recherche n’a pas abouti. Réessayez.');
        return payload;
      } catch (error) {
        if (error.name === 'AbortError') throw new Error('La recherche prend trop de temps. Vous pouvez la relancer.');
        throw error;
      } finally { clearTimeout(timeout); }
    }
    async function refreshPanel() {
      state('success', 'Dossier CPF associé. Mise à jour du suivi…');
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch(root.dataset.refreshUrl, {headers: {Accept: 'text/html'}, signal: controller.signal});
        if (!response.ok) throw new Error();
        const document = new DOMParser().parseFromString(await response.text(), 'text/html');
        const updated = document.querySelector('#cpfTracking');
        if (!updated || updated.querySelector('[data-cpf-native-search]')) throw new Error();
        updated.open = true;
        root.closest('#cpfTracking').replaceWith(updated);
      } catch (_error) {
        state('success', 'Le dossier CPF est associé. Actualisez la fiche pour afficher le suivi.');
        notice.hidden = false;
        notice.innerHTML = `<a class="btn btn-outline" href="${escape(root.dataset.refreshUrl)}#cpfTracking">Actualiser le suivi CPF</a>`;
      } finally { clearTimeout(timeout); }
    }
    function render(payload) {
      csrf = payload.csrf;
      page = payload.page;
      pages = payload.pages;
      resultBox.hidden = false;
      root.querySelector('[data-native-count]').textContent = `${payload.total} dossier${payload.total > 1 ? 's' : ''} trouvé${payload.total > 1 ? 's' : ''}`;
      candidates.innerHTML = payload.candidates.map(item => {
        const name = [item.first_name, item.last_name].filter(Boolean).join(' ');
        const checks = item.checks.map(check => `<span class="${check.matches === true ? '' : 'is-warning'}">${escape(check.label)}</span>`).join('');
        const action = item.can_associate ? `<form data-native-associate action="${escape(item.associate_url)}" class="cpf-native-associate">
          <label><input type="checkbox" name="verified" value="yes" required> J’ai vérifié le dossier et le stagiaire.</label>
          ${item.confirm_dates ? '<label><input type="checkbox" name="confirm_date_mismatch" value="1" required> Je confirme les dates différentes ou la session archivée.</label>' : ''}
          <button class="btn btn-primary cpf-match-live" type="submit">Associer ce dossier</button>
        </form>` : `<div class="cpf-suggestion__conflict">${escape(item.linked ? 'Ce dossier possède déjà une association.' : item.issues.join(' ') || 'L’association nécessite qu’Intégrale EDOF soit actif.')}</div>`;
        return `<article class="cpf-suggestion"><div>
          <div class="cpf-suggestion__top"><strong>${escape(name)}</strong><span class="cpf-suggestion__state">${escape(item.state)}</span></div>
          <div class="cpf-suggestion__meta"><span>Dossier n° ${escape(item.folder_id)}</span><span>${escape(item.title)}</span><span>Du ${date(item.session_start_date)} au ${date(item.session_end_date)}</span></div>
          <div class="cpf-suggestion__matches">${checks}</div>
        </div>${action}</article>`;
      }).join('');
      pagination.hidden = pages <= 1;
      root.querySelector('[data-native-page]').textContent = `${page} / ${pages}`;
      root.querySelector('[data-native-previous]').dataset.unavailable = String(page <= 1);
      root.querySelector('[data-native-next]').dataset.unavailable = String(page >= pages);
      state(payload.total ? 'success' : 'neutral', payload.message);
      notice.hidden = payload.synced && payload.active;
      notice.textContent = !payload.synced ? 'La première synchronisation doit être effectuée dans Intégrale EDOF.' : !payload.active ? 'Intégrale EDOF doit être actif pour enregistrer une association.' : '';
    }
    async function search(automatic = false, targetPage = 1) {
      if (busy || associated) return;
      lock(true);
      notice.hidden = true;
      state('loading', 'Recherche des dossiers et comparaison de l’identité et des dates…');
      try {
        const url = new URL(root.dataset.searchUrl, window.location.href);
        url.searchParams.set('q', query);
        url.searchParams.set('page', targetPage);
        const payload = await request(url);
        csrf = payload.csrf;
        if (automatic && payload.active) {
          state('loading', 'Vérification des correspondances et de l’association…');
          const match = await request(root.dataset.matchUrl, new URLSearchParams({csrf}));
          if (match.status === 'associated') {
            associated = true;
            await refreshPanel();
            return;
          }
        }
        render(payload);
      } catch (error) { state('error', error.message); }
      finally { lock(false); }
    }
    searchButton.addEventListener('click', () => {
      query = '';
      queryForm.elements.q.value = '';
      search(true);
    });
    queryForm.addEventListener('submit', event => {
      event.preventDefault();
      query = queryForm.elements.q.value.trim();
      search(false);
    });
    root.querySelector('[data-native-previous]').addEventListener('click', () => search(false, page - 1));
    root.querySelector('[data-native-next]').addEventListener('click', () => search(false, page + 1));
    candidates.addEventListener('submit', async event => {
      const form = event.target.closest('[data-native-associate]');
      if (!form) return;
      event.preventDefault();
      if (busy || associated) return;
      lock(true);
      state('loading', 'Association du dossier en cours…');
      try {
        const body = new URLSearchParams(new FormData(form));
        body.set('csrf', csrf);
        body.set('session_id', root.dataset.sessionId);
        body.set('trainee_id', root.dataset.traineeId);
        await request(form.action, body);
        associated = true;
        await refreshPanel();
      } catch (error) { state('error', error.message); }
      finally { lock(false); }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
