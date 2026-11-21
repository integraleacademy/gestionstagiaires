(() => {
  const dialog = document.querySelector('#edof-cpf-mail-dialog');
  if (!dialog) return;
  const frame = dialog.querySelector('[data-cpf-preview-frame]');
  const recipient = dialog.querySelector('[data-cpf-recipient]');
  const subject = dialog.querySelector('[data-cpf-subject]');
  const info = dialog.querySelector('[data-cpf-info]');
  const send = dialog.querySelector('[data-cpf-send]');
  let selected = null;
  let sending = false;

  const feedback = (message, error = false) => {
    info.textContent = message || '';
    info.classList.toggle('is-error', !!error);
  };
  const getData = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store',
      headers: {'Accept': 'application/json', ...(options.headers || {})}, ...options});
    let body;
    try {
      body = await response.json();
    } catch (_) {
      throw new Error('Réponse indisponible. Actualisez la page et réessayez.');
    }
    if (!response.ok) throw new Error(body.message || "Cette action n'est plus disponible.");
    return body;
  };
  const openDialog = () => {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
  };

  for (const close of dialog.querySelectorAll('[data-cpf-close]')) {
    close.addEventListener('click', () => {
      if (sending) return;
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    });
  }
  dialog.addEventListener('cancel', event => {
    if (sending) event.preventDefault();
  });

  document.querySelectorAll('[data-edof-cpf-mail]').forEach(button => {
    button.addEventListener('click', async () => {
      if (sending) return;
      selected = button;
      recipient.textContent = 'Vérification de la fiche EDOF…';
      subject.textContent = '';
      frame.srcdoc = '';
      send.disabled = true;
      feedback('Préparation de la prévisualisation…');
      openDialog();
      try {
        const result = await getData(button.dataset.previewUrl);
        if (selected !== button) return;
        recipient.textContent = result.recipient || 'Adresse non vérifiée dans EDOF';
        subject.textContent = result.subject;
        frame.srcdoc = result.html || '';
        send.disabled = !result.can_send;
        if (result.status && result.status.label) {
          const status = result.status;
          feedback(status.label + (status.error ? ' — ' + status.error : '') +
            (result.explanation ? ' — ' + result.explanation : ''), !result.can_send);
        } else {
          feedback(result.explanation || 'Prévisualisation prête. Le bouton envoie immédiatement le message.', !result.can_send);
        }
      } catch (error) {
        recipient.textContent = 'Impossible de charger le destinataire';
        feedback(error.message || 'Prévisualisation indisponible.', true);
      }
    });
  });

  send.addEventListener('click', async () => {
    if (!selected || sending || send.disabled) return;
    sending = true;
    send.disabled = true;
    send.textContent = 'Envoi en cours…';
    feedback('Transmission au service d’envoi…');
    const button = selected;
    try {
      const result = await getData(button.dataset.sendUrl, {
        method: 'POST',
        headers: {'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body: new URLSearchParams({csrf: button.dataset.csrf}),
      });
      feedback(result.message || 'E-mail accepté par le service d’envoi.');
      const status = button.closest('tr')?.querySelector('.edof-cpf-status');
      if (status) {
        status.textContent = 'E-mail envoyé';
        status.dataset.cpfStatus = 'sent';
      }
      button.disabled = true;
      button.textContent = 'E-mail déjà envoyé';
    } catch (error) {
      // Un timeout ne doit jamais réactiver l’envoi sans vérification serveur :
      // l’API persiste le statut "inconnu" pour empêcher les doublons.
      feedback((error.message || "L'envoi n'a pas pu être confirmé.") +
        ' Fermez cette fenêtre puis vérifiez le statut du dossier.', true);
    } finally {
      sending = false;
      send.textContent = 'Envoyer ce courriel';
    }
  });
})();
