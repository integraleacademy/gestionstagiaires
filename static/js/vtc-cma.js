(() => {
  'use strict';
  const configNode = document.getElementById('cmaConfig');
  if (!configNode) return;
  const config = JSON.parse(configNode.textContent), bank = config.bank;
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const number = value => value == null ? 'En attente' : new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(value);
  const subjectInfo = id => bank.subjects.find(s => s.id === id);
  const subjectsToGrade = result => [...new Set([...(result.pending_subjects || []), ...(result.review_subjects || [])])];
  let state = null, paper = null, answers = {}, position = 0, revision = 0;
  let generation = 0, savedGeneration = 0, saveTimer, saveChain = Promise.resolve(), saving = 0;
  let submitting = false, controlling = false, conflicted = false, grading = false, autoGraded = false;
  let clockSync = 0, wallClockSync = 0, timeAtSync = 0, expiryCheck = -Infinity;
  let expired = false, expiryRefreshing = false;

  function error(message) { $('cmaError').textContent = message; $('cmaError').hidden = !message; }
  function visible(id) {
    ['cmaLanding', 'cmaPaper', 'cmaBetween', 'cmaResult'].forEach(name => { $(name).hidden = name !== id; });
    document.body.classList.toggle('cma-exam-running', id === 'cmaPaper');
  }
  async function request(url, data) {
    const options = {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}};
    if (data !== undefined) Object.assign(options, {method: 'POST', headers: {...options.headers, 'Content-Type': 'application/json', 'X-Elearning-CSRF': config.csrfToken}, body: JSON.stringify(data)});
    let response, body;
    const controller = new AbortController(); options.signal = controller.signal;
    const timeout = setTimeout(() => controller.abort(), /\/(grade|correct)$/.test(url) ? 120000 : 20000);
    try {
      response = await fetch(url, options);
      const parsed = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : {};
      body = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
      throw new Error('La connexion a été interrompue. Vos réponses enregistrées sont conservées. Réessayez dans quelques instants.');
    } finally {
      clearTimeout(timeout);
    }
    if (!response.ok || !body.ok) {
      const ex = new Error(body.error || ([401, 403].includes(response.status) ? 'Votre accès a expiré ou n’est plus autorisé. Revenez au parcours pour vous reconnecter.' : 'La connexion a été interrompue. Votre dernière sauvegarde serveur est conservée. Réessayez.'));
      ex.code = body.code; ex.state = body.state; throw ex;
    }
    return body;
  }
  function remainingSeconds() {
    if (!paper || config.preview) return null;
    const part = state?.parts.find(p => p.subject === paper.id);
    if (part?.status === 'paused') return Math.max(0, Math.ceil(part.remaining_seconds));
    if (!part || part.status !== 'running') return 0;
    // A monotonic clock prevents a backwards clock adjustment from adding time;
    // wall time also counts suspension on platforms that pause performance.now().
    const elapsed = Math.max(0, performance.now() - clockSync, Date.now() - wallClockSync);
    return Math.max(0, Math.ceil((part.deadline * 1000 - timeAtSync - elapsed) / 1000));
  }
  function isPaused() { return !config.preview && state?.parts.find(p => p.subject === paper?.id)?.status === 'paused'; }
  function paperLocked() { return submitting || controlling || isPaused() || conflicted || expired || (!config.preview && remainingSeconds() === 0); }
  function updateControls() {
    const paused = isPaused(), busy = submitting || controlling || conflicted || expired || (!config.preview && remainingSeconds() === 0);
    $('cmaPause').hidden = config.preview;
    $('cmaPause').textContent = controlling ? 'Enregistrement…' : paused ? 'Reprendre' : 'Mettre en pause';
    $('cmaPause').disabled = $('cmaReset').disabled = $('cmaConfirmReset').disabled = busy;
    $('cmaPausedInfo').hidden = !paused;
    $('cmaWorkspace').hidden = paused;
    $('cmaClockLabel').textContent = config.preview ? 'Durée de l’épreuve' : paused ? 'Temps conservé' : 'Temps restant';
    $('cmaClockDetail').textContent = config.preview ? 'Sans décompte' : `sur ${paper.minutes} min${paused ? ' · en pause' : ''}`;
    $('cmaQuestion').disabled = $('cmaSubmit').disabled = $('cmaConfirmSubmit').disabled = $('cmaSaveNow').disabled = paperLocked();
  }
  function cancelAutosave() { clearTimeout(saveTimer); saveTimer = null; }
  function answered(q) { return q.kind === 'qrc' ? !!(answers[q.id] || '').trim() : !!answers[q.id]?.length; }
  function progress() {
    if (!paper) return;
    const count = paper.questions.filter(answered).length;
    $('cmaAnswered').textContent = `${count} / ${paper.questions.length} réponses renseignées`;
    $('cmaProgress').max = paper.questions.length; $('cmaProgress').value = count;
    Array.from($('cmaQuestionGrid').children).forEach((button, index) => {
      button.classList.toggle('is-answered', answered(paper.questions[index]));
      button.classList.toggle('is-current', index === position);
      button.setAttribute('aria-current', index === position ? 'step' : 'false');
      button.setAttribute('aria-label', `Question ${index + 1}, ${answered(paper.questions[index]) ? 'renseignée' : 'sans réponse'}`);
    });
  }
  function dirty() {
    generation++; progress(); $('cmaConfirm').hidden = true;
    if (config.preview) { $('cmaSaved').textContent = 'Aperçu : réponses conservées uniquement dans cette page.'; return; }
    $('cmaSaved').textContent = 'Modifications en attente d’enregistrement…';
    // Save throughout continuous typing, rather than waiting for a pause that
    // may never happen. Send the last keystrokes immediately near the deadline.
    if (remainingSeconds() <= 2) { cancelAutosave(); void queueSave(); }
    else if (!saveTimer) saveTimer = setTimeout(() => { saveTimer = null; void queueSave(); }, 700);
  }
  function renderQuestion(focus = false) {
    const q = paper.questions[position], field = $('cmaQuestion'); field.replaceChildren();
    const legend = el('legend', q.prompt); legend.tabIndex = -1; field.append(legend);
    $('cmaQuestionMeta').textContent = `Question ${position + 1} / ${paper.questions.length} · ${q.kind.toUpperCase()} · ${number(q.max_points)} point${q.max_points > 1 ? 's' : ''}`;
    if (q.kind === 'qrc') {
      const instruction = el('p', 'Rédigez une réponse courte avec vos propres mots. Pour un calcul, montrez les étapes.', 'cma-note');
      instruction.id = 'cmaWritingInstruction';
      const textarea = el('textarea'); textarea.id = 'cmaWrittenAnswer'; textarea.name = q.id;
      textarea.maxLength = q.max_chars; textarea.value = answers[q.id] || ''; textarea.spellcheck = false;
      textarea.setAttribute('aria-label', `Votre réponse à la question ${position + 1}`); textarea.setAttribute('aria-describedby', instruction.id);
      const count = el('p', `${textarea.value.length} / ${q.max_chars} caractères`, 'cma-count');
      textarea.addEventListener('input', () => { if (paperLocked()) return; answers[q.id] = textarea.value; count.textContent = `${textarea.value.length} / ${q.max_chars} caractères`; dirty(); });
      field.append(instruction, textarea, count);
    } else {
      field.append(el('p', q.multiple ? 'Cochez toutes les bonnes réponses. L’ensemble exact est attendu.' : 'Sélectionnez une seule réponse.', 'cma-note'));
      q.options.forEach((option, index) => {
        const label = el('label', undefined, 'cma-option'), input = el('input');
        input.type = q.multiple ? 'checkbox' : 'radio'; input.name = q.id; input.value = option.id;
        input.checked = (answers[q.id] || []).includes(option.id);
        input.addEventListener('change', () => { if (paperLocked()) return; answers[q.id] = q.multiple ? Array.from(field.querySelectorAll('input:checked')).map(n => n.value) : [option.id]; dirty(); });
        label.append(input, el('span', `${String.fromCharCode(65 + index)}. ${option.text}`)); field.append(label);
      });
      const clear = el('button', 'Effacer mon choix', 'cma-secondary'); clear.type = 'button';
      clear.addEventListener('click', () => { if (paperLocked()) return; answers[q.id] = []; dirty(); renderQuestion(); }); field.append(clear);
    }
    $('cmaPrevious').disabled = position === 0; $('cmaNext').disabled = position === paper.questions.length - 1;
    field.disabled = paperLocked(); progress(); if (focus) legend.focus();
  }
  function renderPaper(nextPaper, copy, fresh = true) {
    visible('cmaPaper'); paper = nextPaper;
    if (fresh) { cancelAutosave(); answers = copy || {}; position = 0; generation = savedGeneration = 0; conflicted = expired = false; expiryCheck = -Infinity; }
    $('cmaSubjectTitle').textContent = `${paper.id} · ${paper.title}`;
    $('cmaSubjectMeta').textContent = `${paper.minutes} min · coefficient ${paper.coefficient} · minimum ${paper.minimum}/20`;
    $('cmaPreviewSelect').hidden = !config.preview; $('cmaSubjectSelect').value = paper.id;
    $('cmaClockLabel').textContent = config.preview ? 'Durée de l’épreuve' : 'Temps restant';
    $('cmaExamStage').textContent = config.preview ? 'Exploration libre · sans décompte' : `Épreuve ${bank.subjects.findIndex(s => s.id === paper.id) + 1} / ${bank.subjects.length} · Examen en conditions réelles`;
    $('cmaTimeProgress').hidden = config.preview;
    $('cmaSubjectSteps').replaceChildren();
    bank.subjects.forEach(subject => {
      const status = state?.parts.find(p => p.subject === subject.id)?.status;
      const done = !config.preview && ['submitted', 'expired'].includes(status);
      const step = el('li', undefined, done ? 'is-done' : subject.id === paper.id ? 'is-active' : '');
      if (subject.id === paper.id) step.setAttribute('aria-current', 'step');
      step.append(el('strong', `${done ? '✓ ' : ''}${subject.id}`), el('span', `${subject.minutes} min`));
      step.setAttribute('aria-label', `${subject.id} · ${subject.title} · ${done ? 'copie remise' : subject.id === paper.id ? 'en cours' : 'à venir'}`);
      $('cmaSubjectSteps').append(step);
    });
    $('cmaSubmit').textContent = config.preview ? 'Corriger cette matière · aperçu' : 'Valider mes réponses';
    $('cmaSaveNow').hidden = config.preview;
    $('cmaPassage').hidden = !paper.passage_lines;
    $('cmaPassageTitle').textContent = paper.passage_title || '';
    $('cmaPassageLines').replaceChildren();
    (paper.passage_lines || []).forEach(line => $('cmaPassageLines').append(el('li', line)));
    const grid = $('cmaQuestionGrid'); grid.replaceChildren();
    paper.questions.forEach((q, i) => { const b = el('button', String(i + 1)); b.type = 'button'; b.addEventListener('click', () => { position = i; renderQuestion(true); }); grid.append(b); });
    $('cmaSaved').textContent = config.preview ? 'Aperçu sans enregistrement stagiaire.' : 'Copie synchronisée avec le serveur.';
    $('cmaConfirm').hidden = $('cmaResetConfirm').hidden = true;
    $('cmaSubmit').disabled = $('cmaConfirmSubmit').disabled = $('cmaSaveNow').disabled = false;
    renderQuestion(); updateClock();
    if (fresh) { $('cmaSubjectTitle').focus({preventScroll: true}); $('cmaPaper').scrollIntoView?.({block: 'start'}); }
  }
  function applyState(next, preserveDraft = false) {
    const oldPaper = paper?.id, wasPaused = isPaused();
    if (state?.id === next.id && next.server_now < state.server_now) return;
    config.preview = false;
    state = next; clockSync = performance.now(); wallClockSync = Date.now(); timeAtSync = next.server_now * 1000;
    if (state.id) history.replaceState(null, '', `${config.homeUrl}?attempt=${encodeURIComponent(state.id)}`);
    if (state.status === 'submitted') {
      paper = null; cancelAutosave(); renderResults(state.result);
      if (!autoGraded && config.aiAvailable && subjectsToGrade(state.result).length) { autoGraded = true; void gradePending(); }
      return;
    }
    if (state.paper) {
      const part = state.parts.find(p => p.subject === state.current_subject);
      revision = part.revision;
      if (preserveDraft && oldPaper === state.paper.id && wasPaused === isPaused()) { updateClock(); return; }
      renderPaper(state.paper, state.answers); return;
    }
    paper = null; cancelAutosave(); generation = savedGeneration = 0;
    visible('cmaBetween'); const panel = $('cmaBetween'); panel.replaceChildren();
    const nextInfo = subjectInfo(state.current_subject), previous = state.parts.filter(p => ['submitted', 'expired'].includes(p.status));
    panel.append(el('p', 'COPIE ENREGISTRÉE', 'cma-eyebrow'), el('h2', `Prêt pour la matière ${nextInfo.id} ?`));
    if (previous.at(-1)?.status === 'expired') panel.append(el('p', 'Le temps de la matière précédente est écoulé. Les réponses enregistrées avant l’échéance ont été remises automatiquement.', 'cma-alert'));
    panel.append(el('p', `${nextInfo.title} · ${nextInfo.minutes} minutes · coefficient ${nextInfo.coefficient}. Son chronomètre démarre uniquement lorsque vous cliquez ci-dessous.`));
    const list = el('ul', undefined, 'cma-status-list'); previous.forEach(p => list.append(el('li', `${p.subject} · ${p.status === 'expired' ? 'temps écoulé' : 'remise'}`))); panel.append(list);
    const start = el('button', `Démarrer la matière ${nextInfo.id}`, 'cma-primary'); start.type = 'button';
    start.addEventListener('click', async () => { start.disabled = true; error(''); try { const data = await request(state.urls.start_part, {version: state.version, subject: nextInfo.id}); applyState(data.state); } catch (ex) { error(ex.message); start.disabled = false; } });
    panel.append(start, el('p', 'Vous pouvez faire une pause ici. Les corrigés seront disponibles après la septième matière.', 'cma-note')); panel.focus();
  }
  async function performSave(submit = false) {
    if (config.preview || !paper || isPaused() || conflicted || (!submit && generation === savedGeneration)) return true;
    if (expired || remainingSeconds() === 0) { updateClock(); return false; }
    saving++; const sentGeneration = generation, sentSubject = paper.id, sentAnswers = JSON.parse(JSON.stringify(answers));
    try {
      const data = await request(submit ? state.urls.submit : state.urls.save, {version: state.version, subject: sentSubject, revision, answers: sentAnswers});
      savedGeneration = sentGeneration;
      applyState(data.state, !submit && data.state.paper?.id === sentSubject);
      if (paper?.id === sentSubject) $('cmaSaved').textContent = generation === savedGeneration ? `Enregistré à ${new Date().toLocaleTimeString('fr-FR')}.` : 'Dernière copie enregistrée ; nouvelles modifications en attente…';
      return true;
    } catch (ex) {
      if (ex.code === 'revision_conflict') { conflicted = true; $('cmaQuestion').disabled = true; }
      error(ex.message); $('cmaSaved').textContent = 'Enregistrement non confirmé. Gardez cette page ouverte.'; return false;
    } finally { saving--; }
  }
  function queueSave(submit = false) { saveChain = saveChain.catch(() => false).then(() => performSave(submit)); return saveChain; }
  async function controlPaper(action) {
    if (!paper || controlling || submitting || conflicted || expired || (!config.preview && remainingSeconds() === 0)) return;
    if (config.preview) { if (action === 'reset') renderPaper(paper, {}); return; }
    controlling = true; cancelAutosave(); error(''); updateControls();
    const subject = paper.id, oldPosition = position;
    $('cmaConfirm').hidden = true;
    try {
      // Finish any in-flight autosave before using its new revision. Pausing
      // then commits the latest draft and the frozen clock together.
      await saveChain;
      if (!paper || paper.id !== subject || conflicted || expired) return;
      const data = await request(state.urls[action], {version: state.version, subject, revision,
        ...(action === 'pause' ? {answers: JSON.parse(JSON.stringify(answers))} : {})});
      applyState(data.state);
      if (paper?.id === subject && action !== 'reset') { position = oldPosition; renderQuestion(); }
      $('cmaResetConfirm').hidden = true;
    } catch (ex) {
      if (ex.code === 'revision_conflict') conflicted = true;
      error(ex.message);
    } finally {
      controlling = false;
      if (paper) { updateClock(); $('cmaPause').focus({preventScroll: true}); }
    }
  }
  async function refreshState() {
    if (!state || config.preview || saving || generation !== savedGeneration || submitting || controlling || conflicted) return;
    try {
      const data = await request(state.urls.state);
      const part = data.state.parts.find(p => p.subject === paper?.id);
      if (paper && part?.status === 'running' && part.revision !== revision) {
        conflicted = true; $('cmaQuestion').disabled = true;
        error('Cette tentative a été modifiée dans une autre page. Rechargez pour reprendre la dernière sauvegarde.'); return;
      }
      applyState(data.state, data.state.paper?.id === paper?.id);
    } catch (ex) { error(ex.message); }
  }
  function updateClock() {
    if (!paper) return;
    updateControls();
    if (config.preview) {
      $('cmaClock').textContent = `${paper.minutes} min`;
      $('cmaClockBox').classList.remove('is-urgent', 'is-critical');
      $('cmaTimeNotice').textContent = 'Exploration libre : le chronomètre est désactivé.';
      $('cmaTimeNotice').className = 'cma-time-notice'; return;
    }
    const remaining = remainingSeconds();
    $('cmaClock').textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
    $('cmaClockBox').classList.toggle('is-urgent', !isPaused() && remaining <= 300);
    $('cmaClockBox').classList.toggle('is-critical', !isPaused() && remaining <= 60);
    $('cmaTimeProgress').max = paper.minutes * 60; $('cmaTimeProgress').value = remaining;
    if (isPaused()) {
      $('cmaTimeNotice').textContent = 'Chronomètre en pause. Reprenez quand vous êtes prêt : le temps restant est conservé.';
      $('cmaTimeNotice').className = 'cma-time-notice is-paused'; return;
    }
    const message = !remaining ? 'Temps écoulé. Remise automatique de la copie enregistrée…' : remaining <= 60 ? 'Dernière minute : terminez votre réponse. La copie sera remise automatiquement.' : remaining <= 300 ? 'Il reste 5 minutes ou moins. Relisez votre copie et vérifiez les réponses manquantes.' : 'Pour revenir plus tard, cliquez sur « Mettre en pause » avant de quitter cette page.';
    if ($('cmaTimeNotice').textContent !== message) $('cmaTimeNotice').textContent = message;
    $('cmaTimeNotice').className = `cma-time-notice${remaining <= 60 ? ' is-critical' : remaining <= 300 ? ' is-urgent' : ''}`;
    if (!remaining) {
      expired = true; cancelAutosave(); $('cmaConfirm').hidden = true;
      $('cmaQuestion').disabled = $('cmaSubmit').disabled = $('cmaConfirmSubmit').disabled = $('cmaSaveNow').disabled = true;
    }
    if (!remaining && !controlling && !expiryRefreshing && performance.now() - expiryCheck >= 5000) {
      expiryCheck = performance.now(); expiryRefreshing = true;
      // No late client answers are sent: the server locks its last saved draft.
      request(state.urls.state).then(data => { error(''); applyState(data.state); }).catch(ex => error(ex.message)).finally(() => { expiryRefreshing = false; });
    }
  }
  function lessonLinks(links) {
    const box = el('div', undefined, 'cma-links');
    (links || []).forEach(link => { const a = el('a', `Revoir ${link.ref}`); a.href = link.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; box.append(a); }); return box;
  }
  function correctionCard(q) {
    const box = el('details', undefined, `cma-correction ${q.points != null && q.points < q.max_points ? 'is-low' : ''}`);
    box.append(el('summary', `${q.points == null ? 'Correction en attente' : `${number(q.points)} / ${q.max_points}`} · ${q.kind.toUpperCase()} · ${q.prompt}`));
    const body = el('div', undefined, 'cma-correction-body');
    if (q.kind === 'qcm') {
      const list = el('ul'); q.options.forEach(o => list.append(el('li', `${o.text}${q.answers.includes(o.id) ? ' — réponse attendue' : ''}${q.selected.includes(o.id) ? ' — votre choix' : ''}`, q.answers.includes(o.id) ? 'cma-grade-good' : ''))); body.append(list, el('p', q.explanation));
    } else {
      body.append(el('h3', 'Votre réponse'), el('p', q.selected || 'Aucune réponse remise.', 'cma-copy'));
      q.criteria.forEach(c => {
        const criterion = el('div', undefined, 'cma-criterion');
        criterion.append(el('strong', `${c.label} · ${number(c.points)} / ${number(c.max_points)}`));
        if (c.feedback) criterion.append(el('p', c.feedback));
        criterion.append(el('p', `Attendu : ${c.expected}`));
        if (c.improvement) criterion.append(el('p', `À améliorer : ${c.improvement}`));
        criterion.append(el('p', `Barème : ${c.partial_guidance}`, 'cma-note')); body.append(criterion);
      });
      body.append(el('h3', 'Exemple de réponse attendue'), el('p', q.model_response, 'cma-model'));
    }
    body.append(lessonLinks(q.lesson_links));
    if (q.origin) body.append(el('p', q.origin, 'cma-note'));
    (q.sources || []).forEach(source => { if (!/^https:\/\//.test(source.url)) return; const p = el('p', undefined, 'cma-note'), a = el('a', source.title); a.href = source.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(a); body.append(p); });
    box.append(body); return box;
  }
  function subjectResult(row) {
    const box = el('section', undefined, 'cma-card');
    const verified = row.status === 'corrected', score = verified ? row.score : null;
    box.append(el('p', `MATIÈRE ${row.subject} · COEFFICIENT ${row.coefficient}`, 'cma-eyebrow'), el('h2', `${row.title} · ${number(score)}${score == null ? '' : ' / 20'}`));
    box.append(el('p', `QCM : ${number(row.qcm_score)} points · QRC : ${number(verified ? row.qrc_score : null)} points · Minimum : ${row.minimum}/20`));
    if (row.status === 'needs_human_review') {
      box.append(el('p', 'Une analyse complémentaire de vos réponses est nécessaire pour finaliser cette correction. Elle se lance à l’ouverture du bilan ; vous pouvez aussi la reprendre avec le bouton ci-dessus.', 'cma-note'));
    }
    if (row.status === 'pending_correction') box.append(el('p', row.grading_error || (row.grading_status === 'working' ? 'La correction rédigée est en cours.' : 'La copie est remise. La correction des réponses rédigées reste à effectuer.'), 'cma-note'));
    if (row.subject === 'D') {
      box.append(el('p', !verified ? 'Orthographe : vérification en attente.' : `Orthographe : ${number(row.spelling_error_count)} faute(s) relevée(s) ; pénalité appliquée : ${row.spelling_penalty} point.`, 'cma-note'));
      if (verified && row.spelling_errors?.length) { const details = el('details'); details.append(el('summary', 'Voir les occurrences d’orthographe relevées')); const list = el('ul'); row.spelling_errors.forEach(e => list.append(el('li', `${e.field_id} : « ${e.excerpt} » → « ${e.correction} »`))); details.append(list); box.append(details); }
    }
    if (row.lesson_links?.length) { box.append(el('h3', 'Vos révisions conseillées'), lessonLinks(row.lesson_links)); }
    if (verified) (row.ai_feedback?.next_steps || []).forEach(step => box.append(el('p', typeof step === 'string' ? step : step.text || step.title || 'Reprendre les éléments signalés dans le barème.', 'cma-note')));
    row.corrections.forEach(q => box.append(correctionCard(!verified && q.kind === 'qrc' ? {...q, points: null, criteria: q.criteria.map(c => ({...c, points: null, feedback: '', improvement: ''}))} : q))); return box;
  }
  function renderResults(result) {
    visible('cmaResult'); const panel = $('cmaResult'); panel.replaceChildren();
    const hero = el('div', undefined, 'cma-result-hero'); hero.append(el('p', 'BILAN DE VOTRE SIMULATION', 'cma-eyebrow'));
    const labels = {pending_correction: 'Copie remise · corrections en cours', needs_human_review: 'Analyse complémentaire des réponses', admissible: 'Critères d’admissibilité atteints', not_admissible: 'Des critères restent à atteindre'};
    hero.append(el('h2', labels[result.status]), el('p', result.weighted_average == null ? 'La moyenne définitive sera disponible lorsque toutes les matières auront une correction vérifiée.' : `Moyenne pondérée : ${number(result.weighted_average)} / 20. Objectif : au moins 10/20 et tous les minima atteints.`));
    if (result.failed_minima.length) hero.append(el('p', `Minimum non atteint : ${result.failed_minima.join(', ')}.`));
    if (result.status === 'not_admissible' && result.weighted_average >= 10 && !result.failed_minima.length) hero.append(el('p', 'La moyenne affichée est arrondie ; le calcul sans arrondi reste inférieur à 10/20.'));
    hero.append(el('p', 'Ce bilan est un entraînement pédagogique. L’admissibilité officielle est décidée par la CMA.')); panel.append(hero);
    const controls = el('div', undefined, 'cma-card');
    const pending = subjectsToGrade(result);
    if (pending.length) {
      const grade = el('button', grading ? 'Correction des réponses rédigées…' : 'Lancer ou reprendre les corrections', 'cma-primary'); grade.id = 'cmaGrade'; grade.type = 'button'; grade.disabled = grading;
      grade.addEventListener('click', () => void gradePending()); controls.append(grade);
      controls.append(el('p', grading ? 'Analyse de vos réponses… La correction peut prendre quelques instants' : `${pending.length} matière(s) rédigée(s) en attente. La correction avance matière par matière ; vous pouvez revenir consulter le bilan.`, 'cma-note'));
    }
    const restart = el('a', 'Retour aux simulations', 'cma-secondary'); restart.href = config.homeUrl; controls.append(restart); panel.append(controls);
    const tableBox = el('div', undefined, 'cma-card cma-table'), table = el('table'), thead = el('thead'), headings = el('tr');
    ['Matière', 'Note / 20', 'Coefficient', 'Minimum', 'État'].forEach(label => headings.append(el('th', label))); thead.append(headings); table.append(thead);
    const tbody = el('tbody'); result.subjects.forEach(row => { const tr = el('tr'); [row.subject, number(row.status === 'corrected' ? row.score : null), row.coefficient, `${row.minimum}/20`, row.status === 'corrected' ? row.minimum_met ? 'Minimum atteint' : 'Minimum non atteint' : 'Correction en attente'].forEach((text, i) => tr.append(el(i ? 'td' : 'th', String(text), i === 1 && row.status === 'corrected' ? row.minimum_met ? 'cma-grade-good' : 'cma-grade-low' : ''))); tbody.append(tr); });
    table.append(tbody); tableBox.append(table); panel.append(tableBox);
    result.subjects.forEach(row => panel.append(subjectResult(row)));
  }
  async function gradePending() {
    if (grading || !state?.result) return;
    grading = true; error(''); renderResults(state.result);
    const pending = subjectsToGrade(state.result);
    try {
      for (const subject of pending) {
        try { const data = await request(state.urls.grade, {version: state.version, subject}); applyState(data.state); }
        catch (ex) { if (ex.state) applyState(ex.state); error(ex.message); break; }
      }
    } finally { grading = false; if (state?.result) renderResults(state.result); }
  }
  async function submitPaper() {
    if (!paper || paperLocked()) { updateClock(); return; }
    submitting = true; $('cmaQuestion').disabled = true; $('cmaSubmit').disabled = true; $('cmaConfirmSubmit').disabled = true;
    error(''); cancelAutosave();
    try {
      if (config.preview) {
        $('cmaSaved').textContent = 'Analyse de vos réponses… La correction peut prendre quelques instants';
        const data = await request(config.previewGradeUrl, {version: bank.version, subject: paper.id, answers});
        visible('cmaResult'); const panel = $('cmaResult'); panel.replaceChildren();
        const notice = el('div', undefined, 'cma-card'); notice.append(el('h2', 'Correction de l’aperçu'), el('p', 'Cette correction n’a créé aucune tentative ni progression stagiaire.'));
        const back = el('button', 'Revenir à l’aperçu', 'cma-secondary'); back.type = 'button'; back.addEventListener('click', () => { visible('cmaPaper'); renderQuestion(); }); notice.append(back); panel.append(notice, subjectResult(data.result)); panel.focus();
      } else await queueSave(true);
    } catch (ex) { error(ex.message); }
    finally { submitting = false; $('cmaQuestion').disabled = paperLocked(); $('cmaSubmit').disabled = $('cmaConfirmSubmit').disabled = paperLocked(); $('cmaConfirm').hidden = true; if (config.preview) $('cmaSaved').textContent = 'Aperçu : réponses conservées uniquement dans cette page.'; }
  }
  $('cmaStart').addEventListener('click', async () => {
    error('');
    $('cmaStart').disabled = true;
    try { const data = await request(config.startUrl, {version: bank.version}); applyState(data.state); }
    catch (ex) { error(ex.message); } finally { $('cmaStart').disabled = false; }
  });
  $('cmaExplore')?.addEventListener('click', () => { error(''); config.preview = true; state = null; renderPaper(bank.subjects[0], {}); });
  $('cmaSubjectSelect').addEventListener('change', () => { if (config.preview) { error(''); renderPaper(subjectInfo($('cmaSubjectSelect').value), {}); } });
  $('cmaPrevious').addEventListener('click', () => { if (position > 0) { position--; renderQuestion(true); } });
  $('cmaNext').addEventListener('click', () => { if (position < paper.questions.length - 1) { position++; renderQuestion(true); } });
  $('cmaUnanswered').addEventListener('click', () => { const index = paper.questions.findIndex(q => !answered(q)); if (index >= 0) { position = index; renderQuestion(true); } else $('cmaSubmit').focus(); });
  $('cmaSaveNow').addEventListener('click', () => void queueSave());
  $('cmaPause')?.addEventListener('click', () => void controlPaper(isPaused() ? 'resume' : 'pause'));
  $('cmaReset')?.addEventListener('click', () => {
    if (!paper || controlling || submitting || conflicted || expired) return;
    $('cmaConfirm').hidden = true;
    $('cmaResetText').textContent = `Remettre à zéro la matière ${paper.id} ? Ses réponses seront effacées.${config.preview ? '' : ` Le chronomètre reviendra à ${paper.minutes} minutes et restera en pause jusqu’à ce que vous cliquiez sur « Reprendre ». Les autres matières seront conservées.`}`;
    $('cmaResetConfirm').hidden = false; $('cmaConfirmReset').focus();
  });
  $('cmaConfirmReset')?.addEventListener('click', () => void controlPaper('reset'));
  $('cmaCancelReset')?.addEventListener('click', () => { $('cmaResetConfirm').hidden = true; $('cmaReset').focus(); });
  $('cmaForm').addEventListener('submit', event => { event.preventDefault(); if (!paper || paperLocked()) { updateClock(); return; } if (config.preview) { void submitPaper(); return; } const count = paper.questions.filter(q => !answered(q)).length; $('cmaResetConfirm').hidden = true; $('cmaConfirmText').textContent = `${count ? `${count} réponse(s) manquante(s) seront notées zéro. ` : ''}Après validation, vous ne pourrez plus modifier cette matière. Confirmez-vous la validation ?`; $('cmaConfirm').hidden = false; $('cmaConfirmSubmit').focus(); });
  $('cmaCancelSubmit').addEventListener('click', () => { $('cmaConfirm').hidden = true; $('cmaSubmit').focus(); });
  $('cmaConfirmSubmit').addEventListener('click', () => void submitPaper());
  window.addEventListener('beforeunload', event => { if (!config.preview && paper && generation !== savedGeneration) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { updateClock(); void refreshState(); } });
  setInterval(updateClock, 500); setInterval(() => { if (!document.hidden && paper) void refreshState(); }, 20000);
  if (config.state) applyState(config.state);
})();
