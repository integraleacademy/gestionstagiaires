const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/elearning-payment.js', 'utf8');
const root = '/admin/organisme/e-learning/commandes/order-1';
const urls = {order_url: root, status_url: root + '/statut', confirmation_url: root + '/confirmation'};
const ready = {paid: false, checkout_url: 'https://pay.qonto.com/link-1', payment_status: 'unpaid'};
class Element {
  constructor() { this.listeners = {}; this.dataset = {}; this.style = {}; this.children = []; this.hidden = false; this.textContent = ''; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async trigger(name) { const event = {preventDefault() { this.prevented = true; }}; for (const fn of this.listeners[name] || []) await fn(event); return event; }
  setAttribute() {}
  append(...items) { this.children.push(...items); }
  after(element) { this.afterElement = element; }
  prepend(element) { this.notice = element; }
  scrollIntoView() {}
  querySelector(selector) { return (this.nodes ||= {})[selector] ||= new Element(); }
}
function boot({blocked = false, free = false, failure = false, valid = true} = {}) {
  const events = [], timers = [];
  const form = new Element(); form.action = root + '/confirmer'; form.dataset.elFree = String(free); form.checkValidity = () => valid;
  form.querySelector('button[type="submit"]').textContent = 'Valider et passer au paiement';
  const document = new Element(); document.hidden = false;
  document.querySelectorAll = selector => selector === '[data-el-checkout]' ? [form] : [];
  document.createElement = () => new Element();
  const popup = {closed: false, opener: {}, document: {body: new Element(), createElement: () => new Element()}, location: {replace(value) { events.push(['payment', value]); }}, close() { this.closed = true; events.push(['close']); }};
  const window = new Element();
  window.open = () => { events.push(['open']); return blocked ? null : popup; };
  window.focus = () => events.push(['focus']);
  const location = {href: 'https://www.integraleconnect.com/admin/organisme/e-learning/groupes/g/recapitulatif', origin: 'https://www.integraleconnect.com', assign(value) { events.push(['navigate', value]); }};
  const state = {current: ready};
  const fetch = async (url, options) => {
    events.push(['fetch', url, options.method || 'GET']);
    if (options.method === 'POST') return {ok: !failure, redirected: false, headers: {get: () => 'application/json'}, json: async () => urls};
    return {ok: true, redirected: false, json: async () => state.current};
  };
  vm.runInNewContext(source, {document, window, location, URL, Date, FormData: class {}, fetch, clearTimeout() {}, setTimeout(fn) { timers.push(fn); return timers.length; }});
  return {form, popup, events, timers, state, window};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('payment opens on the validation click, then confirmed capture closes it and shows Connect confirmation', async () => {
  const page = boot();
  await page.form.trigger('submit'); await flush();
  assert.equal(page.events[0][0], 'open');
  assert.equal(page.events[1][2], 'POST');
  assert.equal(page.popup.opener, null);
  assert.ok(page.events.some(event => event[0] === 'payment' && event[1] === ready.checkout_url));
  assert.equal(page.form.hidden, true);
  assert.ok(!page.events.some(event => event[0] === 'navigate'));
  page.state.current = {paid: true, checkout_url: ''};
  await page.timers.shift()(); await flush();
  assert.equal(page.popup.closed, true);
  assert.ok(page.events.some(event => event[0] === 'navigate' && event[1] === 'https://www.integraleconnect.com' + urls.confirmation_url));
});

test('blocked popup retains a working payment link and continues polling', async () => {
  const page = boot({blocked: true});
  await page.form.trigger('submit'); await flush();
  const link = page.form.afterElement.querySelector('[data-payment-open]');
  assert.equal(link.hidden, false);
  assert.equal(link.href, ready.checkout_url);
  assert.equal(page.timers.length, 1);
});

test('authorized or processing payment never navigates to a success screen', async () => {
  const page = boot();
  page.state.current = {paid: false, checkout_url: '', payment_status: 'processing'};
  await page.form.trigger('submit'); await flush();
  assert.ok(!page.events.some(event => event[0] === 'navigate'));
  assert.equal(page.form.afterElement.querySelector('[data-payment-open]').hidden, true);
  assert.ok(page.form.afterElement.querySelector('[data-payment-message]').textContent.includes('confirmation'));
});

test('a free order skips Qonto and redirects to its server-verified confirmation', async () => {
  const page = boot({free: true});
  await page.form.trigger('submit'); await flush();
  assert.ok(!page.events.some(event => event[0] === 'open'));
  assert.ok(page.events.some(event => event[0] === 'navigate'));
});

test('failed validation closes the preparation window and preserves the form', async () => {
  const page = boot({failure: true});
  await page.form.trigger('submit'); await flush();
  assert.equal(page.popup.closed, true);
  assert.equal(page.form.hidden, false);
  assert.equal(page.form.querySelector('button[type="submit"]').disabled, false);
});

test('double submission is prevented and creates only one checkout request', async () => {
  const page = boot();
  const first = page.form.trigger('submit');
  const second = await page.form.trigger('submit');
  await first; await flush();
  assert.equal(second.prevented, true);
  assert.equal(page.events.filter(event => event[0] === 'fetch' && event[2] === 'POST').length, 1);
});

test('invalid required fields do not open a payment window', async () => {
  const page = boot({valid: false});
  await page.form.trigger('submit');
  assert.equal(page.events.length, 0);
});
