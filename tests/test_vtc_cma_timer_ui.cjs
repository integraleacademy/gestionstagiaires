const {JSDOM} = require('jsdom');
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/vtc-cma.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const startTime = 2000000;
const subjects = [...'ABCDEFG'].map((id, i) => ({id, title: `Matière ${id}`,
  minutes: [45, 45, 30, 30, 30, 30, 20][i], coefficient: 3, minimum: 6,
  questions: [1, 2].map(n => ({id: `${id}-${n}`, kind: 'qrc', prompt: `Question ${n}`, max_chars: 800, max_points: 2}))}));

function active({subject = 'A', now = startTime, deadline = startTime + 2700} = {}) {
  return {id: 'trial', version: 'v1', status: 'active', server_now: now, current_subject: subject,
    paper: subjects.find(s => s.id === subject), answers: {},
    parts: subjects.map(s => ({subject: s.id, status: s.id === subject ? 'running' : s.id < subject ? 'submitted' : 'not_started',
      revision: 0, started_at: startTime, deadline: s.id === subject ? deadline : undefined})),
    urls: {state: '/state', save: '/save', submit: '/submit', start_part: '/next', pause: '/pause', resume: '/resume', reset: '/reset'}};
}

function fixture({state = active(), admin = false, respond} = {}) {
  const config = {preview: admin, adminPreview: admin, aiAvailable: false, csrfToken: 'csrf',
    homeUrl: '/simulation', startUrl: '/start', previewGradeUrl: '/correct', bank: {version: 'v1', subjects}, state};
  const dom = new JSDOM(`<main><p id="cmaError" hidden></p>
    <section id="cmaLanding"><button id="cmaStart">Commencer</button><button id="cmaExplore">Explorer</button></section>
    <section id="cmaPaper" hidden>
      <p id="cmaExamStage"></p><h2 id="cmaSubjectTitle" tabindex="-1"></h2><p id="cmaSubjectMeta"></p>
      <div id="cmaClockBox"><span id="cmaClockLabel"></span><strong id="cmaClock"></strong><span id="cmaClockDetail"></span></div>
      <progress id="cmaTimeProgress"></progress><p id="cmaTimeNotice" role="status"></p><ol id="cmaSubjectSteps"></ol>
      <div id="cmaPreviewSelect"><select id="cmaSubjectSelect">${subjects.map(s => `<option>${s.id}</option>`).join('')}</select></div>
      <button type="button" id="cmaPause"></button><button type="button" id="cmaReset">Remettre à zéro</button>
      <div id="cmaResetConfirm" hidden><p id="cmaResetText"></p><button type="button" id="cmaConfirmReset">Confirmer</button><button type="button" id="cmaCancelReset">Annuler</button></div><div id="cmaPausedInfo" hidden></div>
      <div id="cmaWorkspace"><p id="cmaAnswered"></p><progress id="cmaProgress"></progress><nav id="cmaQuestionGrid"></nav>
      <button id="cmaUnanswered">Manquantes</button><button id="cmaSaveNow">Enregistrer</button><p id="cmaSaved"></p>
      <details id="cmaPassage"><summary id="cmaPassageTitle"></summary><ol id="cmaPassageLines"></ol></details>
      <p id="cmaQuestionMeta"></p><form id="cmaForm"><fieldset id="cmaQuestion"></fieldset>
      <button type="button" id="cmaPrevious">Précédente</button><button type="button" id="cmaNext">Suivante</button>
      <button id="cmaSubmit">Remettre</button><div id="cmaConfirm"><p id="cmaConfirmText"></p>
      <button type="button" id="cmaCancelSubmit">Annuler</button><button type="button" id="cmaConfirmSubmit">Confirmer</button></div></form></div>
    </section><section id="cmaBetween" hidden></section><section id="cmaResult" hidden></section></main>
    <script id="cmaConfig" type="application/json">${JSON.stringify(config)}</script>`,
    {url: 'https://test.invalid/simulation', runScripts: 'outside-only'});
  const w = dom.window, requests = [], intervals = []; let elapsed = 0;
  w.performance.now = () => elapsed;
  w.Date.now = () => startTime * 1000 + elapsed;
  w.setInterval = callback => { intervals.push(callback); return intervals.length; };
  w.fetch = async (url, options) => {
    const data = options.body ? JSON.parse(options.body) : null; requests.push({url, data});
    const result = respond ? await respond(url, data) : {ok: true, state: active()};
    return {ok: result.ok, status: result.ok ? 200 : 503,
      headers: {get: () => 'application/json'}, json: async () => result};
  };
  w.eval(source);
  return {w, d: w.document, requests, tick(seconds) {elapsed += seconds * 1000; intervals[0]();}, close: () => w.close()};
}

