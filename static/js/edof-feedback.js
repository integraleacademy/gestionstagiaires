(() => {
  const dialog = document.getElementById('edof-action-dialog');
  const banner = document.getElementById('edof-action-resume');
  if (!dialog || !banner || typeof dialog.showModal !== 'function') return;
  const titles = {
    sync: ['Synchronisation manuelle en cours', 'Synchronisation terminée'],
    connect: ['Connexion EDOF en cours', 'Connexion EDOF confirmée'],
    reconnect: ['Reconnexion EDOF en cours', 'Reconnexion EDOF confirmée'],
    catchup: ['Rattrapage des automatisations en cours', 'Rattrapage terminé'],
    proposal: ['Dossier en cours de transmission à EDOF', 'Transmission confirmée par EDOF']
  };
  let current, sequence = 0, timer, trigger, suspendedRefresh;
  const title = dialog.querySelector('#edof-action-title');
  const subtitle = dialog.querySelector('[data-action-subtitle]');
  const phase = dialog.querySelector('[data-action-phase]');
  const message = dialog.querySelector('#edof-action-message');
  const help = dialog.querySelector('[data-action-help]');
  const reload = dialog.querySelector('[data-action-reload]');
  const correct = dialog.querySelector('[data-action-correct]');
  const issues = dialog.querySelector('[data-action-issues]');
  function timerText() {
    const seconds = Math.floor((Date.now() - current.started) / 1000);
    dialog.querySelector('[data-action-elapsed]').textContent = 'Depuis ' +
      [Math.floor(seconds / 60), seconds % 60].map(n => String(n).padStart(2, '0')).join(':');
  }
  function show() { banner.hidden = true; if (!dialog.open) dialog.showModal(); }
  function paint(status) {
    dialog.dataset.state = status;
    banner.dataset.state = status;
    const done = !['request', 'running'].includes(status);
    for (const step of dialog.querySelectorAll('[data-action-step]')) {
      const active = step.dataset.actionStep === (done ? 'done' : status);
      step.classList.toggle('is-current', active);
      step.classList.toggle('is-done', done || status === 'running' && step.dataset.actionStep === 'request');
      if (active) step.setAttribute('aria-current', 'step'); else step.removeAttribute('aria-current');
    }
    dialog.querySelector('.edof-action-status').setAttribute('aria-busy', String(!done));
    dialog.querySelector('.edof-action-footer [data-action-close]').textContent = done ? 'Fermer' : 'Continuer en arrière-plan';
    banner.querySelector('[data-action-banner]').textContent = !done ? titles[current.kind][0] :
      status === 'success' ? titles[current.kind][1] : 'Action EDOF à vérifier';
  }
  function hide() {
    dialog.close();
    banner.hidden = !current || current.dismissed;
    if (trigger?.isConnected && !trigger.disabled) trigger.focus({preventScroll:true});
  }
  function restoreRefresh() {
    if (suspendedRefresh && !current?.busy && !dialog.open) {
      document.head.appendChild(suspendedRefresh);
      suspendedRefresh = null;
    }
  }
  dialog.addEventListener('close', () => { banner.hidden = !current || current.dismissed; restoreRefresh(); });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    if (current && !current.busy) current.dismissed = true;
    hide();
  });
  for (const button of dialog.querySelectorAll('[data-action-close]')) button.addEventListener('click', () => {
    if (current && !current.busy) current.dismissed = true;
    hide();
  });
  banner.addEventListener('click', show);
  reload.addEventListener('click', () => location.reload());
  correct.addEventListener('click', () => { current.dismissed = true; hide(); current.correct?.(); });
  window.edofFeedback = {
    begin(kind, text, button, dossier='') {
      clearInterval(timer);
      current = {id: ++sequence, kind, busy:true, started:Date.now(), dismissed:false};
      trigger = button || document.activeElement;
      dialog.dataset.kind = kind;
      dialog.querySelector('[data-action-brand]').hidden = kind !== 'proposal';
      const caseLabel = dialog.querySelector('[data-action-case]');
      caseLabel.textContent = dossier; caseLabel.hidden = !dossier;
      correct.hidden = true; issues.replaceChildren(); issues.hidden = true;
      suspendedRefresh = suspendedRefresh || document.querySelector('meta[http-equiv="refresh"]');
      suspendedRefresh?.remove();
      title.textContent = titles[kind][0];
      subtitle.textContent = 'Votre demande est prise en charge par le serveur.';
      phase.textContent = 'Transmission de votre demande…';
      message.textContent = text;
      help.textContent = 'Vous pouvez continuer en arrière-plan : le traitement se poursuit sur le serveur.';
      reload.hidden = true;
      paint('request'); timerText(); timer = setInterval(timerText, 1000); show();
      return current.id;
    },
    update(id, text, label='Traitement en cours…') {
      if (current?.id !== id || !current.busy) return;
      phase.textContent = label; message.textContent = text; paint('running');
    },
    finish(id, status, text, refresh=false, options={}) {
      if (current?.id !== id || !current.busy) return;
      current.busy = false;
      clearInterval(timer);
      title.textContent = options.title || (status === 'success' ? titles[current.kind][1] :
        status === 'warning' ? 'Traitement à vérifier' : current.kind === 'proposal' ? 'Transmission non aboutie' : 'Traitement non terminé');
      subtitle.textContent = status === 'success' ? 'Le serveur a confirmé le résultat.' : 'Le détail ci-dessous indique la suite à donner.';
      phase.textContent = options.phase || (status === 'success' ? 'Confirmation reçue' : status === 'warning' ? 'Une vérification est nécessaire' : 'Une difficulté a été rencontrée');
      message.textContent = text;
      help.textContent = options.help || (status === 'success' ? 'Vous pouvez fermer cette fenêtre et poursuivre votre travail.' :
        'Consultez le suivi avant de relancer : aucune tentative supplémentaire n’est déclenchée par cette fenêtre.');
      reload.hidden = !refresh;
      current.correct = options.correct;
      correct.hidden = !options.correct;
      for (const detail of options.issues || []) {
        const item = document.createElement('li'); item.textContent = detail; issues.appendChild(item);
      }
      issues.hidden = !issues.childElementCount;
      paint(status);
      if (!dialog.open) banner.hidden = false;
      restoreRefresh();
    },
    show(id) { if (current?.id === id) show(); },
    get blockingReload() { return Boolean(dialog.open || current?.busy); }
  };
})();
