const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Exercise the actual UI handlers with a small DOM, without a browser or mail service.
function setup() {
  const nodes = new Map();
  class Element {
    constructor(id = '') {
      this.id = id; this.dataset = {}; this.listeners = {}; this.attributes = {};
      this.hidden = false; this.disabled = false; this.open = false; this.scrollTop = 0;
    }
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
    emit(type, event = {}) { return Promise.all((this.listeners[type] || []).map(fn => fn(event))); }
    setAttribute(key, value) { this.attributes[key] = value; }
    hasAttribute(key) { return key in this.attributes; }
    querySelectorAll() { return []; }
    closest(selector) {
      if (selector === 'button,a') return this;
      if (selector === '[data-juror]') return {dataset:{juror:'J1'}};
      return null;
    }
    replaceWith(next) { nodes.set(this.id, next); }
    showModal() { this.open = true; }
    close() { this.open = false; return this.emit('close'); }
  }
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, new Element(id));
    return nodes.get(id);
  };
  const base = '/api/admin/sessions/S1/ssiap-exam';
  get('ssiapExamDialog').dataset.url = base;
  const data = {
    csrf:'test-csrf', read_only:false, history:[], directory:[], excluded_count:0,
    collective_url:'/collective.pdf', attendance_url:'/attendance.pdf', mail_status:{}, automatic_reminders:{members:{J1:{status:'scheduled',label:'Programmé le 21/10/2026 à partir de 09:00'}}},
    config:{level:'SSIAP 1',date:'2026-10-28',time:'08:30',jury:[{id:'J1',email:'jury@example.test',role:'member'}]},
    candidates:[{id:'T1',first_name:'Camille',last_name:'EXEMPLE',candidate:{included:true},documents:[],
      dossier_url:'/dossier.pdf',pv_url:'/individual.pdf',edit_url:'/candidate'}]
  };
  const sent = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/ssiap-exam.js'), 'utf8'), {
    document:{getElementById:get,createElement:() => new Element()},
    fetch:async (url, options = {}) => {
      let result = data;
      if (url.endsWith('/preview')) {
        const kind = url.includes('/reminder/') ? 'reminder' : 'invitation';
        result = {to:'jury@example.test',subject:kind,html:`<h1>${kind}</h1>`,text:`Texte ${kind}`,preview_token:kind};
      } else if (url.endsWith('/mail/send')) {
        sent.push(JSON.parse(options.body)); result = {ok:true};
      }
      return {ok:true,json:async () => result};
    },
    setTimeout:() => 1, clearTimeout:() => {}, console
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  return {get, sent, settle, async preview(kind) {
    const button = new Element(); button.dataset.previewKind = kind;
    await get('ssiapExamDialog').emit('click',{target:button,preventDefault(){}});
    await settle();
    return get('ssiapExamMailFrame');
  }};
}

test('PDF primary actions open inline in a new tab; separate links download', async () => {
  const ui = setup();
  await ui.get('btnSsiapExam').emit('click'); await ui.settle();
  assert.match(ui.get('ssiapExamCandidates').innerHTML, /href="\/dossier.pdf" target="_blank" rel="noopener">Dossier examen PDF/);
  assert.match(ui.get('ssiapExamCollective').innerHTML, /href="\/collective.pdf" target="_blank" rel="noopener">Ouvrir le PV collectif/);
  assert.match(ui.get('ssiapExamCollective').innerHTML, /href="\/collective.pdf\?download=1"/);
  assert.match(ui.get('ssiapExamAttendance').innerHTML, /href="\/attendance.pdf" target="_blank"/);
  assert.match(ui.get('ssiapExamConfig').innerHTML, /Programmé le 21\/10\/2026/);
});

test('reminder reopens with a fresh frame, resets scroll and retains the send lock', async () => {
  const ui = setup();
  await ui.get('btnSsiapExam').emit('click'); await ui.settle();
  const invitation = await ui.preview('invitation');
  await invitation.emit('load'); invitation.scrollTop = 1200;
  ui.get('ssiapExamMailDialog').scrollTop = 500;
  await ui.get('ssiapExamMailDialog').close();
  const reminder = await ui.preview('reminder');
  assert.notEqual(reminder, invitation);
  assert.equal(reminder.srcdoc, '<h1>reminder</h1>');
  assert.equal(reminder.attributes.sandbox, '');
  assert.equal(reminder.scrollTop, 0);
  assert.equal(ui.get('ssiapExamMailDialog').scrollTop, 0);
  assert.equal(ui.get('ssiapExamSend').disabled, true);
  await reminder.emit('load');
  assert.equal(ui.get('ssiapExamMailLoading').hidden, true);
  assert.equal(ui.get('ssiapExamSend').disabled, false);
  await ui.get('ssiapExamMailTextToggle').emit('click');
  assert.equal(ui.get('ssiapExamMailText').textContent, 'Texte reminder');
  assert.equal(ui.get('ssiapExamMailText').hidden, false);
  assert.equal(reminder.hidden, true);
  await ui.get('ssiapExamSend').emit('click');
  assert.equal(ui.sent.length, 1);
  assert.equal(ui.sent[0].preview_token, 'reminder');
  await ui.get('ssiapExamMailTextToggle').emit('click');
  await ui.get('ssiapExamMailTextToggle').emit('click');
  assert.equal(ui.get('ssiapExamSend').disabled, true);
});