test('Countdown warns at five minutes and one minute; expiry locks even after navigation or an offline retry', async () => {
  const f = fixture({respond: () => {throw new Error('offline');}});
  try {
    assert.equal(f.d.getElementById('cmaClock').textContent, '45:00');
    assert.equal(f.d.getElementById('cmaSubjectSteps').children.length, 7);
    f.tick(2400);
    assert.equal(f.d.getElementById('cmaClock').textContent, '05:00');
    assert(f.d.getElementById('cmaClockBox').classList.contains('is-urgent'));
    assert.match(f.d.getElementById('cmaTimeNotice').textContent, /5 minutes/);
    f.tick(240);
    assert.equal(f.d.getElementById('cmaClock').textContent, '01:00');
    assert.match(f.d.getElementById('cmaTimeNotice').textContent, /Dernière minute/);
    const input = f.d.getElementById('cmaWrittenAnswer'); input.value = 'Dernière saisie locale';
    input.dispatchEvent(new f.w.Event('input', {bubbles: true}));
    f.tick(60); await flush();
    assert.equal(f.d.getElementById('cmaClock').textContent, '00:00');
    assert(f.d.getElementById('cmaQuestion').disabled);
    f.d.getElementById('cmaNext').click();
    assert(f.d.getElementById('cmaQuestion').disabled);
    assert(f.d.getElementById('cmaSubmit').disabled);
    assert(f.requests.every(r => r.url === '/state' && !r.data), 'no local answers sent after deadline');
    f.tick(5); await flush();
    assert.equal(f.requests.length, 2, 'expiration is retried after a network error');
  } finally {f.close();}
});

test('Expiry remits the saved copy and waits for an explicit start of the next paper', async () => {
  const between = active({subject: 'B', now: startTime + 2700});
  delete between.paper; delete between.answers;
  between.parts[0].status = 'expired'; between.parts[1].status = 'not_started';
  const f = fixture({respond: url => ({ok: true, state: url === '/next'
    ? active({subject: 'B', now: startTime + 2700, deadline: startTime + 5400}) : between})});
  try {
    f.tick(2700); await flush();
    assert.equal(f.d.getElementById('cmaBetween').hidden, false);
    assert.match(f.d.getElementById('cmaBetween').textContent, /remises automatiquement/);
    assert.equal(f.requests.length, 1);
    f.d.querySelector('#cmaBetween button').click(); await flush();
    assert.equal(f.requests[1].data.subject, 'B');
    assert.equal(f.d.getElementById('cmaClock').textContent, '45:00');
    assert.equal(f.d.getElementById('cmaQuestion').disabled, false);
    assert.match(f.d.getElementById('cmaExamStage').textContent, /2 \/ 7/);
  } finally {f.close();}
});

test('Reload uses the persisted server deadline and never grants a fresh duration', () => {
  const f = fixture({state: active({now: startTime + 600})});
  try {
    assert.equal(f.d.getElementById('cmaClock').textContent, '35:00');
    f.tick(30);
    assert.equal(f.d.getElementById('cmaClock').textContent, '34:30');
    assert.equal(f.requests.length, 0);
  } finally {f.close();}
});

test('Admin starts the real timed engine; free exploration remains a separate choice', async () => {
  const f = fixture({state: null, admin: true});
  try {
    f.d.getElementById('cmaStart').click(); await flush();
    assert.equal(f.requests[0].url, '/start');
    assert.equal(f.d.getElementById('cmaClock').textContent, '45:00');
    assert(f.d.getElementById('cmaPreviewSelect').hidden);
    f.tick(10);
    assert.equal(f.d.getElementById('cmaClock').textContent, '44:50');
  } finally {f.close();}
  const free = fixture({state: null, admin: true});
  try {
    free.d.getElementById('cmaExplore').click();
    free.tick(60);
    assert.equal(free.requests.length, 0);
    assert.equal(free.d.getElementById('cmaClock').textContent, '45 min');
    assert.equal(free.d.getElementById('cmaPreviewSelect').hidden, false);
  } finally {free.close();}
});

test('An interrupted manual submission cannot re-enable answers when its deadline has passed', async () => {
  let release;
  const f = fixture({respond: url => url === '/submit' ? new Promise(resolve => {release = resolve;}) : Promise.reject(new Error('offline'))});
  try {
    f.d.getElementById('cmaConfirmSubmit').click(); await flush();
    f.tick(2700); await flush();
    release({ok: false, error: 'Connexion interrompue'}); await flush();
    assert(f.d.getElementById('cmaQuestion').disabled);
    assert(f.d.getElementById('cmaSubmit').disabled);
  } finally {f.close();}
});

function paused({remaining = 2400, revision = 1, answers = {'A-1': 'Réponse conservée'}} = {}) {
  const state = active({now: startTime + 300});
  Object.assign(state.parts[0], {status: 'paused', revision, remaining_seconds: remaining});
  delete state.parts[0].deadline;
  state.answers = answers;
  return state;
}

