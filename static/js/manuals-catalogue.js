(() => {
  'use strict';
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/œ/g, 'oe');
  document.querySelectorAll('[data-catalogue]').forEach(catalogue => {
    const tools = catalogue.querySelector('[data-catalogue-tools]');
    if (!tools) return;
    const cards = Array.from(catalogue.querySelectorAll('[data-catalogue-card]'));
    const groups = Array.from(catalogue.querySelectorAll('[data-catalogue-group]'));
    const search = tools.querySelector('[data-catalogue-search]');
    const buttons = Array.from(tools.querySelectorAll('[data-category-filter]'));
    const parameter = catalogue.dataset.catalogueParam || 'categorie';
    const requested = new URLSearchParams(window.location.search).get(parameter);
    const unit = catalogue.dataset.catalogueUnit || 'manuel';
    let category = buttons.some(button => button.dataset.categoryFilter === requested) ? requested : '';

    function countLabel(count) {
      return `${count} ${unit}${count === 1 ? '' : 's'}`;
    }

    function filter() {
      const terms = normalize(search.value).split(/\s+/).filter(Boolean);
      let count = 0;
      cards.forEach(card => {
        const visible = (!category || card.dataset.category === category)
          && terms.every(term => normalize(card.dataset.search).includes(term));
        card.hidden = !visible;
        if (visible) count++;
      });
      groups.forEach(group => {
        const visibleCount = Array.from(group.querySelectorAll('[data-catalogue-card]')).filter(card => !card.hidden).length;
        group.hidden = visibleCount === 0;
        group.querySelector('[data-category-count]').textContent = countLabel(visibleCount);
      });
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.categoryFilter === category)));
      tools.querySelector('[data-catalogue-count]').textContent = countLabel(count);
      catalogue.querySelector('[data-catalogue-empty]').hidden = count !== 0;
    }

    buttons.forEach(button => button.addEventListener('click', () => {
      category = button.dataset.categoryFilter;
      const url = new URL(window.location.href);
      if (category) url.searchParams.set(parameter, category);
      else url.searchParams.delete(parameter);
      window.history.replaceState(null, '', url);
      filter();
    }));
    search.addEventListener('input', filter);
    search.addEventListener('keydown', event => {
      // Searching inside the order form must not submit the customer's basket.
      if (event.key === 'Enter') event.preventDefault();
    });
    catalogue.addEventListener('catalogue:reveal', event => {
      category = event.detail?.category || '';
      search.value = '';
      filter();
    });
    tools.hidden = false;
    filter();
  });
})();
