(() => {
  const dialog = document.getElementById('vaeApsAccess');
  const form = dialog.querySelector('form');
  const submit = form.querySelector('[type="submit"]');
  const notice = form.querySelector('[data-status]');
  let ticket;
  let saved = false;
  document.getElementById('openVaeApsAccess').addEventListener('click', async () => {
    dialog.showModal();
    submit.disabled = true;
    form.elements.send.checked = false;
    form.elements.send.disabled = true;
    notice.textContent = 'Chargement des accès…';
    try {
      const response = await fetch(form.dataset.preview, {cache: 'no-store'});
      if (!response.ok) throw new Error();
      const preview = await response.json();
      ticket = preview.ticket;
      form.querySelector('[data-recipient]').textContent = preview.can_send ? preview.email : 'Renseignez une adresse e-mail valide pour permettre l’envoi.';
      form.querySelector('[data-subject]').textContent = preview.subject;
      form.querySelector('iframe').srcdoc = preview.html;
      form.elements.send.disabled = !preview.can_send || !preview.mail_available;
      submit.disabled = false;
      notice.textContent = '';
    } catch {
      notice.textContent = 'Impossible de charger les accès. Fermez cette fenêtre et réessayez.';
    }
  });
  dialog.querySelector('[data-dismiss]').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (saved) location.reload(); });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    const send = form.elements.send.checked;
    form.elements.send.disabled = true;
    notice.textContent = 'Enregistrement…';
    try {
      const response = await fetch(form.dataset.activate, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ticket, send})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Rechargez la fiche pour vérifier les accès.');
      saved = true;
      const messages = {
        sent: 'L’accès APS est ouvert. Le mail a été envoyé.',
        failed: 'L’accès APS est ouvert. L’envoi a échoué. Fermez cette fenêtre pour réessayer depuis la fiche.',
        sending: 'L’accès APS est ouvert. Le mail est en cours d’envoi.',
        unconfirmed: 'L’accès APS est ouvert. Vérifiez dans Brevo si le mail a été reçu.'
      };
      notice.textContent = messages[result.status] || 'L’accès APS est ouvert dans l’espace stagiaire.';
      if (!dialog.open) location.reload();
    } catch (error) {
      notice.textContent = error.message || 'Rechargez la fiche pour vérifier les accès.';
    }
  });
})();
