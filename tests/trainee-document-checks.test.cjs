const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const photoAccept = '.jpg,.jpeg,.png,.webp,.heic,.heif,.tif,.tiff,.bmp,.gif,.avif';

function setup(kind = 'photo', fetcher = async () => ({status: 200, json: async () => ({summary: {status: 'success', title: 'Photo : c’est bon !', message: ''}, receipt: 'signed-receipt'})})) {
  const modal = fs.readFileSync(path.join(__dirname, '../templates/_trainee_document_check_modal.html'), 'utf8');
  const markup = `<form data-document-check-url="/check" data-document-key="${kind}" data-document-label="Document" data-max-bytes="26214400" data-max-files="${kind === 'id' ? 2 : 1}">
    <input name="document_check_token" value="csrf"><input name="document_check_receipt" value="">
    <input type="file" accept="${kind === 'photo' ? photoAccept : ''}" ${kind === 'id' ? 'multiple' : ''}><ul class="tdc-files"></ul><div class="tdc-feedback"></div><button type="submit">Déposer</button><div class="uploading-msg" hidden></div></form>${modal}`;
  const dom = new JSDOM(markup, {runScripts: 'outside-only', url: 'https://test.example/'});
  const {window} = dom;
  window.HTMLDialogElement.prototype.showModal = function() { this.open = true; };
  window.HTMLDialogElement.prototype.close = function() { this.open = false; };
  window.DataTransfer = class { constructor() {this.files = []; this.items = {add: file => this.files.push(file)};} };
  const form = window.document.querySelector('form');
  const input = form.querySelector('input[type=file]');
  let files = [];
  Object.defineProperty(input, 'files', {get: () => files, set: value => {files = value;}});
  let calls = 0; window.fetch = (...args) => {calls++; return fetcher(...args);};
  let pickerClicks = 0;
  const nativeClick = window.HTMLInputElement.prototype.click;
  window.HTMLInputElement.prototype.click = function() { if (this.type === 'file') pickerClicks++; nativeClick.call(this); };
  let submitted = 0;
  form.requestSubmit = () => {const event = new window.Event('submit', {bubbles: true, cancelable: true}); form.dispatchEvent(event); if (!event.defaultPrevented) submitted++;};
  window.eval(fs.readFileSync(path.join(__dirname, '../static/js/trainee-document-checks.mjs'), 'utf8').replace('export function selectionError', 'function selectionError'));
  const choose = (...names) => {input.files = names.map(name => new window.File(['document'], name, {lastModified: 1})); input.dispatchEvent(new window.Event('change'));};
  const replacementPicker = () => window.document.querySelector('[data-tdc-replacement-picker]');
  const chooseReplacement = (...names) => {
    const picker = replacementPicker();
    assert.ok(picker, 'replacement file picker is open');
    Object.defineProperty(picker, 'files', {value: names.map(name => new window.File(['replacement'], name, {lastModified: 2})), configurable: true});
    picker.dispatchEvent(new window.Event('change'));
  };
  const cancelReplacement = () => replacementPicker().dispatchEvent(new window.Event('cancel'));
  return {window, form, input, choose, chooseReplacement, cancelReplacement, replacementPicker, get pickerClicks() {return pickerClicks;}, get calls() {return calls;}, get submitted() {return submitted;}, dialog: window.document.getElementById('traineeDocumentCheck'), close: () => dom.window.close()};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('a PDF identity photo opens a correction modal without an analysis or an upload', () => {
  const ui = setup(); ui.choose('scan.pdf');
  assert.equal(ui.dialog.dataset.status, 'invalid'); assert.equal(ui.dialog.open, true);
  assert.equal(ui.calls, 0); assert.equal(ui.submitted, 0);
  assert.equal(ui.window.document.getElementById('tdcSecondary').hidden, true); ui.close();
});

test('documents in Word, HEIC and other formats reach the server for conversion', async () => {
  for (const name of ['attestation.docx', 'recto.HEIC', 'tableau.xlsx', 'scan.tiff', 'document.pages', 'document']) {
    const ui = setup('id'); ui.choose(name);
    assert.equal(ui.dialog.dataset.status, 'pending', name);
    assert.match(ui.window.document.getElementById('tdcMessage').textContent, /convertissons votre fichier en PDF/);
    assert.equal(ui.calls, 1, name); assert.equal(ui.submitted, 0, name);
    await settle(); assert.equal(ui.dialog.dataset.status, 'success', name); ui.close();
  }
});

test('an HEIC identity photo reaches the server and stays described as an image', async () => {
  const ui = setup(); ui.choose('portrait.HEIC');
  assert.equal(ui.dialog.dataset.status, 'pending'); assert.equal(ui.calls, 1);
  assert.match(ui.window.document.getElementById('tdcMessage').textContent, /restera une image/);
  await settle(); assert.equal(ui.dialog.dataset.status, 'success'); ui.close();
});

test('newly accepted document formats keep the empty-file and size checks', () => {
  const ui = setup('cv');
  const limit = 26214400;
  assert.match(ui.window.selectionError([{name: 'vide.docx', size: 0}], '', limit, 1), /vide/);
  assert.match(ui.window.selectionError([{name: 'trop-grand.heic', size: limit}], '', limit, 1), /inférieur/);
  ui.close();
});

test('a successful analysis is sent only after the deposit button is clicked', async () => {
  const ui = setup(); ui.choose('photo.png');
  assert.equal(ui.dialog.dataset.status, 'pending'); assert.equal(ui.submitted, 0);
  await settle(); assert.equal(ui.dialog.dataset.status, 'success');
  assert.equal(ui.form.elements.document_check_receipt.value, 'signed-receipt');
  ui.window.document.getElementById('tdcPrimary').click();
  assert.equal(ui.submitted, 1); assert.equal(ui.calls, 1); ui.close();
});

test('warning allows replacement, file removal clears its signed result', async () => {
  const ui = setup('photo', async () => ({status: 200, json: async () => ({summary: {status: 'warning', title: 'Photo à remplacer', message: 'Plusieurs portraits.'}, receipt: 'warning-receipt'})}));
  ui.choose('planche.png'); await settle();
  assert.equal(ui.dialog.dataset.status, 'warning');
  ui.window.document.getElementById('tdcPrimary').click();
  assert.equal(ui.dialog.open, false); assert.equal(ui.form.elements.document_check_receipt.value, '');
  ui.form.querySelector('.tdc-files button').click(); assert.equal(ui.input.files.length, 0); assert.equal(ui.submitted, 0); ui.close();
});

test('warning can be explicitly deposited without becoming a successful check', async () => {
  const ui = setup('photo', async () => ({status: 200, json: async () => ({summary: {status: 'warning', title: 'Photo à remplacer', message: 'Plusieurs portraits.'}, receipt: 'warning-receipt'})}));
  ui.choose('planche.png'); await settle(); ui.window.document.getElementById('tdcSecondary').click();
  assert.equal(ui.submitted, 1); assert.equal(ui.form.elements.document_check_receipt.value, 'warning-receipt'); ui.close();
});

test('cancelled or replaced selections never receive a stale green result', async () => {
  let finish;
  const ui = setup('photo', () => new Promise(resolve => {finish = resolve;}));
  ui.choose('old.png'); ui.window.document.querySelector('[data-tdc-close]').click();
  ui.form.querySelector('.tdc-files button').click();
  finish({status: 200, json: async () => ({summary: {status: 'success'}, receipt: 'stale'})});
  await settle(); assert.equal(ui.form.elements.document_check_receipt.value, ''); assert.equal(ui.dialog.open, false); ui.close();
});

test('outage is inconclusive and can be deposited for manual review', async () => {
  const ui = setup('photo', async () => {throw new Error('offline');});
  ui.choose('photo.png'); await settle(); assert.equal(ui.dialog.dataset.status, 'unknown');
  assert.equal(ui.window.document.getElementById('tdcTitle').textContent, 'Vérification automatique indisponible');
  assert.match(ui.window.document.getElementById('tdcMessage').textContent, /service de vérification.*inaccessible/);
  assert.match(ui.window.document.getElementById('tdcMessage').textContent, /Cela ne signifie pas que votre document est illisible/);
  ui.window.document.getElementById('tdcSecondary').click(); assert.equal(ui.submitted, 1); ui.close();
});

test('identity selection retains both files and an excess file is never silently discarded', async () => {
  const ui = setup('id'); ui.choose('recto.pdf'); await settle();
  ui.window.document.querySelector('[data-tdc-close]').click(); ui.choose('verso.pdf'); await settle();
  assert.equal(ui.input.files.length, 2);
  ui.window.document.querySelector('[data-tdc-close]').click(); ui.choose('extra.pdf');
  assert.equal(ui.dialog.dataset.status, 'invalid'); assert.equal(ui.input.files.length, 3);
  assert.equal(ui.calls, 2); ui.close();
});

test('unknown result offers replacement, retry and manual deposit, without submitting', async () => {
  const ui = setup('id', async () => ({status: 200, json: async () => ({summary: {status: 'unknown'}, receipt: 'unknown-receipt'})}));
  ui.choose('old-recto.jpg', 'old-verso.jpg'); await settle();
  assert.equal(ui.window.document.getElementById('tdcTitle').textContent, 'Vérification automatique indisponible');
  assert.match(ui.window.document.getElementById('tdcMessage').textContent, /n’a pas renvoyé de résultat exploitable/);
  const replace = ui.window.document.getElementById('tdcReplace');
  assert.equal(replace.hidden, false); assert.equal(replace.textContent, 'Choisir un autre document');
  assert.match(ui.window.document.getElementById('tdcPrimary').textContent, /Réessayer/);
  assert.match(ui.window.document.getElementById('tdcSecondary').textContent, /Déposer pour vérification/);
  replace.click();
  assert.equal(ui.pickerClicks, 1); assert.equal(ui.submitted, 0);
  assert.equal(ui.replacementPicker().multiple, true);
  assert.equal(ui.form.elements.document_check_receipt.value, '');
  ui.chooseReplacement('replacement.pdf');
  assert.deepEqual(Array.from(ui.input.files, file => file.name), ['replacement.pdf']);
  assert.equal(ui.calls, 2); assert.equal(ui.submitted, 0);
  assert.equal(ui.form.elements.document_check_receipt.value, '');
  await settle(); assert.equal(ui.dialog.dataset.status, 'unknown'); ui.close();
});

test('cancelling replacement preserves selection and normal identity selection still appends a side', async () => {
  const ui = setup('id', async () => ({status: 200, json: async () => ({summary: {status: 'unknown'}, receipt: 'unknown-receipt'})}));
  ui.choose('recto.jpg'); await settle();
  ui.window.document.getElementById('tdcReplace').click();
  ui.cancelReplacement();
  assert.deepEqual(Array.from(ui.input.files, file => file.name), ['recto.jpg']);
  assert.equal(ui.replacementPicker(), null); assert.equal(ui.calls, 1); assert.equal(ui.submitted, 0);
  ui.choose('verso.jpg'); await settle();
  assert.deepEqual(Array.from(ui.input.files, file => file.name), ['recto.jpg', 'verso.jpg']);
  assert.equal(ui.calls, 2); assert.equal(ui.submitted, 0); ui.close();
});

test('empty replacement change also preserves both original identity files', async () => {
  const ui = setup('id', async () => ({status: 200, json: async () => ({summary: {status: 'unknown'}})}));
  ui.choose('recto.jpg', 'verso.jpg'); await settle();
  ui.window.document.getElementById('tdcReplace').click();
  ui.chooseReplacement();
  assert.deepEqual(Array.from(ui.input.files, file => file.name), ['recto.jpg', 'verso.jpg']);
  assert.equal(ui.calls, 1); assert.equal(ui.submitted, 0); ui.close();
});

test('replacement ignores late results and receipts from the previous selection', async () => {
  const resolvers = [];
  const ui = setup('id', () => new Promise(resolve => resolvers.push(resolve)));
  ui.choose('old.pdf');
  ui.window.document.getElementById('tdcPrimary').click();
  assert.equal(ui.pickerClicks, 1);
  ui.chooseReplacement('new.pdf');
  assert.equal(ui.calls, 2);
  resolvers[1]({status: 200, json: async () => ({summary: {status: 'warning', title: 'Nouveau document à vérifier'}, receipt: 'new-receipt'})});
  await settle();
  resolvers[0]({status: 200, json: async () => ({summary: {status: 'success', title: 'Ancien résultat'}, receipt: 'stale-receipt'})});
  await settle();
  assert.deepEqual(Array.from(ui.input.files, file => file.name), ['new.pdf']);
  assert.equal(ui.dialog.dataset.status, 'warning');
  assert.equal(ui.window.document.getElementById('tdcTitle').textContent, 'Nouveau document à vérifier');
  assert.equal(ui.form.elements.document_check_receipt.value, 'new-receipt');
  assert.equal(ui.submitted, 0); ui.close();
});

test('invalid and warning results open an actual replacement picker', async () => {
  const invalid = setup(); invalid.choose('portrait.pdf');
  invalid.window.document.getElementById('tdcPrimary').click();
  assert.equal(invalid.pickerClicks, 1); assert.equal(invalid.replacementPicker().accept, photoAccept);
  invalid.chooseReplacement('portrait.png'); await settle();
  assert.equal(invalid.dialog.dataset.status, 'success'); assert.equal(invalid.submitted, 0); invalid.close();
  const warning = setup('id', async () => ({status: 200, json: async () => ({summary: {status: 'warning'}})}));
  warning.choose('old.pdf'); await settle(); warning.window.document.getElementById('tdcPrimary').click();
  assert.equal(warning.pickerClicks, 1); warning.chooseReplacement('new.pdf'); await settle();
  assert.deepEqual(Array.from(warning.input.files, file => file.name), ['new.pdf']);
  assert.equal(warning.submitted, 0); warning.close();
});
