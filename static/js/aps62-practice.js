(() => {
  'use strict';
  const root = document.querySelector('[data-aps-practice]');
  if (!root) return;
  const config = JSON.parse(document.getElementById('apsPracticeConfig').textContent);
  const preview = Boolean(document.getElementById('nativePreviewConfig'));
  const access = JSON.parse(document.getElementById(preview ? 'nativePreviewConfig' : 'nativeElearningConfig').textContent);
  const form = root.querySelector('form');
  const check = root.querySelector('.aps-practice-check');
  const restart = root.querySelector('.aps-practice-restart');
  const summary = root.querySelector('[data-practice-result]');
  const draft = root.querySelector('[data-practice-draft]');
  const exercises = [...root.querySelectorAll('[data-exercise-id]')];
  const key = `aps62-practice:${location.pathname}:${config.courseVersion}:${config.activityId}:${config.practice.revision}`;
  let verified = '', busy = false;

  function collect(requireAll = true) {
    const answers = {};
    for (const element of exercises) {
      const id = element.dataset.exerciseId;
      if (element.dataset.kind === 'single') {
        answers[id] = element.querySelector('input:checked')?.value || '';
        if (requireAll && !answers[id]) throw new Error('Sélectionnez une réponse dans chaque question.');
      } else {
        const values = [...element.querySelectorAll('select')];
        answers[id] = Object.fromEntries(values.map(field => [field.dataset.rowId, field.value]));
        if (requireAll && values.some(field => !field.value)) throw new Error('Complétez chaque carte avant de vérifier.');
        if (requireAll && ['order', 'matching'].includes(element.dataset.kind)
          && new Set(values.map(field => field.value)).size !== values.length) {
          throw new Error('Utilisez chaque étape ou association une seule fois.');
        }
      }
    }
    return answers;
  }

  function restore(answers) {
    if (!answers || typeof answers !== 'object') return;
    for (const element of exercises) {
      const answer = answers[element.dataset.exerciseId];
      element.querySelectorAll('input[type=radio]').forEach(field => { field.checked = field.value === answer; });
      element.querySelectorAll('select').forEach(field => {
        const value = answer && typeof answer === 'object' ? answer[field.dataset.rowId] : '';
        field.value = [...field.options].some(option => option.value === value) ? value : '';
      });
    }
  }

  function clearDraft() {
    try { sessionStorage.removeItem(key); } catch (_) { /* optional local cache */ }
  }

  function clearFeedback() {
    verified = '';
    summary.textContent = '';
    delete summary.dataset.correct;
    exercises.forEach(element => {
      delete element.dataset.correct;
      element.querySelector('[data-exercise-feedback]').hidden = true;
    });
  }

  function saveDraft(event) {
    verified = '';
    summary.textContent = 'Choix modifié. Vérifiez à nouveau vos réponses.';
    delete summary.dataset.correct;
    const changed = event.target.closest('[data-exercise-id]');
    if (changed) {
      delete changed.dataset.correct;
      changed.querySelector('[data-exercise-feedback]').hidden = true;
    }
    if (preview || config.completed) return;
    try {
      sessionStorage.setItem(key, JSON.stringify(collect(false)));
      draft.textContent = 'Choix conservés dans cet onglet. Vérifiez-les avant de terminer l’activité.';
    } catch (_) { draft.textContent = 'Terminez l’activité pour enregistrer vos choix.'; }
  }

  function render(result) {
    for (const item of result.feedback) {
      const element = exercises.find(ex => ex.dataset.exerciseId === item.id);
      if (!element) continue;
      element.dataset.correct = String(item.correct);
      const box = element.querySelector('[data-exercise-feedback]');
      box.replaceChildren();
      const label = document.createElement('strong');
      label.textContent = item.correct ? '✓ Bien joué' : 'À revoir';
      const explanation = document.createElement('p');
      explanation.textContent = item.explanation;
      box.append(label, explanation);
      if (!item.correct) {
        const heading = document.createElement('strong');
        heading.textContent = 'La correction';
        const list = document.createElement('ul');
        for (const text of item.correction) {
          const line = document.createElement('li'); line.textContent = text; list.append(line);
        }
        box.append(heading, list);
      }
      box.hidden = false;
    }
    summary.dataset.correct = String(result.correct);
    summary.textContent = `${result.passed} exercice${result.passed > 1 ? 's' : ''} réussi${result.passed > 1 ? 's' : ''} sur ${result.total}. `
      + (result.correct ? (preview ? 'Atelier réussi. Vous pouvez recommencer librement.' : 'Vous pouvez terminer l’activité et continuer.')
        : 'Consultez les corrections, modifiez vos choix et vérifiez à nouveau.');
  }

  async function verify(event) {
    event.preventDefault();
    if (busy || check.disabled) return;
    let answers;
    try { answers = collect(); }
    catch (error) { summary.textContent = error.message; summary.dataset.correct = 'false'; return; }
    busy = true;
    const controls = [...form.querySelectorAll('input,select,button')];
    const previous = controls.map(field => field.disabled);
    controls.forEach(field => { field.disabled = true; });
    check.textContent = 'Vérification…';
    try {
      const response = await fetch(preview ? access.answerUrl : access.practiceUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Elearning-CSRF': access.csrfToken},
        body: JSON.stringify({practice_answers: answers, ...(!preview ? {access_token: access.accessToken} : {})}),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || 'Impossible de vérifier vos réponses. Réessayez.');
      render(result);
      verified = result.correct ? JSON.stringify(answers) : '';
    } catch (error) {
      verified = '';
      summary.dataset.correct = 'false';
      summary.textContent = error.message || 'La connexion a été interrompue. Vos choix sont conservés ; réessayez.';
    } finally {
      busy = false;
      controls.forEach((field, i) => { field.disabled = previous[i]; });
      check.textContent = 'Vérifier mes réponses';
    }
  }

  restore(config.savedAnswers);
  if (!preview && !config.completed) {
    try { restore(JSON.parse(sessionStorage.getItem(key) || 'null')); } catch (_) { /* ignore invalid local drafts */ }
  }
  if (config.completed) clearDraft();
  form.addEventListener('submit', verify);
  form.addEventListener('change', saveDraft);
  restart.addEventListener('click', () => {
    if (busy) return;
    form.reset(); clearFeedback(); clearDraft();
    summary.textContent = 'À vous de jouer : tous les choix ont été réinitialisés.';
    if (!preview && !config.completed) draft.textContent = 'Vos réponses seront enregistrées lorsque vous terminerez l’activité.';
  });
  window.aps62Practice = {
    clearDraft,
    collectForCompletion() {
      const answers = collect();
      if (busy || verified !== JSON.stringify(answers)) throw new Error('Vérifiez les exercices et corrigez les choix à revoir avant de continuer.');
      return answers;
    },
  };
})();
