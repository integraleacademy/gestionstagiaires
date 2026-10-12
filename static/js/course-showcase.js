(() => {
  const dialog = document.querySelector('.cs-lightbox');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const preview = dialog.querySelector('img');
  const caption = dialog.querySelector('p');
  let opener;
  document.querySelectorAll('[data-course-image]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = link;
      preview.src = link.href;
      preview.alt = link.querySelector('img').alt;
      caption.textContent = preview.alt;
      dialog.showModal();
    });
  });
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => { if (opener) opener.focus(); });
})();
