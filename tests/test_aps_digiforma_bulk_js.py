import subprocess
from pathlib import Path


def test_bulk_queue_continues_after_bad_files_and_stops_after_session_expiry():
    script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('static/js/aps-digiforma-bulk.js', 'utf8');
class Element {
  constructor() { this.dataset = {}; this.listeners = {}; this.children = []; this.disabled = false; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren() { this.children = []; }
  querySelectorAll() { return this.buttons; }
}
async function run(expired) {
  const ids = ['apsDigiformaBulkDialog', 'btnImportDigiforma', 'apsDigiformaFiles',
               'apsBulkStart', 'apsBulkStatus', 'apsBulkProgress', 'apsBulkResults'];
  const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
  elements.apsDigiformaBulkDialog.dataset = {uploadUrl: '/upload', maxBytes: '26214400'};
  elements.apsDigiformaBulkDialog.buttons = [new Element(), new Element()];
  const requests = [];
  let active = 0, maxActive = 0;
  const context = {
    document: {getElementById: id => elements[id], createElement: () => new Element()},
    window: new Element(),
    FormData: class { constructor() { this.values = []; } append(...args) { this.values.push(args); } },
    fetch: async (url, options) => {
      active++; maxActive = Math.max(maxActive, active);
      const values = options.body.values;
      const file = values.find(([key]) => key === 'digiforma_pdf')[1];
      requests.push({name: file.name, ids: values.filter(([key]) => key === 'processed_trainee_ids').map(([,id]) => id)});
      await Promise.resolve(); active--;
      const invalid = file.name === 'bad.pdf';
      const status = invalid ? (expired ? 401 : 400) : 200;
      return {ok: status === 200, status, redirected: false,
        headers: {get: () => 'application/json'},
        json: async () => invalid ? {ok: false, error: expired ? 'Session expirée' : 'PDF illisible'} : {
          ok: true, status: 'imported', trainee_id: file.name, trainee_name: 'Candidat',
          trainee_url: '/trainee/' + file.name, duration: '44 h 54', attendance_rate: '72,4 %', message: 'Importé',
        },
      };
    },
  };
  vm.runInNewContext(source, context);
  elements.apsDigiformaFiles.files = ['alice.pdf', 'bad.pdf', 'notes.txt', 'bob.pdf'].map(name => ({name, size: 1000}));
  elements.apsDigiformaFiles.listeners.change();
  await elements.apsBulkStart.listeners.click();
  assert.equal(maxActive, 1, 'only one PDF should be in flight');
  assert.deepEqual(requests.map(r => r.name), expired ? ['alice.pdf', 'bad.pdf'] : ['alice.pdf', 'bad.pdf', 'bob.pdf']);
  assert.deepEqual(requests[1].ids, ['alice.pdf']);
  assert.equal(elements.apsDigiformaFiles.disabled, false);
  assert(elements.apsDigiformaBulkDialog.buttons.every(button => !button.disabled));
  assert.equal(elements.apsBulkResults.children[1].dataset.status, 'error');
  assert(elements.apsBulkStatus.textContent.includes(expired ? '1 importé(s)' : '2 importé(s)'));
  assert(elements.apsBulkStatus.textContent.includes(expired ? '3 à vérifier' : '2 à vérifier'));
}
(async () => { await run(false); await run(true); })().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1], check=True)
