(() => {
  const feedback = window.edofFeedback;
  const section = () => document.getElementById('proposition-edof');
  if (!feedback || !section()) return;
  const pending = new Set(['queued', 'saving', 'validating', 'checking']);
  let following = false, submitting = false, invalidTimer, currentId, lastWatch = 0, registering = false;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

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
        {rejected:response.status >= 400 && response.status < 500, body});
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
  async function watch(force=false) {
    if (!section()?.dataset.watchUrl || (!force && (document.hidden || Date.now()-lastWatch < 60000))) return;
    const body = new FormData(); body.set('csrf', section().dataset.csrf);
    await read(section().dataset.watchUrl, {method:'POST', body});
    lastWatch = Date.now();
  }
  function registered(id, link) {
    const content = feedback.content(id);
    if (content) { content.hidden = true; content.replaceChildren(); }
    feedback.journey(id, 'registered', {title:'Inscription confirmée', phase:'Le dossier CPF est associé',
      message:`Le stagiaire est inscrit${link?.session_name ? ' sur « '+link.session_name+' »' : ''}.`,
      actionLabel:'Ouvrir la fiche stagiaire', action:link?.url ? () => location.assign(link.url) : undefined});
  }
  function accepted(id, journey) {
    if (journey.link) { registered(id, journey.link); return; }
    feedback.journey(id, 'accepted', {title:'Dossier accepté par le titulaire', phase:'Vous pouvez inscrire le stagiaire',
      message:'L’acceptation est confirmée par EDOF. Choisissez maintenant la session de formation.',
      action:journey.can_register ? () => chooseSession(id, journey.registration_url) : undefined});
  }
  async function followJourney(url, id, first) {
    let journey = first;
    while (feedback.isCurrent(id)) {
      try {
        journey = journey || await read(url);
        if (!feedback.isCurrent(id)) return;
        if (journey.state === 'accepted' || journey.link) {
          accepted(id, journey);
          await refreshDetail(journey.detail_url);
          return;
        }
        if (!['waiting','ft','ft_refused'].includes(journey.state)) {
          feedback.journey(id, 'error', {title:journey.state === 'canceled' ? 'Dossier annulé' : journey.state === 'refused' ? 'Proposition refusée' : 'Le statut du dossier a changé',
            phase:journey.label, message:'L’inscription sur une session n’est pas disponible pour ce statut.',
            actionLabel:'Ouvrir le dossier', action:() => location.assign(journey.detail_url)});
          return;
        }
        feedback.journey(id, 'waiting', {title:'En attente d’acceptation du titulaire', phase:'Dossier transmis à EDOF',
          message:'Dossier transmis à EDOF, en attente d’acceptation par le titulaire.' +
            (journey.state === 'ft' ? ' Une demande de financement France Travail est en cours.' : journey.state === 'ft_refused' ? ' La demande de financement France Travail a été refusée.' : ''),
          help:'Le statut se met à jour automatiquement. Vous pouvez fermer cette fenêtre ; le suivi reste accessible depuis ce dossier.'});
        if (journey.can_watch) await watch();
      } catch (error) {
        if (!feedback.isCurrent(id)) return;
        feedback.journey(id, error.rejected ? 'error' : 'waiting', {title:'Suivi du dossier à reprendre',
          phase:'La proposition n’est pas renvoyée', message:error.rejected ? error.message : 'Le suivi est momentanément indisponible. Une nouvelle vérification sera faite automatiquement.',
          ...(error.rejected ? {actionLabel:'Actualiser le dossier', action:() => location.reload()} : {})});
        if (error.rejected) return;
      }
      await pause(document.hidden ? 30000 : 8000);
      journey = null;
    }
  }
  function attachChooser(id) {
    const content = feedback.content(id);
    const form = content?.querySelector('[data-registration-form]');
    if (!form) return;
    const submit = form.querySelector('button[type="submit"]');
    const choose = () => {
      const selected = form.querySelector('[name="session_id"]:checked');
      form.querySelector('[data-session-dates]').hidden = !selected || selected.dataset.datesMatch === '1';
      submit.disabled = !selected;
    };
    form.addEventListener('change', choose);
    choose();
    form.querySelector('[data-session-search]').addEventListener('input', event => {
      const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('fr');
      const query = normalize(event.target.value.trim());
      let count = 0;
      for (const option of form.querySelectorAll('[data-session-option]')) {
        option.hidden = !normalize(option.textContent).includes(query);
        if (!option.hidden) count++;
      }
      form.querySelector('[data-session-empty]').hidden = count > 0;
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (registering || !form.reportValidity()) return;
      registering = true;
      submit.disabled = true;
      const errorBox = form.querySelector('[data-registration-error]'); errorBox.hidden = true;
      feedback.journey(id, 'saving', {title:'Inscription en cours', phase:'Création du stagiaire et association CPF',
        message:'Les informations EDOF sont reprises dans la session sélectionnée.'});
      try {
        const result = await read(form.action, {method:'POST', body:new FormData(form)});
        if (!result.registered) throw Error('L’inscription n’a pas été confirmée.');
        registered(id, result.link);
        const updated = await read(section().dataset.journeyUrl);
        await refreshDetail(updated.detail_url);
      } catch (error) {
        // A lost response can hide a successful atomic registration. Read the link before retrying.
        let saved;
        try { saved = await read(section().dataset.journeyUrl); } catch { /* Keep the explicit error below. */ }
        if (saved?.link) { registered(id, saved.link); return; }
        feedback.journey(id, 'choosing', {title:'Choisir la session de formation', phase:'Inscription non confirmée',
          message:'Vérifiez le message ci-dessous avant de reprendre.'});
        errorBox.textContent = error.message || 'Le serveur n’a pas confirmé l’inscription. Vous pouvez vérifier le dossier puis reprendre.';
        errorBox.hidden = false;
        submit.disabled = false;
      } finally { registering = false; }
    });
  }
  async function chooseSession(id, url) {
    if (registering) return;
    registering = true;
    const content = feedback.content(id);
    if (!content) { registering = false; return; }
    feedback.journey(id, 'loading', {title:'Préparation de l’inscription', phase:'Récupération des informations EDOF',
      message:'Nous préparons la fiche du candidat et les sessions correspondant à sa formation.'});
    content.hidden = true; content.replaceChildren();
    try {
      const deadline = Date.now()+5*60*1000;
      while (feedback.isCurrent(id)) {
        const result = await read(url);
        if (!feedback.isCurrent(id)) return;
        if (result.link) { registered(id, result.link); return; }
        if (result.ready) {
          content.replaceChildren(...new DOMParser().parseFromString(result.html,'text/html').body.childNodes);
          content.hidden = false;
          feedback.journey(id, 'choosing', {title:'Choisir la session de formation', phase:'Informations du candidat récupérées',
            message:'Seules les sessions compatibles sont proposées. Les dates identiques au dossier EDOF apparaissent en premier.'});
          attachChooser(id);
          return;
        }
        await watch();
        if (Date.now() > deadline) throw Error('La fiche complète n’a pas encore été récupérée. Vérifiez la connexion EDOF puis reprenez l’inscription.');
        await pause(5000);
      }
    } catch (error) {
      if (error.body?.link) { registered(id, error.body.link); return; }
      feedback.journey(id, 'error', {title:'Informations EDOF à vérifier', message:error.message,
        actionLabel:'Reprendre l’inscription', action:() => chooseSession(id, url)});
    } finally { registering = false; }
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
          if (job.status === 'confirmed' && job.journey) {
            await refreshDetail(job.journey.detail_url);
            await followJourney(job.journey.poll_url, id, job.journey);
            return;
          }
          const status = job.status === 'confirmed' ? 'success' : job.status === 'uncertain' ? 'warning' : 'error';
          feedback.finish(id, status, job.message, job.status === 'confirmed', {
            title:job.stopped_before_send ? 'Proposition non envoyée' : job.status === 'uncertain' ? 'Réception à vérifier dans EDOF' : undefined,
            phase:job.stopped_before_send ? 'Lecture interrompue avant l’envoi' : undefined,
            help:job.stopped_before_send ? 'Fermez cette fenêtre pour retrouver votre proposition.' : undefined,
            correct:job.status === 'error' && !job.stopped_before_send ? () => correct(job.message) : undefined
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
    const button = event.target.closest('[data-proposal-follow], [data-journey-follow], [data-registration-open]');
    if (!button) return;
    if ((following || submitting || registering) && feedback.isCurrent(currentId)) { feedback.show(currentId); return; }
    if (button.matches('[data-registration-open]')) { chooseSession(begin(button), section().dataset.registrationUrl); return; }
    if (button.matches('[data-journey-follow]') || section().dataset.transmissionState === 'confirmed') {
      following = true;
      followJourney(section().dataset.journeyUrl, begin(button)).finally(() => { following = false; });
      return;
    }
    const url = section().dataset.transmissionUrl;
    if (url) follow(url, begin(button));
  });
  const box = section();
  if (pending.has(box.dataset.transmissionState) && box.dataset.transmissionUrl) {
    follow(box.dataset.transmissionUrl, begin());
  } else if (new URL(location.href).searchParams.get('enroll') === '1' && box.dataset.followable === '1') {
    chooseSession(begin(), box.dataset.registrationUrl);
  }
})();
