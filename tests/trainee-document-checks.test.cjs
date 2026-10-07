const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

function setup(kind = 'photo', fetcher = async () => ({status: 200, json: async () => ({summary: {status: 'success', title: 'Photo : c’est bon !', message: ''}, receipt: 'signed-receipt'})})) {
  const modal = fs.readFileSync(path.join(__dirname, '../templates/_trainee_document_check_modal.html'), 'utf8');
  const markup = `<form data-document-check-url="/check" data-document-key="${kind}" data-document-label="Document" data-max-bytes="26214400" data-max-files="${kind === 'id' ? 2 : 1}">
    <input name="document_check_token" value="csrf"><input name="document_check_receipt" value="">
    <input type="file" accept="${kind === 'id' ? 'application/pdf' : 'image/jpeg,image/png'}"><ul class="tdc-files"></ul><div class="tdc-feedback"></div><button type="submit">Déposer</button><div class="uploading-msg" hidden></div></form>${modal}`;
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
  let submitted = 0;
  form.requestSubmit = () => {const event = new window.Event('submit', {bubbles: true, cancelable: true}); form.dispatchEvent(event); if (!event.defaultPrevented) submitted++;};
  window.eval(fs.readFileSync(path.join(__dirname, '../static/js/trainee-document-checks.mjs'), 'utf8').replace('export function selectionError', 'function selectionError'));
  const choose = (...names) => {input.files = names.map(name => new window.File(['document'], name, {lastModified: 1})); input.dispatchEvent(new window.Event('change'));};
  return {window, form, input, choose, get calls() {return calls;}, get submitted() {return submitted;}, dialog: window.document.getElementById('traineeDocumentCheck'), close: () => dom.window.close()};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('wrong extension opens a correction modal without an analysis or an upload', () => {
  const ui = setup(); ui.choose('scan.pdf');
  assert.equal(ui.dialog.dataset.status, 'invalid'); assert.equal(ui.dialog.open, true);
  assert.equal(ui.calls, 0); assert.equal(ui.submitted, 0);
  assert.equal(ui.window.document.getElementById('tdcSecondary').hidden, true); ui.close();
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
