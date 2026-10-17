const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/elearning-payment.js', 'utf8');
const root = '/admin/organisme/e-learning/commandes/order-1';
const urls = {order_url: root, status_url: root + '/statut', refresh_url: root + '/actualiser', confirmation_url: root + '/confirmation'};
const ready = {paid: false, checkout_url: 'https://pay.qonto.com/link-1', payment_status: 'unpaid'};
class Element {
  constructor(tag = '') { this.tag = tag; this.listeners = {}; this.dataset = {}; this.attributes = {}; this.hidden = false; this.textContent = ''; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  removeEventListener(name, fn) { this.listeners[name] = (this.listeners[name] || []).filter(value => value !== fn); }
  async trigger(name, fields = {}) { const event = {...fields, preventDefault() { this.prevented = true; }}; for (const fn of this.listeners[name] || []) await fn(event); return event; }
  setAttribute(name, value) { this.attributes[name] = value; }
  after(element) { this.afterElement = element; }
  remove() { this.removed = true; }
  prepend(element) { this.notice = element; }
  append(element) { (this.children ||= []).push(element); }
  scrollIntoView() {}
  focus() { this.focused = true; }
  showModal() { this.open = true; }
  close() { if (this.open) { this.open = false; this.trigger('close'); } }
  querySelector(selector) { return (this.nodes ||= {})[selector] ||= new Element(); }
}
function boot({free = false, failure = false, valid = true, blocked = false, payLink = false} = {}) {
  const events = [], timers = new Map(), watchers = new Map();
  let timerId = 0;
  const form = new Element(); form.action = root + '/confirmer'; form.dataset.elFree = String(free); form.checkValidity = () => valid;
  form.querySelector('button[type="submit"]').textContent = 'Valider et passer au paiement';
  form.querySelector('[name="csrf_token"]').value = 'csrf-test';
  form.dataset.elStatus = urls.status_url; form.dataset.elConfirmation = urls.confirmation_url; form.dataset.elRefresh = urls.refresh_url;
  const link = new Element(); link.closest = () => form;
  const document = new Element(); document.hidden = false; document.body = new Element(); document.activeElement = new Element();
  document.querySelectorAll = selector => selector === '[data-el-checkout]' && !payLink ? [form] : selector === '[data-el-pay]' && payLink ? [link] : [];
  document.createElement = tag => new Element(tag);
  const state = {current: ready, blocked, auth: false, network: false};
  const popups = [];
  const window = new Element();
  window.open = (_url, _target, features) => {
    events.push(['popup', features]);
    if (state.blocked) return null;
    const popup = {closed: false, opener: window, document: {write(text) { popup.html = text; }, close() {}}, location: {replace(url) { events.push(['payment', url]); }}, close() { this.closed = true; }, focus() {}};
    popups.push(popup); return popup;
  };
  window.history = {replaceState(_state, _title, url) { events.push(['history', url]); }};
  const location = {href: 'https://www.integraleconnect.com' + root, pathname: root, origin: 'https://www.integraleconnect.com', assign(value) { events.push(['navigate', value]); }};
  const fetch = async (url, options) => {
    events.push(['fetch', url, options.method || 'GET']);
    assert.ok(document.body.children.some(element => element.tag === 'dialog'), 'Show the dialog before the request');
    if (url.endsWith('/actualiser')) {
      assert.equal(options.method, 'POST'); assert.equal(options.body.get('csrf_token'), 'csrf-test');
      return {ok: true, redirected: false};
    }
    if (options.method === 'POST') return {ok: !failure, redirected: false, headers: {get: () => 'application/json'}, json: async () => urls};
    if (state.network) throw new Error('offline');
    return {ok: !state.auth, status: state.auth ? 401 : 200, redirected: false, json: async () => state.current};
  };
  vm.runInNewContext(source, {document, window, location, URL, Date, Object, FormData: class {constructor() { this.data = {}; } append(k, v) { this.data[k] = v; } get(k) { return this.data[k]; }}, fetch,
    clearTimeout(id) { timers.delete(id); }, setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    clearInterval(id) { watchers.delete(id); }, setInterval(fn) { watchers.set(++timerId, fn); return timerId; }});
  return {form, link, events, timers, watchers, state, window, document, popups,
    dialog: () => document.body.children.find(element => element.tag === 'dialog'),
    tick: async () => { const [id, fn] = timers.entries().next().value; timers.delete(id); await fn(); },
    watch: async () => { for (const fn of [...watchers.values()]) await fn(); }};
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const navigate = page => page.events.filter(event => event[0] === 'navigate');
const refreshed = page => page.events.some(event => event[0] === 'fetch' && event[1].endsWith('/actualiser'));

test('dialog and reserved popup open during the click; Connect stays open and Qonto has no opener', async () => {
  const page = boot();
  await page.form.trigger('submit'); await flush();
  assert.equal(page.dialog().open, true);
  assert.match(page.dialog().innerHTML, /Préparation du paiement en cours/);
  assert.match(page.dialog().innerHTML, /data-payment-close/);
  assert.ok(page.events.findIndex(event => event[0] === 'popup') < page.events.findIndex(event => event[0] === 'fetch'));
  assert.ok(page.events.some(event => event[0] === 'payment' && event[1] === ready.checkout_url));
  assert.equal(navigate(page).length, 0);
  assert.equal(page.popups[0].opener, null);
  assert.match(page.popups[0].html, /Préparation du paiement en cours/);
});

test('closing Qonto requests a server check but never confirms an unpaid order', async () => {
  const page = boot(); await page.form.trigger('submit'); await flush();
  page.popups[0].closed = true; await page.watch(); await flush();
  assert.ok(refreshed(page));
  assert.equal(navigate(page).length, 0);
  assert.match(page.dialog().querySelector('[data-payment-title]').textContent, /Vérification du paiement/);
  assert.equal(page.popups.length, 1, 'Never reopen a dismissed payment automatically');
});

test('closing the modal verifies payment and navigates only after the server confirms it', async () => {
  const page = boot(); await page.form.trigger('submit'); await flush();
  page.state.current = {paid: true, checkout_url: ''};
  await page.dialog().querySelector('[data-payment-close]').trigger('click'); await flush();
  assert.ok(refreshed(page));
  assert.equal(page.popups[0].closed, true);
  assert.deepEqual(navigate(page), [['navigate', 'https://www.integraleconnect.com' + urls.confirmation_url]]);
  assert.equal(page.watchers.size, 0); assert.equal(page.timers.size, 0);
});

test('returning to Connect or explicitly checking rechecks the server without a second charge', async () => {
  const page = boot({payLink: true}); await page.link.trigger('click'); await flush();
  await page.window.trigger('focus'); await flush();
  assert.ok(refreshed(page));
  assert.equal(page.events.filter(event => event[0] === 'payment').length, 1);
  page.state.current = {paid: true};
  await page.dialog().querySelector('[data-payment-check]').trigger('click'); await flush();
  assert.equal(navigate(page).length, 1);
});

test('a blocked popup can be opened from an explicit button without leaving Connect', async () => {
  const page = boot({blocked: true}); await page.form.trigger('submit'); await flush();
  assert.equal(page.dialog().querySelector('[data-payment-open]').hidden, false);
  assert.equal(navigate(page).length, 0);
  page.state.blocked = false;
  await page.dialog().querySelector('[data-payment-open]').trigger('click'); await flush();
  assert.ok(page.events.some(event => event[0] === 'payment'));
});

test('closing during preparation does not reopen Qonto once its link arrives', async () => {
  const page = boot(); page.state.current = {paid: false, checkout_url: ''};
  await page.form.trigger('submit'); await flush();
  page.popups[0].closed = true; await page.watch(); await flush();
  page.state.current = ready; await page.tick(); await flush();
  assert.equal(page.events.filter(event => event[0] === 'payment').length, 0);
  assert.equal(page.popups.length, 1);
});

test('authorized, processing and partial payments never navigate to success', async () => {
  for (const payment_status of ['authorized', 'processing', 'partially_paid']) {
    const page = boot(); page.state.current = {paid: false, checkout_url: '', payment_status};
    await page.form.trigger('submit'); await flush();
    await page.dialog().querySelector('[data-payment-check]').trigger('click'); await flush();
    assert.equal(navigate(page).length, 0);
  }
});

test('a free order skips Qonto and redirects to its server-verified confirmation', async () => {
  const page = boot({free: true}); await page.form.trigger('submit'); await flush();
  assert.equal(page.popups.length, 0);
  assert.deepEqual(navigate(page), [['navigate', 'https://www.integraleconnect.com' + urls.confirmation_url]]);
});

test('failed validation restores the form and releases tracking and reserved windows', async () => {
  const page = boot({failure: true}); await page.form.trigger('submit'); await flush();
  assert.equal(page.form.hidden, false); assert.equal(page.form.querySelector('button[type="submit"]').disabled, false);
  assert.equal(page.window.elPaymentInProgress, false); assert.equal(page.popups[0].closed, true);
  assert.equal(page.dialog().removed, true); assert.equal(page.watchers.size, 0);
});

test('double submission creates only one checkout and one window', async () => {
  const page = boot(); const first = page.form.trigger('submit');
  const second = await page.form.trigger('submit'); await first; await flush();
  assert.equal(second.prevented, true);
  assert.equal(page.events.filter(event => event[0] === 'fetch' && event[2] === 'POST').length, 1);
  assert.equal(page.popups.length, 1);
});

test('invalid required fields leave the form visible without a dialog or popup', async () => {
  const page = boot({valid: false}); await page.form.trigger('submit');
  assert.equal(page.events.length, 0); assert.equal(page.form.hidden, false);
});

test('network or authentication failures cannot confirm payment', async () => {
  for (const field of ['network', 'auth']) {
    const page = boot(); page.state[field] = true;
    await page.form.trigger('submit'); await flush();
    assert.equal(navigate(page).length, 0);
  }
});

test('an unexpected payment host cannot navigate either window', async () => {
  const page = boot(); page.state.current = {...ready, checkout_url: 'https://untrusted.example/pay'};
  await page.form.trigger('submit'); await flush();
  assert.equal(navigate(page).length, 0);
  assert.equal(page.events.filter(event => event[0] === 'payment').length, 0);
});
