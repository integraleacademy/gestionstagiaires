(() => {
  'use strict';
  const root = document.querySelector('[data-campaigns]');
  if (!root) return;
  const pageToggle = root.querySelector('#pc-select-page');
  const audience = root.querySelector('#pc-audience');
  const contacts = [...root.querySelectorAll('[name="contact_id"]')];
  const includeContacted = root.querySelector('[name="include_contacted"]');
  const recipientCount = root.querySelector('#pc-recipient-count');
  const prepareButtons = [...root.querySelectorAll('[data-create-submit]')];
  function updateAudience(reset = false) {
    if (!audience || !recipientCount) return;
    const all = audience.value === 'all';
    const eligible = input => includeContacted.checked || input.dataset.contacted !== '1';
    contacts.forEach(input => {
      input.disabled = all || !eligible(input);
      if (all) input.checked = eligible(input);
      else if (reset || !eligible(input)) input.checked = false;
    });
    const available = contacts.filter(eligible);
    const checked = available.filter(input => input.checked).length;
    pageToggle.disabled = all || !available.length;
    pageToggle.checked = !!available.length && checked === available.length;
    pageToggle.indeterminate = !all && checked > 0 && checked < available.length;
    const count = all ? Number(recipientCount.dataset[includeContacted.checked ? 'total' : 'eligible']) : checked;
    const label = `${count.toLocaleString('fr-FR')} destinataire${count === 1 ? '' : 's'}`;
    recipientCount.textContent = all ? `${label} dans une seule campagne, toutes les pages incluses.` : `${label} parmi les contacts cochés sur cette page.`;
    prepareButtons.forEach(button => {
      button.disabled = count === 0;
      button.textContent = `Préparer l’envoi à ${count.toLocaleString('fr-FR')} contact${count === 1 ? '' : 's'} →`;
    });
  }
  audience?.addEventListener('change', () => updateAudience(true));
  includeContacted?.addEventListener('change', () => updateAudience());
  pageToggle?.addEventListener('change', () => {
    contacts.filter(input => !input.disabled).forEach(input => { input.checked = pageToggle.checked; });
    updateAudience();
  });
  contacts.forEach(input => input.addEventListener('change', () => updateAudience()));
  updateAudience();
  root.querySelectorAll('[data-exclude-contact]').forEach(button => button.addEventListener('click', event => {
    if (!window.confirm('Exclure ce contact des prochains envois ?')) event.preventDefault();
  }));
  const panel = root.querySelector('[data-campaign-id]');
  if (!panel) return;
  const start = panel.querySelector('#pc-start');
  const pause = panel.querySelector('#pc-pause');
  const message = panel.querySelector('#pc-send-status');
  const sendError = panel.querySelector('#pc-send-error');
  const errorDetail = panel.querySelector('#pc-error-detail');
  const retryOption = panel.querySelector('#pc-retry-option');
  const confirm = panel.querySelector('#pc-confirm');
  const csrf = root.querySelector('[name="csrf_token"]').value;
  let running = false;
  let stopRequested = false;
  async function post(url, extra = {}) {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({csrf_token:csrf,...extra}), credentials:'same-origin'});
    const type = response.headers.get('content-type') || '';
    const data = type.includes('application/json') ? await response.json() : {};
    if (!response.ok || !type.includes('application/json')) throw new Error(data.error || 'La session a expiré ou la requête a échoué. Rechargez la page pour vérifier les résultats.');
    return data;
  }
  function update(data) {
    if (!data.counts) return;
    panel.querySelectorAll('[data-count]').forEach(node => { node.textContent = data.counts[node.dataset.count] || 0; });
    panel.querySelector('progress').value = data.total - (data.counts.pending || 0) - (data.counts.sending || 0);
    sendError.hidden = !data.last_error;
    errorDetail.textContent = data.last_error || '';
    retryOption.hidden = !data.counts.failed;
  }
  start.disabled = !confirm.checked;
  confirm.addEventListener('change', () => { if (!running) start.disabled = !confirm.checked; });
  start.addEventListener('click', async () => {
    if (running || !confirm.checked) return;
    running = true;
    stopRequested = false;
    start.disabled = true;
    pause.hidden = false;
    pause.disabled = false;
    message.classList.remove('pc-error');
    message.textContent = 'Envoi en cours… Gardez cette page ouverte.';
    try {
      await post(panel.dataset.startUrl, {confirm:'yes', retry_failed:panel.querySelector('#pc-retry')?.checked ? 'yes' : 'no'});
      while (!stopRequested) {
        const data = await post(panel.dataset.nextUrl);
        update(data);
        if (data.busy) {
          message.textContent = 'Un envoi est déjà en cours. Rechargez la page dans quelques instants pour reprendre.';
          break;
        }
        if (data.done) {
          message.textContent = data.counts.uncertain ? 'Certains résultats sont incertains : vérifiez-les dans Brevo. Ils ne seront pas renvoyés automatiquement.' : data.status === 'paused' && data.counts.failed ? 'L’envoi s’est arrêté après un refus. Les destinataires en attente sont conservés.' : data.status === 'completed' ? 'Traitement terminé. Actualisez le détail pour consulter chaque résultat.' : 'Envoi en pause. Les destinataires restants sont conservés.';
          break;
        }
        message.textContent = `${data.counts.sent || 0} / ${data.total} mails acceptés par Brevo. Envoi en cours…`;
        await new Promise(resolve => setTimeout(resolve, 350));
      }
      if (stopRequested) message.textContent = 'Envoi en pause. Vous pouvez reprendre les destinataires restants plus tard.';
    } catch (error) {
      message.classList.add('pc-error');
      message.textContent = `${error.message} Aucun renvoi automatique n’est effectué : consultez les résultats avant de reprendre.`;
    } finally {
      running = false;
      start.disabled = !confirm.checked;
      start.textContent = 'Reprendre les envois restants';
      pause.hidden = true;
    }
  });
  pause.addEventListener('click', async () => {
    stopRequested = true;
    pause.disabled = true;
    try { await post(panel.dataset.pauseUrl); }
    catch (error) { message.textContent = error.message; }
  });
  window.addEventListener('beforeunload', event => {
    if (running) { event.preventDefault(); event.returnValue = ''; }
  });
})();
