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
    if (form.matches('[data-wedof-search], [data-candidate-search], [data-opco-submit], [data-contract-settings]')) return;
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
  const candidateForm = root.querySelector('[data-candidate-search]');
  if (candidateForm) {
    const field = candidateForm.querySelector('[name="q"]');
    const results = root.querySelector('#candidate-results');
    const template = root.querySelector('[data-candidate-template]');
    const message = candidateForm.querySelector('[data-candidate-message]');
    let timer, controller, sequence = 0;
    const search = async () => {
      const current = ++sequence;
      controller?.abort();
      controller = new AbortController();
      results.replaceChildren();
      if (field.value.trim().length < 2) {
        message.textContent = 'Saisissez au moins deux caractères.';
        return;
      }
      message.textContent = 'Recherche dans les inscriptions BTS…';
      try {
        const response = await fetch(candidateForm.action, {method: 'POST', body: new FormData(candidateForm),
          credentials: 'same-origin', headers: {Accept: 'application/json'}, signal: controller.signal});
        if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Rechargez la page pour rétablir votre session.');
        const data = await response.json();
        if (current !== sequence) return;
        if (!response.ok) throw new Error(data.error || 'La recherche est indisponible.');
        for (const person of data.items) {
          const fragment = template.content.cloneNode(true);
          fragment.querySelector('[name="candidate_id"]').value = person.id;
          fragment.querySelector('[data-candidate-name]').textContent = `${person.prenom} ${person.nom}`;
          fragment.querySelector('[data-candidate-detail]').textContent = [person.numero_dossier, person.email, person.bts, person.mode, person.statut].filter(Boolean).join(' · ');
          const form = fragment.querySelector('form');
          form.addEventListener('submit', event => {
            if (form.dataset.submitting) return event.preventDefault();
            form.dataset.submitting = 'true';
            form.querySelector('button').disabled = true;
            form.querySelector('button').textContent = 'Ajout du dossier…';
          });
          results.append(fragment);
        }
        message.textContent = data.items.length ? `${data.items.length} résultat(s). Sélectionnez la bonne préinscription.${data.more ? ' Précisez la recherche pour voir les autres résultats.' : ''}` : 'Aucune préinscription trouvée. Vous pouvez créer le dossier manuellement ci-dessous.';
      } catch (error) {
        if (error.name !== 'AbortError' && current === sequence) message.textContent = error.message;
      }
    };
    field.addEventListener('input', () => { clearTimeout(timer); timer = window.setTimeout(search, 350); });
    candidateForm.addEventListener('submit', event => { event.preventDefault(); clearTimeout(timer); search(); });
  }
  const disableContractActions = () => {
    root.querySelector('[data-contract-unsaved]')?.removeAttribute('hidden');
    root.querySelectorAll('[data-contract-generate] button, [data-contract-send] button, [data-opco-submit] button').forEach(button => { button.disabled = true; });
  };
  root.querySelectorAll('[data-contract-settings], [data-cerfa-form]').forEach(form => {
    form.addEventListener('input', disableContractActions);
    form.addEventListener('change', disableContractActions);
  });
  root.querySelectorAll('[data-contract-settings]').forEach(form => {
    let active = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (active || !form.reportValidity()) return;
      const body = new FormData(form);
      // Named submit buttons (including the legacy NPEC conversion) are not
      // included by FormData(form). Preserve the explicit action chosen.
      if (event.submitter?.name) body.set(event.submitter.name, event.submitter.value);
      const message = form.querySelector('[data-contract-save-message]');
      const buttons = [...form.elements].filter(element => element.tagName === 'BUTTON' && element.type !== 'button');
      active = true;
      form.setAttribute('aria-busy', 'true');
      buttons.forEach(button => { button.disabled = true; });
      message.hidden = true;
      try {
        const response = await fetch(form.action, {method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}});
        const data = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null;
        if (!response.ok || !data?.ok) throw new Error(data?.message || 'Enregistrement non confirmé. Votre saisie reste affichée ; vérifiez votre connexion avant de réessayer.');
        window.location.assign(data.redirect_url);
      } catch (error) {
        message.textContent = `Les paramètres n’ont pas été enregistrés : ${error.message} Votre saisie est conservée à l’écran.`;
        message.hidden = false;
        message.scrollIntoView({block: 'center', behavior: 'smooth'});
      } finally {
        active = false;
        form.removeAttribute('aria-busy');
        buttons.forEach(button => { button.disabled = false; });
      }
    });
  });
  root.querySelectorAll('[data-opco-submit]').forEach(form => {
    let active = false;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (active || !form.reportValidity()) return;
      active = true;
      const button = form.querySelector('button');
      const message = form.querySelector('[data-opco-message]');
      button.disabled = true;
      form.setAttribute('aria-busy', 'true');
      message.textContent = 'Préparation de la télétransmission…';
      try {
        for (let step = 0; step < 12; step++) {
          const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: {Accept: 'application/json'}});
          if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('La session a expiré. Rechargez le dossier pour vérifier le résultat.');
          const data = await response.json();
          message.textContent = data.message;
          if (!response.ok) throw new Error(data.error || data.message);
          if (data.done) { window.location.assign(data.redirect_url); return; }
        }
        throw new Error('La préparation est enregistrée. Rechargez le dossier pour poursuivre.');
      } catch (error) {
        message.textContent = `${error.message} Rechargez le dossier pour consulter le suivi.`;
      } finally {
        active = false;
        form.removeAttribute('aria-busy');
        // A request may have reached WEDOF despite a disconnected browser.
        // Reloading lets the server's recorded result decide whether retry is safe.
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
