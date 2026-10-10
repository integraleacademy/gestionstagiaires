(() => {
  'use strict';
  const money = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'});
  const errors = document.querySelector('[data-el-errors]');
  if (errors) errors.focus({preventScroll: true});

  const dashboard = document.querySelector('[data-el-dashboard]');
  if (dashboard) {
    const search = dashboard.querySelector('#el-search');
    const filter = dashboard.querySelector('#el-filter');
    const cards = [...dashboard.querySelectorAll('[data-el-group]')];
    const metricLinks = [...dashboard.querySelectorAll('[data-el-state]')];
    const filterForm = dashboard.querySelector('#el-filter-form');
    const reset = dashboard.querySelector('#el-reset-filters');
    const clear = dashboard.querySelector('#el-clear-search');
    const countLabel = dashboard.querySelector('#el-results-count');
    const normalize = text => text.toLocaleLowerCase('fr').normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const labels = {all: 'Tous les états', draft: 'Accès à préparer', waiting: 'En attente d’activation', active: 'Accès activés'};
    const update = (changeUrl = true) => {
      if (!search || !filter) return;
      const query = normalize(search.value.trim());
      const words = query.split(/\s+/).filter(Boolean);
      const matchesQuery = value => words.every(word => normalize(value).includes(word));
      let count = 0;
      cards.forEach(card => {
        const matchedPeople = [...card.querySelectorAll('[data-person-search]')].filter(person => query && matchesQuery(person.dataset.personSearch));
        const textMatches = !query || matchesQuery(card.dataset.search) || matchedPeople.length > 0;
        const stateMatches = filter.value === 'all' || card.dataset.states.split(/\s+/).includes(filter.value);
        card.hidden = !(textMatches && stateMatches);
        if (!card.hidden) count++;
        const detail = card.querySelector('[data-el-matches]');
        if (detail) {
          detail.hidden = matchedPeople.length === 0;
          detail.textContent = matchedPeople.length ? 'Stagiaire' + (matchedPeople.length > 1 ? 's' : '') + ' : ' + matchedPeople.map(person => person.dataset.personName).join(', ') : '';
        }
      });
      metricLinks.forEach(link => {
        const selected = link.dataset.elState === filter.value;
        link.classList.toggle('is-selected', selected);
        if (selected) link.setAttribute('aria-current', 'true'); else link.removeAttribute('aria-current');
      });
      const empty = dashboard.querySelector('#el-no-results');
      if (empty) empty.hidden = count > 0;
      if (countLabel) countLabel.textContent = count + ' résultat' + (count !== 1 ? 's' : '') + (filter.value !== 'all' ? ' · ' + labels[filter.value] : '') + (query ? ' pour « ' + search.value.trim() + ' »' : '');
      if (reset) reset.hidden = filter.value === 'all' && !query;
      if (clear) clear.hidden = !query;
      if (changeUrl && window.history && window.location) {
        const url = new URL(window.location.href);
        if (query) url.searchParams.set('q', search.value.trim()); else url.searchParams.delete('q');
        if (filter.value !== 'all') url.searchParams.set('state', filter.value); else url.searchParams.delete('state');
        window.history.replaceState(null, '', url.pathname + url.search + url.hash);
      }
    };
    if (search && filter) {
      search.addEventListener('input', () => update());
      filter.addEventListener('change', () => update());
      if (filterForm) filterForm.addEventListener('submit', event => { event.preventDefault(); update(); });
      metricLinks.forEach(link => link.addEventListener('click', event => {
        if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault(); filter.value = link.dataset.elState; update();
      }));
      if (reset) reset.addEventListener('click', event => { event.preventDefault(); search.value = ''; filter.value = 'all'; update(); search.focus(); });
      if (clear) clear.addEventListener('click', () => { search.value = ''; update(); search.focus(); });
      update(false);
    }
  }

  const create = document.getElementById('el-create-form');
  if (create) {
    const field = document.getElementById('el-group-name-field');
    const input = field.querySelector('input');
    const update = () => {
      const group = create.querySelector('[name="mode"]:checked').value === 'group';
      field.hidden = !group;
      input.required = group;
      input.disabled = !group;
      const label = document.getElementById('el-create-label');
      if (label) label.textContent = group ? 'Créer mon groupe' : 'Créer mon accès individuel';
    };
    create.addEventListener('change', update); update();
  }

  const roster = document.getElementById('el-roster-form');
  if (roster) {
    const people = document.getElementById('el-learners');
    const add = document.getElementById('el-add');
    const course = document.getElementById('el-course-code');
    const status = document.getElementById('el-save-status');
    const review = document.getElementById('el-review-button');
    const max = Number(roster.dataset.maxLearners) - Number(roster.dataset.lockedCount);
    let dirty = roster.dataset.unsaved === 'true';
    let submitting = false;
    const rows = () => people ? [...people.querySelectorAll('.el-person')] : [];
    const visibleInputs = row => [...row.querySelectorAll('input:not([type="hidden"])')];
    const filled = row => visibleInputs(row).some(input => input.value.trim());
    const showDirty = () => { dirty = true; status.classList.add('is-dirty'); status.textContent = 'Modifications à enregistrer'; };
    const update = () => {
      const list = rows();
      const count = list.filter(filled).length;
      const selected = course.selectedOptions[0];
      const rawPrice = selected ? selected.dataset.price : '';
      const price = rawPrice === '' ? null : Number(rawPrice);
      document.getElementById('el-count').textContent = String(count);
      document.getElementById('el-total').textContent = price === null ? 'Tarif à définir' : price === 0 ? 'Gratuit' : money.format(price * count / 100);
      const counter = document.getElementById('el-roster-count');
      if (counter) counter.textContent = count + ' à préparer';
      if (add) { add.disabled = list.length >= max; add.title = add.disabled ? 'Ce groupe peut contenir jusqu’à 100 stagiaires.' : ''; }
      review.disabled = count === 0 || roster.dataset.conflict === 'true' || roster.dataset.pendingDeletion === 'true';
      const seen = new Set();
      list.forEach((row, index) => {
        row.querySelector('.el-row-number').textContent = String(index + 1);
        const inputs = visibleInputs(row);
        const hasIdentity = Boolean(row.querySelector('[name="learner_id"]').value);
        const active = filled(row) || hasIdentity;
        inputs.forEach(input => { input.required = active; });
        const email = row.querySelector('[name="email"]');
        const value = email.value.trim().toLowerCase();
        email.setCustomValidity(value && seen.has(value) ? 'Cette adresse figure déjà dans la liste.' : '');
        if (value) seen.add(value);
      });
    };
    if (add && people) add.addEventListener('click', () => {
      if (rows().length >= max) return;
      const row = people.firstElementChild.cloneNode(true);
      row.querySelectorAll('input').forEach(input => { input.value = ''; input.setCustomValidity(''); input.required = false; });
      people.append(row); showDirty(); update(); row.querySelector('[name="last_name"]').focus();
    });
    if (people) people.addEventListener('click', event => {
      const button = event.target.closest('.el-remove');
      if (!button) return;
      const row = button.closest('.el-person');
      if (rows().length > 1) row.remove();
      else row.querySelectorAll('input').forEach(input => { input.value = ''; input.setCustomValidity(''); input.required = false; });
      showDirty(); update();
    });
    roster.addEventListener('input', () => { showDirty(); update(); });
    roster.addEventListener('change', () => { showDirty(); update(); });
    roster.addEventListener('submit', event => {
      update();
      if (!roster.checkValidity()) { event.preventDefault(); roster.reportValidity(); return; }
      submitting = true;
      status.classList.remove('is-dirty'); status.textContent = 'Enregistrement en cours…';
      // Keep submit buttons enabled: the clicked name=next value belongs in the request.
    });
    window.addEventListener('beforeunload', event => {
      if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; }
    });
    document.querySelectorAll('[data-el-delete-form]').forEach(form => form.addEventListener('submit', () => { submitting = true; }));
    if (dirty) showDirty();
    update();
  }

  const status = document.querySelector('[data-el-status]');
  if (status) {
    const signature = value => JSON.stringify([value.status, value.payment_status, value.invoice_status, value.active, value.mail_sent, value.payment_url, value.payment_link_status]);
    let previous = null;
    try { previous = status.dataset.elInitial ? signature(JSON.parse(status.dataset.elInitial)) : null; } catch (_) { /* A manual refresh remains available. */ }
    let ticks = 0;
    const poll = async () => {
      if (++ticks > 180) return;
      if (!document.hidden) {
        try {
          const response = await fetch(status.dataset.elStatus, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
          if (response.ok && !response.redirected) {
            const current = signature(await response.json());
            if (previous !== null && current !== previous) { location.reload(); return; }
          }
        } catch (_) { /* Preserve the page and retry after a transient network error. */ }
      }
      window.setTimeout(poll, 10000);
    };
    poll();
  }
})();
