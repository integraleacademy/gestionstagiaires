(() => {
  const tabs = [...document.querySelectorAll('[data-wedof-tab]')];
  const counters = [...document.querySelectorAll('[data-wedof-counter]')];
  const rows = [...document.querySelectorAll('[data-wedof-panel]')];
  const empty = document.querySelector('[data-wedof-filter-empty]');
  const table = document.querySelector('.wedof-preview-table-wrap');
  const resultCount = document.querySelector('#wedof-visible-results');
  if (!rows.length && !empty) return;

  const rowMatches = {
    accepted: row => row.dataset.wedofPanel === 'accepted',
    training: row => row.dataset.wedofPanel === 'training',
    service: row => row.dataset.wedofPanel === 'service',
    anomaly: row => row.dataset.wedofPanel === 'anomaly',
    planned: row => row.dataset.wedofPlanned === 'true',
    invoiced: row => row.dataset.wedofInvoiced === 'true',
  };

  function show(filter, source, {scroll = true} = {}) {
    const matcher = rowMatches[filter] || rowMatches.accepted;
    let visible = 0;
    rows.forEach(row => {
      const matches = matcher(row);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    tabs.forEach(tab => {
      const active = source === 'tab' && tab.dataset.wedofTab === filter;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    });
    counters.forEach(counter => {
      const active = source === 'counter' && counter.dataset.wedofCounter === filter;
      counter.classList.toggle('is-active', active);
      counter.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (empty) empty.hidden = visible !== 0;
    if (resultCount) resultCount.textContent = `${visible} dossier${visible > 1 ? 's' : ''}`;
    if (scroll) table?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => show(tab.dataset.wedofTab, 'tab'));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const current = tabs.indexOf(tab);
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = tabs[(current + direction + tabs.length) % tabs.length];
      next.focus();
      show(next.dataset.wedofTab, 'tab');
    });
  });
  counters.forEach(counter => {
    counter.setAttribute('aria-pressed', 'false');
    counter.addEventListener('click', () => show(counter.dataset.wedofCounter, 'counter'));
  });

  const requested = new URLSearchParams(window.location.search).get('tab');
  if (requested && rowMatches[requested]) {
    show(requested, ['accepted', 'training', 'service', 'anomaly'].includes(requested) ? 'tab' : 'counter', {scroll: false});
  } else {
    show('accepted', 'tab', {scroll: false});
  }
})();
