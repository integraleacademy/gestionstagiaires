(() => {
  'use strict';
  // Full-width radio cards keep long answers readable on a phone. The hidden
  // select is the existing native grouped-question contract, graded by Flask.
  document.querySelectorAll('[data-mac-question]').forEach(group => {
    const select = group.querySelector('select[data-group-id]');
    if (!select) return;
    const radios = [...group.querySelectorAll('input[type="radio"]')];
    const sync = () => radios.forEach(radio => {
      radio.checked = radio.value === select.value;
      radio.disabled = select.disabled;
    });
    radios.forEach(radio => radio.addEventListener('change', () => {
      if (!radio.checked || select.disabled) return;
      select.value = radio.value;
      select.dispatchEvent(new Event('change', {bubbles: true}));
    }));
    select.addEventListener('change', sync);
    sync();
    // The native player restores a saved response when tracking has connected.
    new MutationObserver(sync).observe(select, {attributes: true, attributeFilter: ['disabled']});
    document.addEventListener('native:progress', sync);
    window.setTimeout(sync, 0);
  });
})();
