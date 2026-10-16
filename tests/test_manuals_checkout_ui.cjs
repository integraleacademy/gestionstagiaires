const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/js/manuals-shop.js'), 'utf8');

function fixture(initialUrl = '', responses = []) {
  const requests = [], visits = [], history = [], timers = [], listeners = {};
  const orderUrl = '/admin/manuels/commandes/order-1';
  let now = 0;
  const location = { assign: url => visits.push(['assign', url]), replace: url => visits.push(['replace', url]), reload: () => visits.push(['reload']) };
  const window = { location, addEventListener: (event, fn) => (listeners[event] ||= []).push(fn), open: () => assert.fail('Checkout must not open a new tab') };
  const context = {
    window, location, URL, AbortSignal,
    Date: { now: () => now },
    history: { replaceState: (_, __, url) => history.push(url) },
    document: { querySelectorAll: () => [], querySelector: selector => selector === '[data-checkout]' ? { dataset: { checkoutStatus: orderUrl + '/paiement/statut', checkoutUrl: initialUrl, orderUrl } } : null },
    setTimeout: (fn, delay) => { timers.push({fn, delay}); return timers.length; }, clearTimeout: () => {},
    fetch: async (url, options) => {
      requests.push({ url, options });
      const next = responses.shift();
      if (next instanceof Error) throw next;
      return { ok: true, redirected: false, json: async () => next };
    },
  };
  vm.runInNewContext(source, context);
  return { requests, visits, history, timers, orderUrl, advance: ms => now += ms, event: (name, event = {}) => (listeners[name] || []).forEach(fn => fn(event)) };
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const paymentUrl = 'https://pay.qonto.com/link-1?resource_id=basket-1';

test('Validation waits for checkout then opens it automatically in the current tab', async () => {
  const f = fixture('', [{ waiting: true, payment_url: '' }, { waiting: false, payment_url: paymentUrl }]);
  await flush();
  assert.deepEqual(f.visits, []);
  assert.equal(f.timers[0].delay, 2000);
  await f.timers.shift().fn();
  assert.deepEqual(f.visits, [['assign', paymentUrl]]);
  assert.deepEqual(f.history, [f.orderUrl]);
  assert.equal(f.requests.length, 2);
  assert.equal(f.requests[0].options.cache, 'no-store');
  assert.equal(f.requests[0].options.credentials, 'same-origin');
  assert.equal(f.requests[0].options.method, undefined); // Read only, no new order.
});

test('An already available checkout opens immediately; Back reloads order tracking', () => {
  const f = fixture(paymentUrl);
  assert.deepEqual(f.visits, [['assign', paymentUrl]]);
  assert.equal(f.requests.length, 0);
  f.event('pageshow', { persisted: true });
  assert.deepEqual(f.visits.at(-1), ['reload']);
  assert.deepEqual(f.history, [f.orderUrl]);
});

test('Paid or unavailable checkout returns to order tracking without opening payment', async () => {
  const f = fixture('', [{ waiting: false, payment_url: '' }]);
  await flush();
  assert.deepEqual(f.visits, [['replace', f.orderUrl]]);
  assert.equal(f.timers.length, 0);
});

test('A connection failure retries without resubmitting, then stops after two minutes', async () => {
  const f = fixture('', [new Error('Network unavailable')]);
  await flush();
  f.advance(120000);
  await f.timers.shift().fn();
  assert.equal(f.requests.length, 1);
  assert.deepEqual(f.visits, [['replace', f.orderUrl]]);
});

test('Leaving while polling prevents a late response from reopening payment', async () => {
  const f = fixture('', [{ waiting: false, payment_url: paymentUrl }]);
  f.event('pagehide');
  await flush();
  assert.deepEqual(f.visits, []);
});

test('An untrusted checkout address is never opened', () => {
  const f = fixture('https://pay.qonto.com.evil.test/checkout');
  assert.deepEqual(f.visits, [['replace', f.orderUrl]]);
});
