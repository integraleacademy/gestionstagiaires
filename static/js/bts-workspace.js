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
    if (form.hasAttribute('data-wedof-sync')) return;
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
  root.querySelectorAll('form[data-wedof-sync]').forEach(form => {
    let active = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (active) return;
      active = true;
      const button = form.querySelector('button');
      const message = form.querySelector('[data-sync-message]');
      const progress = form.querySelector('[data-sync-progress]');
      button.disabled = true;
      form.setAttribute('aria-busy', 'true');
      progress.hidden = false;
      progress.removeAttribute('value');
      message.textContent = 'Connexion à WEDOF et récupération des contrats AKTO…';
      let body = new FormData(form);
      let complete = false;
      try {
        // Only this explicit submit starts the loop. GET/page loads never contact WEDOF.
        for (let step = 0; step < 150; step++) {
          // The hidden field named "action" masks form.action in the DOM.
          const response = await fetch(form.getAttribute('action'), {method: 'POST', body, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
          if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) {
            throw new Error('La session a expiré. Rechargez la page pour reprendre.');
          }
          const result = await response.json();
          message.textContent = result.message || 'Synchronisation interrompue. Vous pouvez reprendre.';
          if (!response.ok || result.status !== 'running') {
            complete = result.status === 'complete';
            break;
          }
          if (result.phase === 'details') {
            progress.max = Math.max(1, result.details_total);
            progress.value = result.details_done;
          }
          body = new FormData(form);
          body.set('action', 'continue');
          body.set('run_id', result.id);
          body.set('revision', String(result.revision));
          await new Promise(resolve => window.setTimeout(resolve, 300));
        }
      } catch (error) {
        message.textContent = error.message || 'Connexion interrompue. Les contrats enregistrés sont conservés.';
      } finally {
        active = false;
        button.disabled = false;
        button.textContent = complete ? 'Synchroniser AKTO via WEDOF' : 'Poursuivre la synchronisation';
        form.querySelector('[name="action"]').value = complete ? 'start' : 'resume';
        form.removeAttribute('aria-busy');
        progress.hidden = true;
      }
      if (complete) window.location.reload();
    });
  });
  // The dashboard's running label comes from the server-side sync lock.
  // Reloading this cache-only GET never launches another AKTO request.
  // Dossier forms are never auto-reloaded, and an active search is preserved.
  const syncButton = root.querySelector('.ws-list-card form[action$="/synchroniser"] button');
  if (syncButton && syncButton.textContent.includes('Synchronisation en cours')) {
    const checkRefresh = () => {
      const editing = document.activeElement && document.activeElement.matches('input, textarea, select');
      if (document.visibilityState !== 'visible' || editing) {
        window.setTimeout(checkRefresh, 15000);
        return;
      }
      window.location.reload();
    };
    window.setTimeout(checkRefresh, 15000);
  }
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
