(() => {
  'use strict';
  const root = document.getElementById('uv-experience');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  let state = null, deadline = 0, busy = false, failed = false, clockInterval;
  const duration = Number(root.dataset.seconds) || 45;
  const start = $('uq-start'), next = $('uq-next');
  function tick() {
    if (!state?.started || state.completed) return;
    const ms = Math.max(0, deadline - Date.now());
    $('uq-seconds').textContent = String(Math.ceil(ms / 1000));
    $('uq-clock').style.setProperty('--remaining', `${Math.min(100, ms / (duration * 10))}%`);
    $('uq-clock').classList.toggle('is-urgent', ms <= 10000);
    if (ms <= 0 && !busy && !failed) send('sync');
  }
  function show(data) {
    if (data.completed) { window.location.reload(); return; }
    const changed = data.question?.id !== state?.question?.id;
    state = data;
    $('uq-intro').hidden = !!data.started;
    $('uq-player').hidden = !data.started;
    if (!data.started) { start.disabled = !$('uq-in-class').checked; return; }
    deadline = Date.now() + data.remaining_ms;
    if (changed) {
      $('uq-count').replaceChildren(document.createTextNode(`Question ${String(data.index).padStart(2, '0')} `));
      const count = document.createElement('span'); count.textContent = `/ ${data.total}`; $('uq-count').append(count);
      $('uq-question').textContent = data.question.prompt;
      $('uq-options').replaceChildren();
      const legend = document.createElement('legend'); legend.className = 'uq-sr-only'; legend.textContent = 'Sélectionnez une réponse'; $('uq-options').append(legend);
      data.question.options.forEach(option => {
        const label = document.createElement('label'); label.className = 'uq-option';
        const input = document.createElement('input'); input.type = 'radio'; input.name = 'answer'; input.value = option.id;
        input.addEventListener('change', () => { next.disabled = busy; });
        const letter = document.createElement('span'); letter.className = 'uq-letter'; letter.textContent = option.id;
        const text = document.createElement('span'); text.textContent = option.text;
        label.append(input, letter, text); $('uq-options').append(label);
      });
      $('uq-question').focus({preventScroll:true});
      $('uq-bar').style.width = `${(data.index - 1) / data.total * 100}%`;
      $('uq-progress').setAttribute('aria-valuenow', String(data.index - 1));
      next.textContent = data.index === data.total ? 'Terminer et voir la correction →' : 'Valider et continuer →';
      next.disabled = true;
    }
    tick();
    clearInterval(clockInterval); clockInterval = setInterval(tick, 200);
  }
  async function send(action, extra = {}) {
    if (busy) return;
    busy = true; failed = false; start.disabled = true; next.disabled = true;
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(root.dataset.endpoint, {method:'POST', credentials:'same-origin', signal:controller.signal, headers:{'Content-Type':'application/json'}, body:JSON.stringify({csrf:root.dataset.csrf, action, ...extra})});
      if (response.redirected) { window.location.assign(response.url); return; }
      if (!response.ok) {
        if ([403,404,409].includes(response.status)) throw new Error('Votre accès a changé ou votre session a expiré. Revenez à votre espace stagiaire puis reconnectez-vous.');
        throw new Error('La réponse n’a pas pu être confirmée. Réessayez pour reprendre à la dernière question enregistrée.');
      }
      const data = await response.json();
      $('uq-error').hidden = true;
      show(data);
    } catch(error) {
      failed = true;
      $('uq-error-text').textContent = error.name === 'AbortError' ? 'La connexion est trop lente. Réessayez pour reprendre votre évaluation.' : error.message;
      $('uq-error').hidden = false;
    } finally {
      clearTimeout(timeout); busy = false;
      start.disabled = !$('uq-in-class').checked;
      next.disabled = failed || !document.querySelector('#uq-options input:checked') || Date.now() >= deadline;
    }
  }
  $('uq-in-class').addEventListener('change', () => { start.disabled = busy || !$('uq-in-class').checked; });
  start.addEventListener('click', () => { if ($('uq-in-class').checked) send('start', {in_class:'yes'}); });
  $('uq-form').addEventListener('submit', (event) => {
    event.preventDefault(); const chosen = document.querySelector('#uq-options input:checked');
    if (chosen && state && Date.now() < deadline) send('answer', {question_id:state.question.id, answer:chosen.value});
    else if (Date.now() >= deadline) send('sync');
  });
  $('uq-retry').addEventListener('click', () => send('sync'));
  document.addEventListener('visibilitychange', () => { if (!document.hidden && state?.started) send('sync'); });
  send('sync');
})();
