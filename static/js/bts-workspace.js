(() => {
  'use strict';
  const root = document.querySelector('.bts-workspace');
  if (!root) return;
  let opener = null;
  root.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => {
      const dialog = document.getElementById(button.dataset.openDialog);
      if (!(dialog instanceof HTMLDialogElement)) return;
      opener = button;
      dialog.showModal();
      const firstField = dialog.querySelector('input:not([type="hidden"]), select, textarea');
      if (firstField) firstField.focus();
    });
  });
  root.querySelectorAll('dialog').forEach(dialog => {
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('close', () => {
      if (opener && opener.isConnected) opener.focus();
      opener = null;
    });
  });
  root.querySelectorAll('form[method="post"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.dataset.submitting === 'true') {
        event.preventDefault();
        return;
      }
      if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        return;
      }
      form.dataset.submitting = 'true';
      form.setAttribute('aria-busy', 'true');
      // All persisted values live in inputs; disable the submit action only
      // after the browser has captured the submission, preventing double clicks.
      window.setTimeout(() => {
        form.querySelectorAll('button:not([type="button"])').forEach(button => {
          button.disabled = true;
          button.dataset.originalLabel = button.textContent;
          button.textContent = 'En cours…';
        });
      }, 0);
    });
  });
  // Restore forms after a Back navigation through the browser's page cache.
  window.addEventListener('pageshow', () => {
    root.querySelectorAll('form[data-submitting="true"]').forEach(form => {
      delete form.dataset.submitting;
      form.removeAttribute('aria-busy');
      form.querySelectorAll('button[data-original-label]').forEach(button => {
        button.disabled = false;
        button.textContent = button.dataset.originalLabel;
        delete button.dataset.originalLabel;
      });
    });
  });
})();
