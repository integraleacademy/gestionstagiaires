(() => {
  const dialog = document.querySelector('.manual-gallery-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const links = [...document.querySelectorAll('[data-manual-preview]')];
  const image = dialog.querySelector('img');
  const caption = dialog.querySelector('[data-gallery-caption]');
  const counter = dialog.querySelector('[data-gallery-count]');
  const previous = dialog.querySelector('[data-gallery-previous]');
  const next = dialog.querySelector('[data-gallery-next]');
  let index = 0;
  let opener;

  const display = value => {
    index = (value + links.length) % links.length;
    const link = links[index];
    image.src = link.href;
    image.alt = link.querySelector('img').alt;
    caption.textContent = link.dataset.previewCaption || image.alt;
    counter.textContent = `${index + 1} / ${links.length}`;
    previous.hidden = next.hidden = links.length < 2;
  };
  links.forEach((link, position) => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = link;
      display(position);
      dialog.showModal();
    });
  });
  previous.addEventListener('click', () => display(index - 1));
  next.addEventListener('click', () => display(index + 1));
  dialog.addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      display(index + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
  });
  dialog.addEventListener('close', () => opener?.focus());
})();
