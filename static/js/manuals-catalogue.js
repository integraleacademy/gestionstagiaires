(() => {
  'use strict';
  const tools = document.querySelector('[data-catalogue-tools]');
  if (!tools) return;
  const cards = Array.from(document.querySelectorAll('[data-catalogue-card]'));
  const search = tools.querySelector('[data-catalogue-search]');
  const buttons = Array.from(tools.querySelectorAll('[data-category-filter]'));
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/œ/g, 'oe');
  const requested = new URLSearchParams(window.location.search).get('categorie');
  let category = buttons.some(button => button.dataset.categoryFilter === requested) ? requested : '';
  buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.categoryFilter === category)));
  function filter() {
    const terms = normalize(search.value).split(/\s+/).filter(Boolean);
    let count = 0;
    cards.forEach(card => {
      const visible = (!category || card.dataset.category === category)
        && terms.every(term => normalize(card.dataset.search).includes(term));
      card.hidden = !visible;
      if (visible) count++;
    });
    tools.querySelector('[data-catalogue-count]').textContent = `${count} manuel${count === 1 ? '' : 's'}`;
    document.querySelector('[data-catalogue-empty]').hidden = count !== 0;
  }
  buttons.forEach(button => button.addEventListener('click', () => {
    category = button.dataset.categoryFilter;
    buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    filter();
  }));
  search.addEventListener('input', filter);
  tools.hidden = false;
  filter();
})();
