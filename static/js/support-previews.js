/* Small public selections only; no full presentation is loaded by this reader. */
(() => {
  'use strict';
  const section = document.querySelector('[data-support-previews]');
  if (!section) return;
  const groups = Array.from(section.querySelectorAll('[data-preview-group]'));
  const select = section.querySelector('[data-preview-select]');
  if (select) {
    const showGroup = () => groups.forEach(group => {
      group.hidden = group.dataset.previewGroup !== select.value;
    });
    showGroup();
    select.addEventListener('change', showGroup);
    section.querySelector('[data-preview-picker]').hidden = false;
  }
  const dialog = document.querySelector('.sf-preview-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const stage = dialog.querySelector('[data-preview-stage]');
  const caption = dialog.querySelector('#sf-preview-caption');
  const viewport = dialog.querySelector('.sf-preview-viewport');
  const previous = dialog.querySelector('[data-preview-previous]');
  const next = dialog.querySelector('[data-preview-next]');
  const zoom = dialog.querySelector('[data-preview-zoom]');
  let slides = [], index = 0, opener = null;
  const resetZoom = () => {
    viewport.classList.remove('is-zoomed');
    zoom.setAttribute('aria-pressed', 'false');
    zoom.textContent = 'Zoom +';
    viewport.scrollTo(0, 0);
  };
  const render = () => {
    const slide = slides[index];
    const content = slide.querySelector('.sf-slide-frame').cloneNode(true);
    content.querySelectorAll('img').forEach(img => { img.loading = 'eager'; });
    stage.replaceChildren(content);
    caption.textContent = `${slide.dataset.previewCaption} · ${index + 1} / ${slides.length}`;
    previous.disabled = index === 0;
    next.disabled = index === slides.length - 1;
    resetZoom();
  };
  section.querySelectorAll('[data-support-preview]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = link;
      slides = Array.from(link.closest('[data-preview-group]').querySelectorAll('[data-support-preview]'));
      index = slides.indexOf(link);
      render();
      dialog.showModal();
    });
  });
  const move = delta => {
    const target = index + delta;
    if (target < 0 || target >= slides.length) return;
    index = target;
    render();
  };
  previous.addEventListener('click', () => move(-1));
  next.addEventListener('click', () => move(1));
  zoom.addEventListener('click', () => {
    const active = viewport.classList.toggle('is-zoomed');
    zoom.setAttribute('aria-pressed', String(active));
    zoom.textContent = active ? 'Zoom −' : 'Zoom +';
    if (!active) viewport.scrollTo(0, 0);
  });
  dialog.addEventListener('keydown', event => {
    if (viewport.classList.contains('is-zoomed')) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      move(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
  dialog.addEventListener('click', event => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  });
  dialog.addEventListener('close', () => {
    stage.replaceChildren();
    if (opener) opener.focus({preventScroll: true});
  });
})();
