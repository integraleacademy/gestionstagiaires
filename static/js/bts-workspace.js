(() => {
  'use strict';
  const root = document.querySelector('.bts-workspace');
  if (!root) return;
  const cerfaForm = root.querySelector('[data-cerfa-form]');
  if (cerfaForm) {
    let dirty = false;
    const setDirty = () => {
      dirty = true;
      root.querySelector('[data-cerfa-unsaved]')?.removeAttribute('hidden');
      root.querySelectorAll('[data-cerfa-pdf]').forEach(link => link.setAttribute('aria-disabled', 'true'));
    };
    cerfaForm.addEventListener('input', setDirty);
    cerfaForm.addEventListener('change', setDirty);
    root.querySelectorAll('[data-cerfa-pdf]').forEach(link => link.addEventListener('click', event => {
      if (dirty) {
        event.preventDefault();
        cerfaForm.querySelector('button')?.focus();
      }
    }));
    const revealField = () => {
      let fieldId;
      try { fieldId = decodeURIComponent(window.location.hash.slice(1)); } catch { return; }
      const field = document.getElementById(fieldId);
      if (!field || !cerfaForm.contains(field)) return;
      const section = field.closest('details');
      if (section) section.open = true;
      field.scrollIntoView({block: 'center'});
      field.querySelector('input, select')?.focus({preventScroll: true});
    };
    revealField();
    window.addEventListener('hashchange', revealField);
  }
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
    if (form.hasAttribute('data-wedof-search')) return;
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
      window.setTimeout(() => {
        form.querySelectorAll('button:not([type="button"])').forEach(button => {
          button.disabled = true;
          button.dataset.originalLabel = button.textContent;
          button.textContent = 'En cours…';
        });
      }, 0);
    });
  });
  root.querySelectorAll('form[data-wedof-search]').forEach(form => {
    let active = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (active) return;
      active = true;
      const button = form.querySelector('button');
      const message = form.querySelector('[data-search-message]');
      const originalLabel = button.textContent;
      button.disabled = true;
      form.setAttribute('aria-busy', 'true');
      message.textContent = 'Recherche du contrat dans WEDOF…';
      let body = new FormData(form);
      try {
        // Only an explicit submit searches. Results must then be added individually.
        for (let step = 0; step < 25; step++) {
          const response = await fetch(form.getAttribute('action'), {method: 'POST', body, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
          if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('La session a expiré. Rechargez la page pour rechercher le contrat.');
          }
          const result = await response.json();
          message.textContent = result.message || 'Recherche interrompue. Aucun dossier ajouté.';
          if (!response.ok) break;
          if (result.status !== 'running') {
            if (result.redirect_url) window.location.assign(result.redirect_url);
            break;
          }
          body = new FormData(form);
          body.set('action', 'continue');
          body.set('run_id', result.id);
          body.set('revision', String(result.revision));
          await new Promise(resolve => window.setTimeout(resolve, 250));
        }
      } catch (error) {
        message.textContent = error.message || 'Recherche interrompue. Aucun dossier ajouté.';
      } finally {
        active = false;
        button.disabled = false;
        button.textContent = originalLabel;
        form.removeAttribute('aria-busy');
      }
    });
  });
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
