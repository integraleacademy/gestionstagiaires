(() => {
  const feedback = window.edofFeedback;
  const section = () => document.getElementById('proposition-edof');
  if (!feedback || !section()) return;
  const pending = new Set(['queued', 'saving', 'validating', 'checking']);
  let following = false, submitting = false, invalidTimer, currentId;

  function begin(button) {
    const box = section();
    return currentId = feedback.begin('proposal', 'Vérification de votre demande avant transmission.', button,
      `${box.dataset.holder} · Dossier CPF ${box.dataset.folder}`);
  }
  function correct(message='') {
    const form = section()?.querySelector('.edof-proposal-form');
    const field = form?.querySelector(':invalid:not(fieldset)') ||
      (/date/i.test(message) && form?.querySelector('[name="sessionStartDate"]')) || form?.querySelector('input:not([type="hidden"])');
    if (!field) { location.reload(); return; }
    for (let el=field.parentElement; el; el=el.parentElement) if (el.tagName === 'DETAILS') el.open = true;
    field.focus(); field.scrollIntoView({block:'center', behavior:'smooth'});
  }
  async function read(url, options={}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {...options, cache:'no-store', signal:controller.signal,
        headers:{Accept:'application/json'}});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw Object.assign(Error(body.message || (response.status === 403 ?
        'Votre session ou vos droits ne permettent pas cette action. Actualisez la page.' : 'Le suivi EDOF est indisponible.')),
        {rejected:response.status >= 400 && response.status < 500});
      return body;
    } finally { clearTimeout(timeout); }
  }
  async function refreshDetail(url) {
    try {
      const response = await fetch(url, {cache:'no-store', signal:AbortSignal.timeout(20000)});
      if (!response.ok) return;
      const documentNext = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = documentNext.getElementById('proposition-edof');
      if (next) section()?.replaceWith(next);
    } catch { /* The confirmed result remains visible; refreshing the page is optional. */ }
  }
  async function follow(url, id, first) {
    following = true;
    try {
      const deadline = Date.now() + 35*60*1000;
      let job = first;
      while (Date.now() < deadline) {
        job = job || await read(url);
        if (!job.status || !job.label) throw Error('Le suivi a renvoyé une réponse incomplète.');
        section().dataset.transmissionUrl = job.poll_url;
        section().dataset.transmissionState = job.status;
        if (!pending.has(job.status)) {
          const status = job.status === 'confirmed' ? 'success' : job.status === 'uncertain' ? 'warning' : 'error';
          feedback.finish(id, status, job.message, job.status === 'confirmed', {
            title:job.status === 'uncertain' ? 'Réception à vérifier dans EDOF' : undefined,
            correct:job.status === 'error' ? () => correct(job.message) : undefined
          });
          await refreshDetail(job.detail_url);
          return;
        }
        feedback.update(id, job.message, job.label);
        await new Promise(resolve => setTimeout(resolve, 1500));
        job = null;
      }
      throw Error('Le traitement dure plus longtemps que prévu. Consultez le suivi avant tout nouvel envoi.');
    } catch (error) {
      feedback.finish(id, 'warning', `${error.message || 'Le suivi est momentanément indisponible.'} La transmission peut se poursuivre sur le serveur. Actualisez le dossier avant de renvoyer.`, true);
    } finally { following = false; }
  }

  // Native invalid fields never reach submit. Group them in one accessible modal.
  document.addEventListener('invalid', event => {
    const form = event.target.closest('.edof-proposal-form');
    if (!form) return;
    event.preventDefault(); clearTimeout(invalidTimer);
    invalidTimer = setTimeout(() => {
      const missing = Array.from(form.elements).filter(el => el.willValidate && !el.validity.valid);
      if (!missing.length) return;
      const labels = missing.map(el => {
        const label = el.closest('label')?.querySelector('span')?.textContent ||
          (el.name === 'confirm' ? 'Confirmation des conditions avant l’envoi' : el.name);
        return `${label.replace(/\s*\*\s*$/, '').trim()} : ${el.validationMessage}`;
      });
      const id = begin(missing[0]);
      feedback.finish(id, 'error', 'Certaines informations sont manquantes ou incorrectes. Complétez-les avant de transmettre le dossier.', false,
        {title:'Informations à compléter', issues:labels, correct:() => correct()});
    }, 0);
  }, true);

  document.addEventListener('submit', async event => {
    const form = event.target;
    const check = form.matches('[data-proposal-recheck]');
    if (!check && !form.matches('.edof-proposal-form')) return;
    if (event.submitter?.hasAttribute('formaction')) return; // Save draft remains local.
    event.preventDefault();
    if (submitting || following) return;
    submitting = true;
    const button = event.submitter || form.querySelector('button[type="submit"]');
    const id = begin(button);
    const body = new FormData(form);
    if (button) button.disabled = true;
    try {
      const job = await read(form.action, {method:'POST', body});
      if (!job.poll_url) throw Error('La prise en charge n’a pas pu être confirmée.');
      await follow(job.poll_url, id, job);
    } catch (error) {
      feedback.finish(id, error.rejected ? 'error' : 'warning', error.rejected ? error.message :
        'La réponse du serveur n’a pas été reçue. Le dossier peut avoir été pris en charge : actualisez le suivi avant tout nouvel envoi.',
        !error.rejected, {correct:error.rejected ? () => correct(error.message) : undefined});
    } finally { submitting = false; if (button?.isConnected) button.disabled = false; }
  });

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-proposal-follow]');
    if (!button) return;
    if (following || submitting) { feedback.show(currentId); return; }
    const url = section().dataset.transmissionUrl;
    if (url) follow(url, begin(button));
  });
  const box = section();
  if (pending.has(box.dataset.transmissionState) && box.dataset.transmissionUrl) {
    follow(box.dataset.transmissionUrl, begin());
  }
})();
