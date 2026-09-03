(() => {
  const pageTabs = [...document.querySelectorAll('[data-wedof-page-tab]')];
  const pagePanels = [...document.querySelectorAll('[data-wedof-page-panel]')];

  function showPageSection(section, {updateUrl = true} = {}) {
    if (!pageTabs.some(tab => tab.dataset.wedofPageTab === section)) return;
    pageTabs.forEach(tab => {
      const active = tab.dataset.wedofPageTab === section;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
    });
    pagePanels.forEach(panel => {
      panel.hidden = panel.dataset.wedofPagePanel !== section;
    });
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('section', section);
      window.history.replaceState({}, '', url);
    }
  }

  if (pageTabs.length && pagePanels.length) {
    const requestedSection = new URLSearchParams(window.location.search).get('section');
    const initialSection = pageTabs.some(tab => tab.dataset.wedofPageTab === requestedSection)
      ? requestedSection
      : (pageTabs.find(tab => tab.classList.contains('is-active'))?.dataset.wedofPageTab || 'consumption');
    showPageSection(initialSection, {updateUrl: false});

    pageTabs.forEach((tab, index) => {
      tab.addEventListener('click', () => showPageSection(tab.dataset.wedofPageTab));
      tab.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let nextIndex = index;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = pageTabs.length - 1;
        if (event.key === 'ArrowRight') nextIndex = (index + 1) % pageTabs.length;
        if (event.key === 'ArrowLeft') nextIndex = (index - 1 + pageTabs.length) % pageTabs.length;
        pageTabs[nextIndex].focus();
        showPageSection(pageTabs[nextIndex].dataset.wedofPageTab);
      });
    });
  }

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

  function show(filter, {scroll = true} = {}) {
    const matcher = rowMatches[filter] || rowMatches.accepted;
    let visible = 0;
    rows.forEach(row => {
      const matches = matcher(row);
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    counters.forEach(counter => {
      const active = counter.dataset.wedofCounter === filter;
      counter.classList.toggle('is-active', active);
      counter.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    if (empty) empty.hidden = visible !== 0;
    if (resultCount) resultCount.textContent = `${visible} dossier${visible > 1 ? 's' : ''}`;
    if (scroll) table?.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }

  counters.forEach(counter => {
    counter.setAttribute('aria-pressed', 'false');
    counter.addEventListener('click', () => show(counter.dataset.wedofCounter));
  });

  const requested = new URLSearchParams(window.location.search).get('tab');
  if (requested && rowMatches[requested]) {
    show(requested, {scroll: false});
  } else {
    show('accepted', {scroll: false});
  }
})();
