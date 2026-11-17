const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const js = fs.readFileSync(path.join(__dirname, '../static/js/public-info-autosave.js'), 'utf8');
const context = { setTimeout: () => 1, clearTimeout() {} };
vm.runInNewContext(js, context);

function create(initial, send) {
  const notices = [], permit = [];
  const saver = context.createPublicInfoAutosave({
    initial, send: payload => send(JSON.parse(JSON.stringify(payload))),
    notify: (...n) => notices.push(n), onPermitSaved: value => permit.push(value),
  });
  return { saver, notices, permit };
}

test('typed edits coalesce, fields never touched or restored do not get posted', async () => {
  const calls = [];
  const {saver} = create({city:'NICE', pre_number:'PRE-original', address:'A'}, x => calls.push(x));
  saver.schedule('address', 'Ab');
  saver.schedule('address', 'Abc');
  saver.schedule('city', 'NICE');
  await saver.flush();
  await saver.flush();
  assert.deepEqual(calls, [{address:'Abc', _previous:{address:'A'}}]);
});

test('permit confirms once and reverting an in-flight edit sends the right baseline', async () => {
  const calls = [];
  let release;
  const {saver, permit} = create({city:'NICE', no_permis:false}, payload => {
    calls.push(payload);
    if(calls.length === 1) return new Promise(resolve => {release = resolve;});
  });
  saver.schedule('city','LYON'); saver.schedule('no_permis',true);
  const running = saver.flush();
  saver.schedule('city','NICE');
  await saver.flush();
  assert.equal(calls.length, 1);
  release(); await running;
  assert.deepEqual(calls[1], {city:'NICE', _previous:{city:'LYON'}});
  assert.equal(permit.length, 1);
});

test('transport failure retains only unsaved data and empty inputs never confirm a save', async () => {
  const calls = [];
  const {saver, notices} = create({address:'original',city:'NICE'}, p => {
    calls.push(p);
    if (calls.length === 1) throw new Error('connexion interrompue');
  });
  saver.schedule('address', 'nouvelle');
  await saver.flush();
  assert.deepEqual(notices.at(-1), ['connexion interrompue',true]);
  assert.ok(saver.hasPending());
  saver.schedule('city', '');
  await saver.flush();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1], {address:'nouvelle', _previous:{address:'original'}});
  assert.match(notices.at(-1)[0], /Champ vide/);
});

test('cleared and reverted fields do not block the confirmed permit or prompt on departure', async () => {
  let release;
  const calls = [];
  const {saver, notices, permit} = create({city:'NICE', address:'A', no_permis:false}, p => {
    calls.push(p);
    return new Promise(resolve => {release = resolve;});
  });
  saver.schedule('no_permis', true);
  const running = saver.flush();
  saver.schedule('city','LYON');
  saver.schedule('city','NICE');
  saver.schedule('address','');
  release();
  await running;
  assert.deepEqual(permit, [true]);
  assert.match(notices.at(-1)[0], /Champ vide/);
  assert.equal(calls.length, 1);
  assert.equal(saver.hasPending(), false);
});

for (const conflict of [false, true]) {
  test('lost answer is reconciled before newer input, concurrent change = ' + conflict, async () => {
    let stored = 'A';
    const calls = [];
    const {saver, notices} = create({city:'A'}, p => {
      calls.push(p);
      if (stored !== p.city && stored !== p._previous.city) {
        throw Object.assign(new Error('Conflit'), {rejected:true});
      }
      stored = p.city;
      if (calls.length === 1) throw new Error('Réponse perdue');
    });
    saver.schedule('city', 'B');
    await saver.flush();
    if (conflict) stored = 'D';
    saver.schedule('city', 'C');
    await saver.flush();
    assert.deepEqual(calls[1], {city:'B', _previous:{city:'A'}});
    if (conflict) {
      assert.equal(stored, 'D');
      assert.equal(calls.length, 2);
      assert.match(notices.at(-1)[0], /Conflit/);
    } else {
      assert.deepEqual(calls[2], {city:'C', _previous:{city:'B'}});
      assert.equal(stored, 'C');
      assert.equal(saver.hasPending(), false);
    }
  });
}

test('permit updates submitted indicators in place, preserving selected uploads', () => {
  const required = {hidden:false, files:['driving.pdf']};
  const exempt = {hidden:true};
  const classes = new Set();
  const row = {
    dataset:{permitSubmitted:'false', permitClass:'missing'},
    classList:{add: cls => classes.add(cls), remove: (...names) => names.forEach(n => classes.delete(n))},
    querySelectorAll: q => q === '[data-permit-waived]' ? [exempt] : [required],
  };
  const files = required.files;
  context.showSavedPermit(row, true);
  assert.ok(classes.has('valid'));
  assert.equal(row.dataset.docSubmitted, 'true');
  assert.equal(required.hidden, true);
  context.showSavedPermit(row, false);
  assert.ok(classes.has('missing'));
  assert.equal(row.dataset.docSubmitted, 'false');
  assert.equal(required.hidden, false);
  assert.equal(required.files, files);
});

test('both legacy and new PRE or CAR formats remain valid with or without department', () => {
  const template = fs.readFileSync(path.join(__dirname, '../templates/public_trainee.html'), 'utf8');
  const functions = ['formatPreCarDisplay', 'normalizePRE', 'isValidPRE'].map(name =>
    template.match(new RegExp("function " + name + "\\(.*?\n}", "s"))[0]);
  vm.runInNewContext(functions.join('\n'), context);
  for (const value of ['PRE-013-2029-07-25-20240908920', 'CAR-2029-07-25-20240908920', '2026-0002805-PRE-3P-1050370']) {
    assert.equal(context.normalizePRE(value), value);
    assert.equal(context.isValidPRE(value), true);
  }
  assert.equal(context.isValidPRE('PRE-013-2029'), false);
});
