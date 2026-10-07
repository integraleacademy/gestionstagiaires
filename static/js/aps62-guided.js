(() => {
  'use strict';
  const script = document.getElementById('apsPracticeConfig');
  if (!script) return;
  const config = JSON.parse(script.textContent);
  if (config.practice.mode !== 'guided') return;
  const root = document.querySelector('[data-aps-practice]');
  const preview = Boolean(document.getElementById('nativePreviewConfig'));
  const access = JSON.parse(document.getElementById(preview ? 'nativePreviewConfig' : 'nativeElearningConfig').textContent);
  const form = root.querySelector('form');
  const fields = [...form.querySelectorAll('[data-exercise-id]')];
  const check = root.querySelector('.aps-practice-check');
  const next = root.querySelector('.aps-guided-next');
  const restart = root.querySelector('.aps-practice-restart');
  const summary = root.querySelector('[data-practice-result]');
  const status = root.querySelector('[data-stage-status]');
  const draft = root.querySelector('[data-practice-draft]');
  const cacheKey = `aps62-guided:${location.pathname}:${config.courseVersion}:${config.activityId}`;
  let index = 0, busy = false, verified = '', stepVerified = false;
  const drills = new Map();

  function answers() {
    return Object.fromEntries(fields.map(field => [field.dataset.exerciseId,
      field.dataset.kind === 'single' ? field.querySelector('input:checked')?.value || '' :
        Object.fromEntries([...field.querySelectorAll('select')].map(select => [select.dataset.rowId, select.value]))]));
  }
  function complete(value) {
    return typeof value === 'string' ? Boolean(value) : Object.values(value).every(Boolean);
  }
  function updateJournal() {
    const journal = root.querySelector('[data-journal-preview]');
    if (!journal) return;
    journal.replaceChildren();
    fields.forEach((field, n) => {
      const title = document.createElement('dt'); title.textContent = config.practice.exercises[n].prompt;
      const text = document.createElement('dd');
      text.textContent = field.querySelector('input:checked')?.nextElementSibling?.textContent || 'À compléter';
      journal.append(title, text);
    });
  }
  function show(focus = false) {
    fields.forEach((field, n) => { field.hidden = n !== index; });
    status.textContent = `Question ${index + 1} sur ${fields.length}`;
    check.hidden = stepVerified || Boolean(verified);
    next.hidden = !stepVerified || Boolean(verified);
    next.textContent = index + 1 === fields.length ? 'Valider l’exercice' : 'Question suivante →';
    if (focus) fields[index].querySelector('legend').focus();
  }
  function clearDraft() { try { sessionStorage.removeItem(cacheKey); } catch (_) {} }
  function restore(data) {
    if (!data || typeof data !== 'object') return;
    fields.forEach(field => {
      const value = data[field.dataset.exerciseId];
      field.querySelectorAll('input').forEach(input => { input.checked = input.value === value; });
      field.querySelectorAll('select').forEach(select => {
        const selected = value && typeof value === 'object' ? value[select.dataset.rowId] : '';
        select.value = [...select.options].some(option => option.value === selected) ? selected : '';
      });
    });
  }
  async function request(payload) {
    const response = await fetch(preview ? access.answerUrl : access.practiceUrl, {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type':'application/json', 'Accept':'application/json', 'X-Elearning-CSRF':access.csrfToken},
      body: JSON.stringify({...payload, ...(!preview ? {access_token:access.accessToken} : {})}),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'La vérification a échoué. Réessayez.');
    return result;
  }
  async function lock(action) {
    if (busy) return;
    busy = true;
    const controls = [...root.querySelectorAll('input,select,button')];
    const previous = controls.map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    try { await action(); }
    catch (error) { summary.textContent = error.message || 'Connexion interrompue. Votre choix est conservé. Réessayez.'; summary.dataset.correct = 'false'; }
    finally { busy = false; controls.forEach((control, n) => { control.disabled = previous[n]; }); }
  }
  function feedback(item) {
    const field = fields[index], box = field.querySelector('[data-exercise-feedback]');
    field.dataset.correct = String(item.correct);
    box.replaceChildren();
    const heading = document.createElement('strong');
    heading.textContent = item.correct ? '✓ C’est la bonne réponse.' : 'Reprenons ensemble.';
    const explanation = document.createElement('p'); explanation.textContent = item.explanation;
    box.append(heading, explanation);
    if (!item.correct) {
      const answer = document.createElement('p'); answer.textContent = 'La réponse à choisir : ' + item.correction.join(' ; ');
      const instruction = document.createElement('p'); instruction.textContent = 'Cliquez maintenant sur cette réponse, puis vérifiez à nouveau.';
      box.append(answer, instruction);
    }
    box.hidden = false;
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (busy || check.disabled) return;
    const id = fields[index].dataset.exerciseId, value = answers()[id];
    if (!complete(value)) { summary.textContent = 'Cliquez sur une réponse avant de vérifier.'; return; }
    lock(async () => {
      const result = await request({practice_step:id, practice_answers:{[id]:value}});
      feedback(result.feedback[0]);
      (result.review || []).forEach(drill => drills.set(drill.id, drill));
      stepVerified = result.correct;
      summary.textContent = result.correct ? 'Lisez la correction, puis passez à la suite.' : 'Vous pouvez réessayer. La correction est juste au-dessus.';
      summary.dataset.correct = String(result.correct);
      show();
    });
  });
  next.addEventListener('click', () => {
    if (busy || !stepVerified) return;
    if (index + 1 < fields.length) {
      index++; stepVerified = false; summary.textContent = ''; show(true); return;
    }
    lock(async () => {
      const all = answers();
      const result = await request({practice_answers:all});
      if (!result.correct) {
        index = fields.findIndex(field => field.dataset.exerciseId === result.feedback.find(item => !item.correct).id);
        stepVerified = false; feedback(result.feedback.find(item => !item.correct)); show(true); return;
      }
      verified = JSON.stringify(all);
      summary.dataset.correct = 'true';
      summary.textContent = preview ? '✓ Exercice réussi. Vous pouvez le recommencer.' : '✓ Exercice réussi. Cliquez sur « Terminer l’activité » pour continuer.';
      show(); showReview();
    });
  });
  function showReview() {
    const review = root.querySelector('[data-remediation]');
    if (!review || !drills.size) return;
    review.hidden = false;
    review.querySelector('h3').textContent = 'Un autre exemple pour s’entraîner';
    review.querySelector('p').textContent = 'Facultatif : ces exemples reprennent les points qui vous ont posé difficulté.';
    const items = review.querySelector('[data-remediation-items]'); items.replaceChildren();
    [...drills.values()].forEach(drill => {
      const details = document.createElement('details');
      const title = document.createElement('summary'); title.textContent = 'Ouvrir un nouvel exemple';
      const lesson = document.createElement('p'); lesson.textContent = drill.lesson;
      const field = document.createElement('fieldset'); field.dataset.reviewId = drill.id;
      const legend = document.createElement('legend'); legend.textContent = drill.prompt; field.append(legend);
      drill.options.forEach(option => {
        const label = document.createElement('label'), input = document.createElement('input');
        input.type = 'radio'; input.name = `review-${drill.id}`; input.value = option.id;
        label.append(input, document.createTextNode(option.text)); field.append(label);
      });
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Vérifier cet exemple';
      const resultText = document.createElement('p'); resultText.setAttribute('role','status');
      button.addEventListener('click', () => {
        const selected = field.querySelector('input:checked');
        if (!selected) { resultText.textContent = 'Choisissez une réponse.'; return; }
        lock(async () => {
          const result = await request({practice_answers:answers(), review_answers:{[drill.id]:selected.value}});
          const item = result.review.find(item => item.id === drill.id);
          resultText.textContent = (item.correct ? '✓ Bonne réponse. ' : 'À revoir. ') + item.explanation;
        });
      });
      details.append(title, lesson, field, button, resultText); items.append(details);
    });
    review.querySelector('.aps-practice-review').hidden = true;
  }
  form.addEventListener('change', () => {
    updateJournal();
    stepVerified = false; verified = '';
    fields[index].querySelector('[data-exercise-feedback]').hidden = true;
    delete fields[index].dataset.correct;
    summary.textContent = ''; show();
    if (!preview && !config.completed) {
      try { sessionStorage.setItem(cacheKey, JSON.stringify(answers())); draft.textContent = 'Votre choix est conservé dans cet onglet.'; } catch (_) {}
    }
  });
  restart.addEventListener('click', () => {
    if (busy) return;
    form.reset(); index = 0; stepVerified = false; verified = ''; drills.clear(); clearDraft();
    fields.forEach(field => { delete field.dataset.correct; field.querySelector('[data-exercise-feedback]').hidden = true; });
    root.querySelector('[data-remediation]').hidden = true;
    summary.textContent = ''; updateJournal(); show(true);
  });
  restore(config.savedAnswers);
  if (!preview && !config.completed) { try { restore(JSON.parse(sessionStorage.getItem(cacheKey) || 'null')); } catch (_) {} }
  if (config.completed) clearDraft();
  updateJournal(); show();
  window.aps62Practice = {clearDraft, collectForCompletion() {
    const all = answers();
    if (busy || !verified || verified !== JSON.stringify(all)) throw new Error('Terminez les questions, puis cliquez sur « Valider l’exercice ».');
    return all;
  }};
})();
