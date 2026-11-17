const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');

const source = fs.readFileSync(path.join(__dirname, '../static/js/convocation-jobs.js'), 'utf8');

function fixture(results, storage = new Map()) {
  const calls = [];
  const browser = {
    window: {}, URL, location: new URL('https://example.test/admin/sessions'),
    crypto: { randomUUID }, setTimeout: callback => callback(),
    sessionStorage: {
      getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
      removeItem: key => storage.delete(key),
    },
    fetch: async (url, options) => {
      calls.push({ url: String(url), ...options });
      const next = results.shift();
      assert.ok(next, 'every outbound request must be expected');
      if (next instanceof Error) throw next;
      const [status, result, headers = {}] = next;
      return { status, ok: status >= 200 && status < 300, headers: new Headers(headers), json: async () => result };
    },
  };
  vm.runInNewContext(source, browser);
  return { jobs: browser.window.convocationJobs, calls };
}

const send = '/admin/sessions/a/stagiaires/b/convocation-aps/send';
const queued = [202, { ok: true, status: 'queued', status_url: '/admin/jobs/1' }];
const success = [200, { ok: true, status: 'sent' }];

test('acceptance and transient polling failures do not mark a convocation sent or replay the POST', async () => {
  const { jobs, calls } = fixture([queued, [502, null], [202, { ok:true, status:'running' }], success]);
  const states = [];
  const job = await jobs.submit(send, { skip_if_already_sent:true });
  const result = await jobs.wait(job, status => states.push(status));
  assert.equal(result.status, 'sent');
  assert.ok(states.includes('queued') && states.includes('running'));
  assert.deepEqual(calls.map(c => c.method || 'GET'), ['POST','GET','GET','GET']);
  assert.equal(calls[0].headers.Prefer, 'respond-async');
  assert.equal(calls[0].body, '{"skip_if_already_sent":true}');
});

test('uncertain submission keeps the same key on reload, an intentional resend gets a new key', async () => {
  const storage = new Map();
  const first = fixture([new Error('offline')], storage);
  await assert.rejects(first.jobs.submit(send), /interrompue/);
  const reloaded = fixture([success, success], storage);
  await reloaded.jobs.wait(await reloaded.jobs.submit(send));
  await reloaded.jobs.wait(await reloaded.jobs.submit(send));
  const keyOf = call => call.headers['Idempotency-Key'];
  assert.equal(keyOf(first.calls[0]), keyOf(reloaded.calls[0]));
  assert.notEqual(keyOf(reloaded.calls[0]), keyOf(reloaded.calls[1]));
});

test('restricted destinations and failed terminal delivery are errors', async () => {
  const other = fixture([[202,{ ok:true, status_url:'https://other.test/job' }]]);
  await assert.rejects(other.jobs.submit(send), /indisponible/);
  const failed = fixture([queued, [409,{ ok:false, uncertain:true, error:'Vérifiez l’historique.' }]]);
  await assert.rejects(failed.jobs.wait(await failed.jobs.submit(send)), /historique/);
  assert.equal(failed.calls.length, 2);
});

test('a group is queued before polling and each final row reflects its own outcome', async () => {
  const bulkScript = fs.readFileSync(path.join(__dirname, '../static/js/ssiap-pathways.js'), 'utf8');
  const nodes = {};
  for (const id of ['ssiapFeedback','ssiapBulkSend','ssiapBulkFilter','ssiapSelectVisible']) {
    nodes[id] = { addEventListener(type, callback) { this[type] = callback; } };
  }
  const rows = ['one','two','three'].map(url => {
    const box = { checked: true }, state = {};
    return { box, state, dataset: { sendUrl:url }, querySelector: selector => selector === 'input' ? box : state };
  });
  const events = [];
  vm.runInNewContext(bulkScript, {
    document: { getElementById: id => nodes[id], querySelectorAll: () => rows },
    window: { convocationJobs: {
      submit: async (url, payload) => {
        assert.equal(payload.skip_if_already_sent, true);
        events.push('submit:' + url);
        return { url, statusUrl:'/admin/jobs/' + url };
      },
      wait: async (job, progress) => {
        events.push('wait:' + job.url);
        progress('running');
        if (job.url === 'three') throw new Error('Vérifiez l’historique.');
        return { ok:true, skipped:job.url === 'two' };
      },
    } },
  });
  await nodes.ssiapBulkSend.click();
  assert.deepEqual(events, ['submit:one', 'submit:two', 'submit:three', 'wait:one', 'wait:two', 'wait:three']);
  assert.deepEqual(rows.map(row => row.state.textContent), ['Envoyée', 'Déjà envoyée', 'Vérifiez l’historique.']);
  assert.match(nodes.ssiapFeedback.textContent, /1 à vérifier/);
});


test('a confirmed terminal PDF generation failure can be retried after correcting the issue', async () => {
  const storage = new Map();
  const first = fixture([queued, [500, {ok:false, error:'Modèle indisponible.'}, {'X-Convocation-Job-State':'finished'}]], storage);
  await assert.rejects(first.jobs.wait(await first.jobs.submit(send)), /Modèle/);
  const retry = fixture([success], storage);
  await retry.jobs.submit(send);
  assert.notEqual(retry.calls[0].headers['Idempotency-Key'], first.calls[0].headers['Idempotency-Key']);
});
