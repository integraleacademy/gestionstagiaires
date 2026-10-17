const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/elearning-payment.js', 'utf8');
const root = '/admin/organisme/e-learning/commandes/order-1';
const urls = {order_url: root, status_url: root + '/statut', confirmation_url: root + '/confirmation'};
const ready = {paid: false, checkout_url: 'https://pay.qonto.com/link-1', payment_status: 'unpaid'};
class Element {
  constructor() { this.listeners = {}; this.dataset = {}; this.attributes = {}; this.hidden = false; this.textContent = ''; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async trigger(name, fields = {}) { const event = {...fields, preventDefault() { this.prevented = true; }}; for (const fn of this.listeners[name] || []) await fn(event); return event; }
  setAttribute(name, value) { this.attributes[name] = value; }
  after(element) { this.afterElement = element; }
  remove() { this.removed = true; }
  prepend(element) { this.notice = element; }
  scrollIntoView() {}
  querySelector(selector) { return (this.nodes ||= {})[selector] ||= new Element(); }
}
function boot({free = false, failure = false, valid = true} = {}) {
  const events = [], timers = [];
  const form = new Element(); form.action = root + '/confirmer'; form.dataset.elFree = String(free); form.checkValidity = () => valid;
  form.querySelector('button[type="submit"]').textContent = 'Valider et passer au paiement';
  const document = new Element(); document.hidden = false;
  document.querySelectorAll = selector => selector === '[data-el-checkout]' ? [form] : [];
  document.createElement = () => new Element();
  const window = new Element();
  window.open = () => { throw new Error('Checkout must stay in this tab'); };
  window.history = {replaceState(_state, _title, url) { events.push(['history', url]); }};
  const location = {href: 'https://www.integraleconnect.com/admin/organisme/e-learning/groupes/g/recapitulatif', origin: 'https://www.integraleconnect.com', assign(value) { events.push(['navigate', value]); }};
  const state = {current: ready};
  const fetch = async (url, options) => {
    events.push(['fetch', url, options.method || 'GET']);
    assert.ok(form.afterElement, 'Show the preparation before waiting for the request');
    if (options.method === 'POST') return {ok: !failure, redirected: false, headers: {get: () => 'application/json'}, json: async () => urls};
    return {ok: true, redirected: false, json: async () => state.current};
  };
  vm.runInNewContext(source, {document, window, location, URL, Date, FormData: class {}, fetch, clearTimeout() {}, setTimeout(fn) { timers.push(fn); return timers.length; }});
  return {form, events, timers, state, window};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('validation shows the spinner immediately and opens Qonto in the same tab', async () => {
  const page = boot();
  await page.form.trigger('submit'); await flush();
  assert.match(page.form.afterElement.innerHTML, /Préparation du paiement en cours/);
  assert.match(page.form.afterElement.innerHTML, /el-payment-orbit/);
  assert.ok(!page.form.afterElement.innerHTML.includes('target="_blank"'));
  assert.ok(page.events.some(event => event[0] === 'navigate' && event[1] === ready.checkout_url));
  assert.ok(page.events.some(event => event[0] === 'history' && event[1] === 'https://www.integraleconnect.com' + root));
  assert.equal(page.form.hidden, true);
  assert.equal(page.timers.length, 0);
});

test('returning with browser Back checks payment without reopening Qonto, then shows confirmation', async () => {
  const page = boot();
  await page.form.trigger('submit'); await flush();
  await page.window.trigger('pageshow', {persisted: true}); await flush();
  assert.equal(page.events.filter(event => event[0] === 'navigate').length, 1);
  assert.equal(page.form.afterElement.querySelector('[data-payment-open]').hidden, false);
  page.state.current = {paid: true, checkout_url: ''};
  await page.timers.shift()(); await flush();
  assert.equal(page.events.filter(event => event[0] === 'navigate' && event[1] === ready.checkout_url).length, 1);
  assert.ok(page.events.some(event => event[0] === 'navigate' && event[1] === 'https://www.integraleconnect.com' + urls.confirmation_url));
});

test('waiting for creation stays on the preparation screen until the payment link is ready', async () => {
  const page = boot();
  page.state.current = {paid: false, checkout_url: '', status: 'pending'};
  await page.form.trigger('submit'); await flush();
  assert.ok(!page.events.some(event => event[0] === 'navigate'));
  assert.equal(page.form.afterElement.attributes['aria-busy'], 'true');
  page.state.current = ready;
  await page.timers.shift()(); await flush();
  assert.ok(page.events.some(event => event[0] === 'navigate' && event[1] === ready.checkout_url));
});

test('authorized or processing payment never navigates to a success screen', async () => {
  const page = boot();
  page.state.current = {paid: false, checkout_url: '', payment_status: 'processing'};
  await page.form.trigger('submit'); await flush();
  assert.ok(!page.events.some(event => event[0] === 'navigate'));
  assert.equal(page.form.afterElement.querySelector('[data-payment-open]').hidden, true);
});

test('a free order skips Qonto and redirects to its server-verified confirmation', async () => {
  const page = boot({free: true});
  await page.form.trigger('submit'); await flush();
  assert.deepEqual(page.events.filter(event => event[0] === 'navigate'), [['navigate', 'https://www.integraleconnect.com' + urls.confirmation_url]]);
});

test('failed validation restores the form and releases background status tracking', async () => {
  const page = boot({failure: true});
  await page.form.trigger('submit'); await flush();
  assert.equal(page.form.afterElement.removed, true);
  assert.equal(page.form.hidden, false);
  assert.equal(page.form.querySelector('button[type="submit"]').disabled, false);
  assert.equal(page.window.elPaymentInProgress, false);
});

test('double submission creates only one checkout request', async () => {
  const page = boot();
  const first = page.form.trigger('submit');
  const second = await page.form.trigger('submit');
  await first; await flush();
  assert.equal(second.prevented, true);
  assert.equal(page.events.filter(event => event[0] === 'fetch' && event[2] === 'POST').length, 1);
});

test('invalid required fields keep the form visible', async () => {
  const page = boot({valid: false});
  await page.form.trigger('submit');
  assert.equal(page.events.length, 0);
  assert.equal(page.form.hidden, false);
});

test('an unexpected payment host cannot navigate the browser', async () => {
  const page = boot();
  page.state.current = {...ready, checkout_url: 'https://untrusted.example/pay'};
  await page.form.trigger('submit'); await flush();
  assert.ok(!page.events.some(event => event[0] === 'navigate'));
});
