const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/cpf-native-search.js'), 'utf8');

function setup(responses) {
  const nodes = new Map();
  for (const name of ['status', 'message', 'search', 'results', 'candidates', 'query', 'pagination',
                      'notice', 'count', 'page', 'previous', 'next']) {
    nodes.set(`[data-native-${name}]`, {
      dataset: {}, events: {}, textContent: '', innerHTML: '', hidden: true,
      addEventListener(name, callback) { this.events[name] = callback; },
    });
  }
  const get = name => nodes.get(`[data-native-${name}]`);
  get('query').elements = {q: {value: ''}};
  const buttons = [get('search'), get('previous'), get('next')];
  const state = {calls: [], replaced: false, markup: ''};
  const root = {
    dataset: {searchUrl: '/lookup', matchUrl: '/match', refreshUrl: '/sheet', sessionId: 's1', traineeId: 't1'},
    querySelector: selector => nodes.get(selector), querySelectorAll: () => buttons,
    setAttribute() {}, closest: () => ({replaceWith: () => { state.replaced = true; }}),
  };
  const location = {href: 'https://fixture.invalid/sheet'};
  vm.runInNewContext(source, {
    document: {readyState: 'complete', querySelector: () => root},
    window: {location}, URL, URLSearchParams, AbortController, setTimeout, clearTimeout,
    FormData: class { constructor(form) { return form.data; } },
    DOMParser: class { parseFromString(markup) {
      state.markup = markup;
      return {querySelector: () => ({querySelector: () => null, open: false})};
    } },
    fetch: async (url, options) => {
      state.calls.push({url: String(url), ...options});
      const result = responses.shift();
      if (result instanceof Error) throw result;
      if (!result) throw new Error('Unexpected request');
      return {ok: result.ok !== false, json: async () => result, text: async () => '<details id="cpfTracking">Associated</details>'};
    },
  });
  return {state, root, get, location, async settle() { for (let i = 0; i < 12; i++) await new Promise(setImmediate); }};
}
const result = {csrf: 'fixture-csrf', active: true, synced: true, page: 1, pages: 1, total: 1,
  message: 'Vérifiez le dossier proposé.', candidates: [{folder_id: '100000', first_name: '<Anne>',
    last_name: 'Exemple', state: 'Accepté', title: 'APS', session_start_date: '2026-02-02',
    session_end_date: '2026-02-06', checks: [{label: 'Dates identiques', matches: true}],
    issues: [], can_associate: true, confirm_dates: false, associate_url: '/associate'}]};

test('search stays in the sheet, renders escaped candidates and ignores a double click', async () => {
  const f = setup([result, {status: 'unlinked'}]);
  f.get('search').events.click();
  f.get('search').events.click();
  assert.equal(f.get('search').disabled, true);
  assert.match(f.get('status').className, /loading/);
  await f.settle();
  assert.deepEqual(f.state.calls.map(c => c.method), ['GET', 'POST']);
  assert.equal(f.state.calls[1].body.get('csrf'), 'fixture-csrf');
  assert.match(f.get('candidates').innerHTML, /&lt;Anne&gt;/);
  assert.equal(f.get('results').hidden, false);
  assert.equal(f.get('search').disabled, false);
  assert.equal(f.location.href, 'https://fixture.invalid/sheet');
});

test('a safe automatic association refreshes only the CPF panel', async () => {
  const f = setup([result, {status: 'associated'}, {}]);
  f.get('search').events.click();
  await f.settle();
  assert.equal(f.state.replaced, true);
  assert.equal(f.state.calls[2].url, '/sheet');
  assert.equal(f.location.href, 'https://fixture.invalid/sheet');
});

test('manual lookup is read only and preserves the requested query', async () => {
  const f = setup([{...result, total: 0, candidates: []}]);
  f.get('query').elements.q.value = '  Exemple  ';
  f.get('query').events.submit({preventDefault() {}});
  await f.settle();
  assert.equal(f.state.calls.length, 1);
  assert.equal(new URL(f.state.calls[0].url).searchParams.get('q'), 'Exemple');
  assert.equal(f.state.calls[0].method, 'GET');
});

test('manual association sends verified choices with CSRF and updates the panel', async () => {
  const f = setup([result, {ok: true}, {}]);
  f.get('query').events.submit({preventDefault() {}});
  await f.settle();
  const form = {action: '/associate', data: [['verified', 'yes'], ['confirm_date_mismatch', '1']]};
  await f.get('candidates').events.submit({target: {closest: () => form}, preventDefault() {}});
  const request = f.state.calls[1];
  assert.equal(request.body.get('csrf'), 'fixture-csrf');
  assert.equal(request.body.get('session_id'), 's1');
  assert.equal(request.body.get('trainee_id'), 't1');
  assert.equal(request.body.get('confirm_date_mismatch'), '1');
  assert.equal(f.state.replaced, true);
});

test('network errors show a retryable error and restore the button', async () => {
  const f = setup([new Error('Connexion interrompue')]);
  f.get('search').events.click();
  await f.settle();
  assert.match(f.get('status').className, /error/);
  assert.equal(f.get('message').textContent, 'Connexion interrompue');
  assert.equal(f.get('search').disabled, false);
  assert.equal(f.state.replaced, false);
});

test('a saved association remains successful if refreshing the sheet fails', async () => {
  const f = setup([result, {status: 'associated'}, new Error('Refresh failed')]);
  f.get('search').events.click();
  await f.settle();
  assert.match(f.get('message').textContent, /est associé/);
  assert.match(f.get('notice').innerHTML, /Actualiser le suivi CPF/);
  assert.equal(f.get('search').disabled, true);
  assert.equal(f.state.replaced, false);
});
