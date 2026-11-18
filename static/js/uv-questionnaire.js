(() => {
  'use strict';
  const root = document.getElementById('uv-experience');
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  let state = null, deadline = 0, syncNotBefore = 0, busy = false, failed = false, clockInterval;
  const duration = Number(root.dataset.seconds) || 45;
  const start = $('uq-start'), next = $('uq-next');
  const demo = root.dataset.demo === 'true';
  const generation = root.dataset.generation || '';
  const storageKey = 'uv-pending:' + root.dataset.endpoint;
  let pending = null;
  if (!demo) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey));
      if (saved?.generation === generation && typeof saved.question_id === 'string' && typeof saved.answer === 'string') {
        pending = {question_id: saved.question_id, answer: saved.answer};
      } else {
        sessionStorage.removeItem(storageKey);
      }
    } catch { /* Storage may be unavailable in private browsing. */ }
  }

  function remember(answer) {
    pending = answer;
    if (demo) return;
    try {
      if (answer) sessionStorage.setItem(storageKey, JSON.stringify({...answer, generation}));
      else sessionStorage.removeItem(storageKey);
    } catch { /* Keep the submitted choice in memory in this tab. */ }
  }

  const demoQuestions = demo ? JSON.parse($('uq-demo-data').textContent) : [];
  let demoIndex = 0, demoStarted = false, demoDeadline = 0;
  const demoAnswers = {};
  function demoRequest(action, extra) {
    if (!demoStarted) {
      if (action !== 'start') return {started:false, completed:false};
      demoStarted = true; demoDeadline = Date.now() + duration * 1000;
    }
    const question = demoQuestions[demoIndex];
    if (question && (Date.now() >= demoDeadline || (action === 'answer' && extra.question_id === question.id))) {
      demoAnswers[question.id] = Date.now() >= demoDeadline ? '' : extra.answer;
      demoIndex++; demoDeadline = Date.now() + duration * 1000;
    }
    if (demoIndex === demoQuestions.length) return {completed:true, score:demoQuestions.filter(q=>demoAnswers[q.id]===q.answer).length};
    return {started:true, completed:false, index:demoIndex+1, total:demoQuestions.length,
      remaining_ms:Math.max(0,demoDeadline-Date.now()), question:demoQuestions[demoIndex]};
  }
  function demoResult(data) {
    clearInterval(clockInterval); state = data;
    $('uq-intro').hidden = true; $('uq-player').hidden = true;
    const node = (tag, cls, text) => { const el=document.createElement(tag); el.className=cls; if(text) el.textContent=text; return el; };
    const host = $('uq-demo-results'); host.hidden = false; host.replaceChildren();
    const intro=node('section','uq-intro uq-results');
    intro.append(node('p','uq-eyebrow','Aperçu terminé'),node('h1','', 'Voici la correction affichée au stagiaire.'));
    const score=node('div','uq-result-score',String(data.score));score.append(node('span','','/20'));intro.append(score);
    intro.append(node('p','uq-lead','Ce résultat de démonstration n’est pas enregistré.'));
    const restart=node('button','uq-primary uq-demo-restart','Recommencer l’aperçu');restart.type='button';restart.addEventListener('click',()=>window.location.reload());intro.append(restart);host.append(intro);
    const list=node('div','uq-corrections');
    demoQuestions.forEach((q,i)=>{
      const selected=demoAnswers[q.id], good=selected===q.answer;
      const card=node('article','uq-correction'), heading=node('div','uq-correction-heading');
      heading.append(node('span','uq-tag',`Question ${String(i+1).padStart(2,'0')}`),node('span',`uq-result-status ${good?'good':'wrong'}`,!selected?'Temps écoulé · Sans réponse':good?'Bonne réponse':'À revoir'));
      card.append(heading,node('h2','',q.prompt));
      q.options.forEach(o=>{
        const answer=node('div',`uq-answer-review ${o.id===q.answer?'good':o.id===selected?'wrong':''}`), text=node('span','',o.text);
        if(o.id===selected)text.append(node('small','','Votre réponse'));
        if(o.id===q.answer)text.append(node('small','','Bonne réponse'));
        answer.append(node('strong','',o.id),text);card.append(answer);
      });
      const explanation=node('p','uq-explanation');explanation.append(node('strong','','Pour comprendre'),document.createElement('br'),document.createTextNode(q.explanation));card.append(explanation);list.append(card);
    });
    host.append(list);window.scrollTo({top:0,behavior:'smooth'});
  }
  function tick() {
    if (!state?.started || state.completed) return;
    const now = performance.now();
    const ms = Math.max(0, deadline - now);
    $('uq-seconds').textContent = String(Math.ceil(ms / 1000));
    $('uq-clock').style.setProperty('--remaining', `${Math.min(100, ms / (duration * 10))}%`);
    $('uq-clock').classList.toggle('is-urgent', ms <= 10000);
    if (ms <= 0 && now >= syncNotBefore && !busy && !failed && !pending) send('sync', {question_id: state.question.id});
  }
  function show(data, observedAt = performance.now()) {
    if (data.completed) { if (demo) demoResult(data); else window.location.reload(); return; }
    const changed = data.question?.id !== state?.question?.id;
    state = data;
    $('uq-intro').hidden = !!data.started;
    $('uq-player').hidden = !data.started;
    if (!data.started) { start.disabled = !$('uq-in-class').checked; return; }
    deadline = observedAt + data.remaining_ms;
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
    const saving = action === 'answer';
    if (saving) {
      $('uq-options').disabled = true;
      next.textContent = 'Enregistrement…';
      $('uq-status').textContent = 'Enregistrement de votre réponse…';
      $('uq-status').hidden = false;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 45000);
    try {
      if (demo) {
        const result = demoRequest(action, extra);
        if (saving) remember(null);
        $('uq-error').hidden = true; $('uq-status').hidden = true;
        show(result);
        return;
      }
      const requestedAt = performance.now();
      const response = await fetch(root.dataset.endpoint, {method:'POST', credentials:'same-origin', signal:controller.signal, headers:{'Content-Type':'application/json'}, body:JSON.stringify({csrf:root.dataset.csrf, generation, action, ...extra})});
      if (response.redirected) { window.location.assign(response.url); return; }
      if (response.status === 409) {
        const reason = await response.json().catch(() => null);
        if (reason?.reset) { remember(null); window.location.reload(); return; }
      }
      if (!response.ok) {
        if ([403,404,409].includes(response.status)) throw new Error('Votre accès a changé ou votre session a expiré. Revenez à votre espace stagiaire puis reconnectez-vous.');
        throw new Error('Le serveur n’a pas confirmé l’enregistrement.');
      }
      const data = await response.json();
      const observedAt = performance.now();
      const roundTripMs = Math.max(0, observedAt - requestedAt);
      const processingMs = Number.isFinite(data.server_processing_ms) && data.server_processing_ms >= 0 && data.server_processing_ms <= roundTripMs
        ? data.server_processing_ms : 0;
      if (data.started && !data.completed) {
        const remainingMs = Number.isFinite(data.remaining_ms) ? Math.max(0, data.remaining_ms) : 0;
        // The server already deducted its processing time. Deduct the full
        // remaining round trip conservatively; older servers fall back to RTT.
        data.remaining_ms = Math.max(0, remainingMs - Math.max(0, roundTripMs - processingMs));
        // A conservative estimate can reach zero before the server deadline.
        // Avoid rapid sync retries while allowing the server to refresh it.
        syncNotBefore = data.remaining_ms === 0 && remainingMs > 0
          ? observedAt + Math.min(1000, remainingMs) : 0;
      }
      if (saving) remember(null);
      $('uq-error').hidden = true;
      $('uq-status').hidden = !data.answer_expired;
      if (data.answer_expired) $('uq-status').textContent = 'Le délai était écoulé à la réception de la réponse précédente.';
      show(data, observedAt);
    } catch(error) {
      failed = true;
      $('uq-status').hidden = true;
      const message = error.name === 'AbortError' ? 'Le serveur met du temps à répondre.' : error.message;
      $('uq-error-text').textContent = pending
        ? message + ' Votre choix est conservé. Cliquez sur « Réessayer » pour le renvoyer.'
        : message;
      $('uq-error').hidden = false;
    } finally {
      clearTimeout(timeout); busy = false;
      start.disabled = failed || !!pending || !$('uq-in-class').checked;
      $('uq-options').disabled = !!pending;
      if (state?.started) next.textContent = state.index === state.total ? 'Terminer et voir la correction →' : 'Valider et continuer →';
      next.disabled = failed || !!pending || !document.querySelector('#uq-options input:checked') || performance.now() >= deadline;
    }
  }
  $('uq-in-class').addEventListener('change', () => { start.disabled = busy || failed || !!pending || !$('uq-in-class').checked; });
  start.addEventListener('click', () => { if ($('uq-in-class').checked) send('start', {in_class:'yes'}); });
  $('uq-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (busy || failed || pending || !state?.question) return;
    const chosen = document.querySelector('#uq-options input:checked');
    if (performance.now() >= deadline) {
      send('sync', {question_id: state.question.id});
    } else if (chosen) {
      remember({question_id: state.question.id, answer: chosen.value});
      send('answer', pending);
    }
  });
  function resume() {
    if (pending) send('answer', pending);
    else send('sync', state?.question ? {question_id: state.question.id} : {});
  }
  $('uq-retry').addEventListener('click', resume);
  window.addEventListener('online', () => { if (failed) resume(); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (failed || pending) resume();
    else if (state?.started) tick();
  });
  resume();
})();
