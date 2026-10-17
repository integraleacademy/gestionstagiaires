const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/elearning-celebration.js', 'utf8');
function boot({verified = true, seen = false, reduced = false, storageFailure = false} = {}) {
  const events = {}, pieces = [], timers = new Map(), controls = [{}, {}];
  const confetti = {append(piece) { pieces.push(piece); }, replaceChildren() { pieces.length = 0; }};
  const heading = {setAttribute() {}, focus() { this.focused = true; }};
  const dialog = {dataset: {elCelebration: 'paid-order'}, querySelector: () => confetti, querySelectorAll: () => controls,
    addEventListener(name, fn) { events[name] = fn; }, showModal() { this.open = true; }, close() { this.open = false; events.close(); }};
  controls.forEach(control => control.addEventListener = (_event, fn) => { control.click = fn; });
  const window = {matchMedia: () => ({matches: reduced})};
  const storage = new Map(seen ? [['el-celebration:paid-order', 'shown']] : []);
  const document = {querySelector: selector => selector === '[data-el-celebration]' ? verified ? dialog : null : heading,
    createElement: () => ({style: {setProperty() {}}})};
  vm.runInNewContext(source, {document, window, sessionStorage: {getItem(key) { if (storageFailure) throw new Error(); return storage.get(key); }, setItem(key, value) { if (storageFailure) throw new Error(); storage.set(key, value); }}, Math,
    setTimeout(fn) { timers.set(1, fn); return 1; }, clearTimeout(id) { timers.delete(id); }});
  return {dialog, pieces, controls, window, timers, storage, heading};
}
test('only a server-rendered verified confirmation can celebrate', () => {
  const unpaid = boot({verified: false}); assert.equal(unpaid.dialog.open, undefined); assert.equal(unpaid.pieces.length, 0);
  const paid = boot(); assert.equal(paid.dialog.open, true); assert.equal(paid.pieces.length, 110);
});
test('dismissal clears animation, resumes normal tracking and focuses the order', () => {
  const page = boot(); page.controls[0].click();
  assert.equal(page.dialog.open, false); assert.equal(page.pieces.length, 0); assert.equal(page.timers.size, 0);
  assert.equal(page.window.elCelebrationInProgress, false); assert.equal(page.heading.focused, true);
});
test('the same order does not replay on reload', () => {
  const page = boot({seen: true}); assert.equal(page.dialog.open, undefined); assert.equal(page.pieces.length, 0);
});
test('reduced motion keeps the confirmation but omits moving confetti', () => {
  const page = boot({reduced: true}); assert.equal(page.dialog.open, true); assert.equal(page.pieces.length, 0);
});
test('blocked session storage never hides the confirmed result', () => {
  const page = boot({storageFailure: true}); assert.equal(page.dialog.open, true);
});

test('confetti repeats until dismissal without accumulating elements or marking the dialog seen early', () => {
  const page = boot();
  assert.equal(page.storage.get('el-celebration:paid-order'), undefined);
  const firstPiece = page.pieces[0];
  for (let wave = 0; wave < 3; wave++) {
    const fn = page.timers.get(1); page.timers.delete(1); fn();
    assert.equal(page.pieces.length, 110);
    assert.equal(page.timers.size, 1);
  }
  assert.notEqual(page.pieces[0], firstPiece);
  page.controls[0].click();
  assert.equal(page.timers.size, 0);
  assert.equal(page.pieces.length, 0);
  assert.equal(page.storage.get('el-celebration:paid-order'), 'shown');
});