test('Pause atomically sends the last unsaved answer, freezes time, and resumes without losing it', async () => {
  let saved;
  const f = fixture({respond: (url, data) => {
    if (url === '/pause') {saved = data.answers; return {ok: true, state: paused({answers: saved})};}
    assert.equal(url, '/resume');
    const state = active({now: startTime + 90000, deadline: startTime + 92400});
    state.parts[0].revision = 2; state.answers = saved;
    return {ok: true, state};
  }});
  try {
    const input = f.d.getElementById('cmaWrittenAnswer'); input.value = 'Dernière frappe avant pause';
    input.dispatchEvent(new f.w.Event('input', {bubbles: true}));
    f.d.getElementById('cmaPause').click(); await flush();
    assert.equal(f.requests.length, 1);
    assert.equal(f.requests[0].url, '/pause');
    assert.equal(f.requests[0].data.answers['A-1'], input.value);
    assert.equal(f.d.getElementById('cmaPause').textContent, 'Reprendre');
    assert(f.d.getElementById('cmaWorkspace').hidden);
    assert(f.d.getElementById('cmaQuestion').disabled);
    assert.equal(f.d.getElementById('cmaPausedInfo').hidden, false);
    f.tick(90000);
    assert.equal(f.d.getElementById('cmaClock').textContent, '40:00');
    assert.equal(f.requests.length, 1);
    f.d.getElementById('cmaPause').click(); await flush();
    assert.equal(f.requests[1].data.revision, 1);
    assert.equal(f.d.getElementById('cmaWrittenAnswer').value, input.value);
    assert.equal(f.d.getElementById('cmaWorkspace').hidden, false);
    assert.equal(f.d.getElementById('cmaQuestion').disabled, false);
    f.tick(60);
    assert.equal(f.d.getElementById('cmaClock').textContent, '39:00');
  } finally {f.close();}
});

test('Reload of a paused exam remains frozen until an explicit resume', () => {
  const f = fixture({state: paused()});
  try {
    f.tick(86400);
    assert.equal(f.d.getElementById('cmaClock').textContent, '40:00');
    assert.equal(f.requests.length, 0);
    assert(f.d.getElementById('cmaWorkspace').hidden);
    assert.equal(f.d.getElementById('cmaPause').textContent, 'Reprendre');
  } finally {f.close();}
});

test('Reset requires confirmation and clears answers with a full, paused timer instead of submitting', async () => {
  const f = fixture({state: paused(), respond: url => {
    assert.equal(url, '/reset');
    return {ok: true, state: paused({remaining: 2700, revision: 2, answers: {}})};
  }});
  try {
    f.d.getElementById('cmaReset').click();
    assert.equal(f.requests.length, 0);
    assert.equal(f.d.getElementById('cmaResetConfirm').hidden, false);
    assert.match(f.d.getElementById('cmaResetText').textContent, /réponses seront effacées/);
    f.d.getElementById('cmaCancelReset').click();
    assert(f.d.getElementById('cmaResetConfirm').hidden);
    assert.equal(f.d.getElementById('cmaWrittenAnswer').value, 'Réponse conservée');
    f.d.getElementById('cmaReset').click(); f.d.getElementById('cmaConfirmReset').click(); await flush();
    assert.equal(f.requests.length, 1);
    assert.equal(f.d.getElementById('cmaClock').textContent, '45:00');
    assert.equal(f.d.getElementById('cmaWrittenAnswer').value, '');
    assert.equal(f.d.getElementById('cmaPause').textContent, 'Reprendre');
  } finally {f.close();}
});

test('Failed pause keeps the running clock and local draft visible, without claiming it was saved', async () => {
  const f = fixture({respond: () => {throw new Error('offline');}});
  try {
    const input = f.d.getElementById('cmaWrittenAnswer'); input.value = 'Brouillon local';
    input.dispatchEvent(new f.w.Event('input', {bubbles: true}));
    f.d.getElementById('cmaPause').click(); await flush();
    assert.match(f.d.getElementById('cmaError').textContent, /interrompue/);
    assert.equal(f.d.getElementById('cmaWorkspace').hidden, false);
    assert(f.d.getElementById('cmaPausedInfo').hidden);
    assert.equal(f.d.getElementById('cmaWrittenAnswer').value, input.value);
    f.tick(10);
    assert.equal(f.d.getElementById('cmaClock').textContent, '44:50');
  } finally {f.close();}
});

test('Pause waits for an in-flight save and uses its new revision and latest draft', async () => {
  let release;
  const f = fixture({respond: (url, data) => {
    if (url === '/save') return new Promise(resolve => {release = resolve;});
    assert.equal(url, '/pause');
    assert.equal(data.revision, 1);
    assert.equal(data.answers['A-1'], 'Version finale');
    return {ok: true, state: paused({revision: 2, answers: data.answers})};
  }});
  try {
    const input = f.d.getElementById('cmaWrittenAnswer'); input.value = 'Première saisie';
    input.dispatchEvent(new f.w.Event('input', {bubbles: true}));
    f.d.getElementById('cmaSaveNow').click(); await flush();
    input.value = 'Version finale'; input.dispatchEvent(new f.w.Event('input', {bubbles: true}));
    f.d.getElementById('cmaPause').click(); await flush();
    assert.equal(f.requests.length, 1);
    const saved = active(); saved.parts[0].revision = 1; saved.answers = {'A-1': 'Première saisie'};
    release({ok: true, state: saved}); await flush(); await flush();
    assert.equal(f.requests.length, 2);
    assert.equal(f.d.getElementById('cmaWrittenAnswer').value, 'Version finale');
    assert(f.d.getElementById('cmaWorkspace').hidden);
  } finally {f.close();}
});
