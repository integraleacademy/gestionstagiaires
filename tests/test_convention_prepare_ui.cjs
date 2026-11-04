const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/trainee-sheet.js'), 'utf8');
const code = source.slice(source.indexOf('// All convention entry points use the same type, finance and signature flow.'));

function fixture({state = 'loading', disabled = false, missing = false, query = '?preparer_convention=1&retour=liste'} = {}) {
  const events = new Map(), frames = [], navigations = [];
  let submissions = 0;
  const panel = {tagName: 'DETAILS', open: false, parentElement: null};
  const form = {parentElement: panel, querySelector: () => ({disabled}), requestSubmit: () => submissions++};
  const context = {
    URL, URLSearchParams,
    window: {
      location: {search: query, href: 'https://example.test/fiche' + query + '#automationHub'},
      history: {state: {keep: true}, replaceState: (...args) => navigations.push(args)},
    },
    document: {readyState: state, querySelector: () => missing ? null : form,
      addEventListener: (name, callback, options) => { assert.equal(options.once, true); events.set(name, callback); }},
    requestAnimationFrame: callback => frames.push(callback),
  };
  vm.runInNewContext(code, context);
  return {events, frames, panel, navigations, count: () => submissions};
}

const loading = fixture();
assert.equal(loading.frames.length, 0, 'Do not open the dialog before base.html has finished parsing');
assert.equal(loading.navigations.length, 0);
loading.events.get('DOMContentLoaded')();
assert.equal(loading.panel.open, true);
assert.equal(loading.count(), 0);
loading.frames[0]();
assert.equal(loading.count(), 1);
assert.equal(loading.navigations[0][2], '/fiche?retour=liste#automationHub');

const ready = fixture({state: 'complete'});
assert.equal(ready.events.size, 0);
ready.frames[0]();
assert.equal(ready.count(), 1);
for (const options of [{disabled: true}, {missing: true}, {query: ''}]) {
  const blocked = fixture({state: 'complete', ...options});
  assert.equal(blocked.frames.length, 0);
  assert.equal(blocked.count(), 0);
}
console.log('Convention preparation: loading, ready, permissions and URL preservation passed.');
