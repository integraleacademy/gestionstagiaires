(() => {
  'use strict';
  const node = document.getElementById('annalesConfig');
  if (!node) return;
  const config = JSON.parse(node.textContent), exam = config.exam, questions = exam.questions;
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const key = `vtc-annales:${config.contextKey}:${exam.id}:${exam.version}`;
  let answers = {}, position = 0, attemptId = config.attemptId, submitting = false, finished = false;
  try {
    const draft = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (draft && typeof draft === 'object') {
      questions.filter(q => q.status === 'active').forEach(q => {
        const selected = draft.answers?.[q.id];
        if (Array.isArray(selected) && selected.length && selected.every(v => typeof v === 'string' && q.options.some(o => o.id === v)) && new Set(selected).size === selected.length && (q.kind !== 'single' || selected.length === 1)) answers[q.id] = selected;
      });
      if (Number.isInteger(draft.position) && draft.position >= 0 && draft.position < questions.length) position = draft.position;
      if (/^[a-f0-9]{32}$/.test(draft.attemptId || '')) attemptId = draft.attemptId;
    }
  } catch (_) { /* A damaged draft never prevents opening a paper. */ }
  function save() {
    try { sessionStorage.setItem(key, JSON.stringify({answers, position, attemptId})); $('annalesDraft').textContent = 'Vos réponses sont conservées dans cet onglet jusqu’à la correction.'; }
    catch (_) { $('annalesDraft').textContent = 'La sauvegarde locale est indisponible. Gardez cet onglet ouvert.'; }
  }
  const count = () => questions.filter(q => q.status === 'active' && answers[q.id]?.length).length;
  function update() {
    $('annalesAnswered').textContent = `${count()} / ${exam.scored_count} questions évaluées complétées`;
    $('annalesProgress').value = count();
    Array.from($('annalesGrid').children).forEach((button, i) => {
      const q = questions[i];
      button.classList.toggle('is-answered', !!answers[q.id]?.length);
      button.classList.toggle('is-current', i === position);
      button.setAttribute('aria-current', i === position ? 'step' : 'false');
      button.setAttribute('aria-label', `Question ${q.number}${q.status === 'historical' ? ', hors score' : answers[q.id]?.length ? ', réponse saisie' : ', à compléter'}`);
    });
  }
  function render(focus = false) {
    const q = questions[position], field = $('annalesQuestion'), context = $('annalesContext');
    field.replaceChildren(); context.replaceChildren();
    if (q.context) { const box = el('details', undefined, 'annales-context'); box.open = true; box.append(el('summary', 'Texte ou document du sujet'), el('p', q.context)); context.append(box); }
    if (q.image) { const image = el('img'); image.src = q.image; image.alt = `Illustration du sujet, question ${q.number}`; image.className = 'annales-question-image'; context.append(image); }
    const legend = el('legend', q.prompt); legend.tabIndex = -1; field.append(legend);
    if (q.adaptation_note) field.append(el('p', q.adaptation_note, 'annales-notice'));
    if (q.status === 'historical') {
      field.append(el('p', 'Cette question nécessite une mise au point. Elle ne compte pas dans votre score ; son explication sera présentée avec la correction.', 'annales-notice'));
      const list = el('ul'); q.options.forEach(o => list.append(el('li', o.text))); field.append(list);
    } else {
      field.append(el('p', q.kind === 'multiple' ? 'Cochez la ou les bonnes réponses. Pour valider la question, tous les choix attendus doivent être sélectionnés.' : 'Sélectionnez une réponse.', 'exam-note'));
      q.options.forEach((o, i) => {
        const label = el('label', undefined, 'exam-option'), input = el('input');
        input.type = q.kind === 'multiple' ? 'checkbox' : 'radio'; input.name = q.id; input.value = o.id;
        input.checked = (answers[q.id] || []).includes(o.id);
        input.addEventListener('change', () => {
          if (q.kind === 'single') answers[q.id] = [o.id];
          else answers[q.id] = Array.from(field.querySelectorAll('input:checked')).map(n => n.value);
          if (!answers[q.id].length) delete answers[q.id];
          $('annalesError').hidden = true; save(); update();
        });
        label.append(input, el('span', `${String.fromCharCode(65 + i)}. ${o.text}`)); field.append(label);
      });
    }
    $('annalesPosition').textContent = `Question ${q.number} · ${position + 1} / ${questions.length} · PDF page ${q.page}`;
    $('annalesPrevious').disabled = position === 0; $('annalesNext').disabled = position === questions.length - 1;
    update(); if (focus) legend.focus();
  }
  questions.forEach((q, i) => { const b = el('button', String(q.number)); b.type = 'button'; if (q.status === 'historical') b.classList.add('is-historical'); b.addEventListener('click', () => { position = i; render(true); save(); }); $('annalesGrid').append(b); });
  $('annalesPrevious').addEventListener('click', () => { position--; render(true); save(); });
  $('annalesNext').addEventListener('click', () => { position++; render(true); save(); });
  function remaining() { const i = questions.findIndex(q => q.status === 'active' && !answers[q.id]?.length); if (i >= 0) { position = i; render(true); save(); } else $('annalesSubmit').focus(); return i; }
  $('annalesReview').addEventListener('click', remaining);
  function displayResult(result) {
    finished = true; $('annalesWorkspace').hidden = true;
    const panel = $('annalesResult'); panel.hidden = false; panel.replaceChildren();
    const hero = el('div', undefined, 'exam-result-hero');
    hero.append(el('span', 'VOTRE BILAN PÉDAGOGIQUE', 'exam-eyebrow'), el('h2', result.total ? `${result.score} / ${result.total} questions justes · ${result.percent} %` : 'Les explications de ce sujet'), el('p', `${result.historical_count} question(s) historique(s) ou ambiguë(s) étudiée(s) hors score.`), el('p', config.preview ? 'Aperçu : aucun résultat stagiaire enregistré.' : 'Votre tentative a été enregistrée séparément de votre progression de cours.', 'exam-note'));
    const retry = el('button', 'Recommencer le sujet', 'exam-primary'); retry.type = 'button'; retry.addEventListener('click', () => location.reload()); hero.append(retry); panel.append(hero);
    const refs = new Map(); result.corrections.filter(q => q.correct === false).forEach(q => q.lesson_links.forEach(l => refs.set(l.ref, l.url)));
    if (refs.size) { const box = el('div', undefined, 'annales-notice'); box.append(el('h2', 'Les cours à revoir en priorité')); const list = el('div', undefined, 'annales-course-links'); refs.forEach((url, ref) => { const a = el('a', `Leçon ${ref}`); a.href = url; list.append(a); }); box.append(list); panel.append(box); }
    result.corrections.forEach(q => {
      const detail = el('details', undefined, `exam-correction ${q.correct === false ? 'is-wrong' : q.correct === null ? 'annales-neutral' : ''}`);
      const summary = el('summary', `${q.correct === null ? 'Hors score' : q.correct ? '✓ Juste' : 'À revoir'} · ${q.number}. ${q.prompt}`); detail.append(summary);
      const body = el('div', undefined, 'exam-correction-body'), list = el('ul');
      q.options.forEach(o => { const right = q.answers.includes(o.id), chosen = q.selected.includes(o.id); list.append(el('li', `${o.text}${right ? (q.status === 'historical' ? (q.correction_origin === 'source' ? ' — Réponse du document ancien' : ' — Repère pédagogique, hors score') : ' — Réponse attendue') : ''}${chosen ? ' — Votre choix' : ''}`, right ? 'right-answer' : chosen ? 'chosen-wrong' : '')); });
      body.append(list, el('p', q.explanation));
      if (q.update_note) body.append(el('p', q.update_note, 'annales-notice'));
      if (q.original_answer) body.append(el('p', `Réponse à la question ouverte${q.original_answer_origin === 'source' || q.correction_origin === 'source' ? ' dans le document source' : ' proposée pour cet entraînement'} : ${q.original_answer}`));
      body.append(el('p', `${q.correction_origin === 'source' ? 'Corrigé présent dans le document source.' : q.original_answer_origin === 'source' ? 'Choix pédagogiques adaptés de la réponse ouverte fournie dans le document.' : 'Correction pédagogique proposée ; le PDF fourni ne contient pas de corrigé officiel pour cette question.'} ${q.original_kind === 'qrc' ? 'Réponses à choix ajoutées pour l’entraînement sans rédaction.' : ''} Source : ${exam.source_filename}, page ${q.page}.`, 'exam-note'));
      const links = el('div', undefined, 'annales-course-links'); q.lesson_links.forEach(l => { const a = el('a', `Comprendre la leçon ${l.ref}`); a.href = l.url; links.append(a); }); body.append(links);
      (q.sources || []).forEach(s => { if (!/^https:\/\//.test(s.url || '')) return; const a = el('a', s.title, 'exam-source'); a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; body.append(a); });
      detail.append(body); panel.append(detail);
    });
    try { sessionStorage.removeItem(key); } catch (_) {} panel.focus();
  }
  $('annalesForm').addEventListener('submit', async event => {
    event.preventDefault(); if (submitting || finished) return;
    if (remaining() >= 0) { $('annalesError').textContent = 'Il reste des questions évaluées sans réponse.'; $('annalesError').hidden = false; return; }
    submitting = true; $('annalesSubmit').disabled = true; $('annalesSubmit').textContent = 'Correction en cours…';
    try {
      const response = await fetch(config.submitUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Elearning-CSRF': config.csrfToken}, body: JSON.stringify({version: exam.version, attempt_id: attemptId, answers})});
      const data = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : {};
      if (!response.ok || !data.ok) throw new Error(data.error || (response.status === 401 || response.status === 403 ? 'Votre session a expiré ou ce sujet n’est plus accessible. Rechargez la page.' : 'Enregistrement impossible pour le moment. Réessayez : vos réponses sont conservées.'));
      displayResult(data.result);
    } catch (error) { $('annalesError').textContent = error.message; $('annalesError').hidden = false; }
    finally { submitting = false; $('annalesSubmit').disabled = false; $('annalesSubmit').textContent = 'Terminer et voir ma correction'; }
  });
  render();
})();
