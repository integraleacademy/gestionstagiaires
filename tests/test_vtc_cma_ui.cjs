const {JSDOM} = require('jsdom');
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/vtc-cma.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

function attempt({review = true, pending = false} = {}) {
  const row = {subject: 'A', title: 'Réglementation', coefficient: 3, minimum: 6,
    status: review ? 'needs_human_review' : pending ? 'pending_correction' : 'corrected',
    score: review || pending ? 8 : 20, qcm_score: 10, qrc_score: review || pending ? 0 : 10,
    minimum_met: review || pending ? null : true, lesson_links: [],
    ai_feedback: {human_review_reasons: ['Le correcteur IA demande une relecture du formateur.'],
      next_steps: review ? ['Contactez votre formateur.'] : ['Révisez les notions du cours.']},
    corrections: [{id: 'A-qrc-01', kind: 'qrc', prompt: 'Expliquer la règle', selected: 'Ma réponse conservée.',
      points: review || pending ? 0 : 10, max_points: 10, model_response: 'Réponse de référence.', lesson_links: [],
      criteria: [{label: 'Justification', points: review || pending ? 0 : 10, max_points: 10,
        feedback: review ? 'Vérification par le formateur.' : 'La règle est expliquée.', expected: 'Justifier la règle.', partial_guidance: 'Selon les éléments démontrés.'}]}]};
  return {id: 'attempt-1', version: 'edition-test', status: 'submitted', server_now: 100,
    parts: [{subject: 'A', status: 'submitted'}], urls: {grade: '/grade', state: '/state'},
    result: {status: review ? 'needs_human_review' : pending ? 'pending_correction' : 'admissible',
      weighted_average: review || pending ? null : 20, passed: review || pending ? null : true,
      pending_subjects: pending ? ['A'] : [], review_subjects: review ? ['A'] : [], failed_minima: [], subjects: [row]}};
}

function fixture({state = attempt(), available = true, respond} = {}) {
  const config = {preview: false, aiAvailable: available, csrfToken: 'csrf', homeUrl: '/simulation',
    bank: {version: 'edition-test', subjects: [{id: 'A', title: 'Réglementation'}]}, state};
  const dom = new JSDOM(`<main><p id="cmaError" hidden></p><section id="cmaLanding"><button id="cmaStart">Commencer</button></section>
    <section id="cmaPaper" hidden><select id="cmaSubjectSelect"><option>A</option></select>
    <button id="cmaPrevious">Précédente</button><button id="cmaNext">Suivante</button><button id="cmaUnanswered">Manquantes</button><button id="cmaSaveNow">Enregistrer</button>
    <form id="cmaForm"><fieldset id="cmaQuestion"></fieldset><button id="cmaSubmit">Remettre</button></form>
    <div id="cmaConfirm"><p id="cmaConfirmText"></p><button id="cmaCancelSubmit">Annuler</button><button id="cmaConfirmSubmit">Confirmer</button></div></section>
    <section id="cmaBetween" hidden></section><section id="cmaResult" hidden></section></main>
    <script id="cmaConfig" type="application/json">${JSON.stringify(config).replace(/</g, '\\u003c')}</script>`,
    {url: 'https://test.invalid/simulation', runScripts: 'outside-only'});
  const w = dom.window, requests = [];
  w.fetch = async (url, options) => {
    requests.push({url, options});
    const result = await (respond ? respond(requests.length) : {ok: true, state: attempt({review: false})});
    return {ok: result.ok, status: result.ok ? 200 : 503, headers: {get: () => 'application/json'}, json: async () => {
      if (result.invalidJson) throw new SyntaxError('Unexpected end of JSON input');
      return result;
    }};
  };
  w.eval(source);
  return {w, requests, close: () => w.close()};
}

test('A saved uncertain result is analysed automatically without a trainer or provisional mark', async () => {
  let resolve;
  const response = new Promise(r => { resolve = r; });
  const f = fixture({respond: () => response});
  try {
    const d = f.w.document;
    assert.equal(f.requests.length, 1);
    assert.equal(JSON.parse(f.requests[0].options.body).subject, 'A');
    assert.equal(f.requests[0].options.headers['X-Elearning-CSRF'], 'csrf');
    assert.match(d.getElementById('cmaResult').textContent, /Analyse de vos réponses… La correction peut prendre quelques instants/);
    assert.match(d.getElementById('cmaResult').textContent, /Ma réponse conservée/);
    assert.doesNotMatch(d.getElementById('cmaResult').textContent, /formateur|humaine|\bIA\b|8\s*\/\s*20/i);
    resolve({ok: true, state: attempt({review: false})});
    await flush();
    assert.match(d.getElementById('cmaResult').textContent, /Critères d’admissibilité atteints/);
    assert.match(d.getElementById('cmaResult').textContent, /20 \/ 20/);
    assert.equal(d.getElementById('cmaGrade'), null);
    assert.equal(f.requests.length, 1);
  } finally { f.close(); }
});

test('A temporary correction failure preserves the copy and permits a bounded learner retry', async () => {
  const f = fixture({respond: n => n === 1 ? {ok: false,
    error: 'La correction est momentanément indisponible. Vos réponses sont conservées ; vous pourrez réessayer dans quelques instants.',
    state: attempt()} : {ok: true, state: attempt({review: false})}});
  try {
    await flush();
    const d = f.w.document;
    assert.equal(f.requests.length, 1);
    assert.match(d.getElementById('cmaError').textContent, /réponses sont conservées/);
    assert.match(d.getElementById('cmaResult').textContent, /Ma réponse conservée/);
    assert.equal(d.getElementById('cmaGrade').disabled, false);
    assert.doesNotMatch(d.getElementById('cmaResult').textContent, /formateur|humaine|\bIA\b/i);
    d.getElementById('cmaGrade').click();
    await flush();
    assert.equal(f.requests.length, 2);
    assert.match(d.getElementById('cmaResult').textContent, /Critères d’admissibilité atteints/);
  } finally { f.close(); }
});

test('A verified result is displayed without invoking the correction service again', async () => {
  const f = fixture({state: attempt({review: false})});
  try {
    await flush();
    assert.equal(f.requests.length, 0);
    assert.equal(f.w.document.getElementById('cmaGrade'), null);
    assert.match(f.w.document.getElementById('cmaResult').textContent, /20 \/ 20/);
  } finally { f.close(); }
});

for (const failure of ['network', 'json']) {
  test(`An interrupted ${failure} response uses a French retry message and preserves the copy`, async () => {
    const f = fixture({respond: n => {
      if (n > 1) return {ok: true, state: attempt({review: false})};
      if (failure === 'network') throw new TypeError('Failed to fetch');
      return {ok: true, invalidJson: true};
    }});
    try {
      await flush();
      const d = f.w.document;
      assert.match(d.getElementById('cmaError').textContent, /La connexion a été interrompue/);
      assert.doesNotMatch(d.getElementById('cmaError').textContent, /Failed to fetch|JSON|formateur|\bIA\b/);
      assert.match(d.getElementById('cmaResult').textContent, /Ma réponse conservée/);
      assert.equal(f.requests.length, 1);
      assert.equal(d.getElementById('cmaGrade').disabled, false);
      d.getElementById('cmaGrade').click();
      await flush();
      assert.equal(f.requests.length, 2);
      assert.match(d.getElementById('cmaResult').textContent, /Critères d’admissibilité atteints/);
    } finally { f.close(); }
  });
}
