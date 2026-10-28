const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const template = fs.readFileSync(path.join(__dirname, '../templates/admin_trainees.html'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, '../static/js/ssiap-birth-department.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const debounce = () => new Promise(resolve => setTimeout(resolve, 400));
const result = department => ({ok: true, json: async () => ({ok: true, department})});

function setup(t, fetcher = async () => result('59')) {
  const markup = template.match(/<form id="ssiapDiplomaInfoForm"[\s\S]*?<\/form>/)[0];
  const dom = new JSDOM(markup, {runScripts: 'outside-only', url: 'https://test.example/'});
  t.after(() => dom.window.close());
  const {window} = dom;
  const form = window.document.getElementById('ssiapDiplomaInfoForm');
  form.dataset.birthDepartmentUrl = '/admin/ssiap/birth-department';
  let calls = 0;
  window.fetch = (...args) => {calls++; return fetcher(...args);};
  window.eval(source);
  const input = (name, value) => {
    form.elements[name].value = value;
    form.elements[name].dispatchEvent(new window.Event('input'));
  };
  const open = (city = 'MAUBEUGE', department = '', country = 'France') => {
    form.elements.birth_city.value = city;
    form.elements.birth_country.value = country;
    form.elements.birth_department.value = department;
    form.dispatchEvent(new window.Event('ssiap-diploma-info-opened'));
  };
  return {
    window, form, input, open,
    get calls() {return calls;},
    get department() {return form.elements.birth_department.value;},
    get hint() {return window.document.getElementById('ssiapInfoBirthDepartmentHint').textContent;},
  };
}

test('opening the real edit button fills Maubeuge automatically', async t => {
  const ui = setup(t, async url => {
    assert.equal(new URL(url, 'https://test.example').searchParams.get('city'), 'MAUBEUGE');
    return result('59');
  });
  const button = ui.window.document.createElement('button');
  button.className = 'ssiap-edit-info-btn';
  button.dataset.birthCity = 'MAUBEUGE';
  button.dataset.birthCountry = 'france';
  ui.window.document.body.append(button);
  ui.window.openModal = () => {};
  const opener = template.slice(template.indexOf('  document.querySelectorAll(".ssiap-edit-info-btn")'),
    template.indexOf('  document.querySelectorAll(".ssiap-exam-select")'));
  ui.window.eval(opener);
  button.click();
  await tick();
  assert.equal(ui.department, '59');
  assert.match(ui.hint, /automatiquement/);
});

test('existing saved department and subsequent manual corrections are kept', async t => {
  let finish;
  const ui = setup(t, () => new Promise(resolve => {finish = resolve;}));
  ui.open('Saint-Sauveur', '60');
  assert.equal(ui.calls, 0);
  ui.open();
  ui.input('birth_department', '62');
  finish(result('59'));
  await tick();
  assert.equal(ui.department, '62');
  assert.equal(ui.hint, '');
});

test('city changes clear the old department and debounce the new lookup', async t => {
  const ui = setup(t, async () => result('83'));
  ui.open('Paris', '75');
  ui.input('birth_city', 'To');
  ui.input('birth_city', 'Tou');
  ui.input('birth_city', 'Toulon');
  assert.equal(ui.department, '');
  await debounce();
  assert.equal(ui.calls, 1);
  assert.equal(ui.department, '83');
});

test('an old response never overwrites another city or another trainee', async t => {
  const pending = [];
  const ui = setup(t, () => new Promise(resolve => pending.push(resolve)));
  ui.open('Maubeuge');
  ui.input('birth_city', 'Ajaccio');
  pending[0](result('59'));
  await tick();
  assert.equal(ui.department, '');
  await debounce();
  ui.open('Bastia');
  pending[2](result('2B'));
  await tick();
  pending[1](result('2A'));
  await tick();
  assert.equal(ui.department, '2B');
});

test('foreign country cancels French lookup and clears its old department', async t => {
  const ui = setup(t);
  ui.open();
  await tick();
  ui.input('birth_country', 'Belgique');
  await debounce();
  assert.equal(ui.department, '');
  assert.equal(ui.calls, 1);
  ui.open('Paris', '', 'États-Unis');
  await tick();
  assert.equal(ui.calls, 1);
});

test('a manual entry during the debounce is never replaced', async t => {
  const ui = setup(t);
  ui.open('Paris', '75');
  ui.input('birth_city', 'Saint-Sauveur');
  ui.input('birth_department', '60');
  await debounce();
  assert.equal(ui.department, '60');
  assert.equal(ui.calls, 0);
});

test('unknown or ambiguous cities allow manual entry', async t => {
  const ui = setup(t, async () => result(''));
  ui.open('Saint-Sauveur');
  await tick();
  assert.equal(ui.department, '');
  assert.match(ui.hint, /renseignez le département/);
  ui.input('birth_department', '60');
  assert.equal(ui.department, '60');
});

test('network failure and expired login leave the form usable', async t => {
  let fail = true;
  const ui = setup(t, async () => {
    if (fail) throw new Error('offline');
    return {ok: false, status: 401};
  });
  ui.open();
  await tick();
  assert.match(ui.hint, /indisponible/);
  assert.equal(ui.form.elements.birth_department.hasAttribute('aria-busy'), false);
  fail = false;
  ui.open();
  await tick();
  assert.match(ui.hint, /indisponible/);
  ui.input('birth_department', '59');
  assert.equal(ui.department, '59');
});
