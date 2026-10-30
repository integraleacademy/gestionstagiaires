(() => {
  'use strict';
  const form = document.querySelector('[data-desp-project-form]');
  if (!form) return;
  const accordion = form.closest('details');
  if (accordion?.querySelector('.desp-project-feedback')) accordion.open = true;
  const status = form.querySelector('[role="status"]');
  const button = form.querySelector('button[type="submit"]');
  const maxBytes = Number(form.dataset.maxBytes);
  const allowed = new Set(['pdf', 'doc', 'docx', 'ppt', 'pptx', 'odt', 'odp']);
  const validate = () => {
    let bytes = 0, count = 0, error = '';
    form.querySelectorAll('[data-project-slot]').forEach(slot => {
      const input = slot.querySelector('input[type="file"]');
      const file = input.files[0];
      const remove = slot.querySelector('input[type="checkbox"]');
      if (file) {
        bytes += file.size;
        count += 1;
        if (!allowed.has(file.name.split('.').pop().toLowerCase())) error = 'Choisissez un document PDF, Word, PowerPoint ou OpenDocument.';
        if (!file.size) error = 'Un document est vide. Choisissez un fichier contenant votre projet.';
      } else if (!remove?.checked && Number(slot.dataset.existingBytes)) {
        bytes += Number(slot.dataset.existingBytes);
        count += 1;
      }
    });
    if (bytes > maxBytes) error = 'Le total de vos documents dépasse 15 Mo. Réduisez ou compressez vos fichiers avant de les déposer à nouveau.';
    status.textContent = error || `${count} document${count > 1 ? 's' : ''} · Total après enregistrement : ${(bytes / 1000000).toLocaleString('fr-FR', {maximumFractionDigits: 2})} Mo / 15 Mo.`;
    status.classList.toggle('is-error', Boolean(error));
    button.disabled = Boolean(error);
    return !error;
  };
  form.addEventListener('change', event => {
    const slot = event.target.closest('[data-project-slot]');
    if (slot) {
      const file = slot.querySelector('input[type="file"]');
      const remove = slot.querySelector('input[type="checkbox"]');
      if (event.target === file && file.files.length && remove) remove.checked = false;
      if (event.target === remove && remove.checked) file.value = '';
    }
    validate();
  });
  form.addEventListener('submit', event => {
    if (!validate()) {
      event.preventDefault();
      return;
    }
    button.disabled = true;
    button.textContent = 'Enregistrement en cours…';
    form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    button.textContent = 'Enregistrer mes documents';
    form.removeAttribute('aria-busy');
    validate();
  });
  validate();
})();
