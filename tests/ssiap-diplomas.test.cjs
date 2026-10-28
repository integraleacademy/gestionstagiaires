const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const template = fs.readFileSync('templates/_ssiap_exam_modal.html', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(t, options = {}) {
  const dom = new JSDOM(template, {url:'https://app.example/',runScripts:'outside-only'});
  t.after(() => dom.window.close());
  const w = dom.window, doc = w.document, panel = doc.getElementById('ssiapExamDiplomas');
  panel.dataset.url = '/api/diplomas';
  w.HTMLDialogElement.prototype.showModal = function() { this.open = true; };
  w.HTMLDialogElement.prototype.close = function() { this.open = false; this.dispatchEvent(new w.Event('close')); };
  w.URL.createObjectURL = () => 'blob:preview'; w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function() {};
  const values = {civility:'Monsieur',first_name:'Clément',last_name:'VAILLANT',birth_date:'1993-09-16',birth_city:'SALLANCHES',birth_department:'74',birth_country:'France',exam_date:'2026-10-28',result:'pending_results'};
  const data = {csrf:'token',read_only:!!options.readOnly,department_url:'/department',candidates:[
    {id:'T1',revision:'r1',values:{...values},included:true,number:'',missing:[],photo_available:true},
    {id:'T2',revision:'r2',values:{...values,first_name:'Camille',last_name:'AUTRE',result:'failed'},included:true,number:'',missing:[],photo_available:false}
  ]};
  const calls = [];
  w.fetch = async (url, config = {}) => {
    const payload = config.body && JSON.parse(config.body);
    calls.push({url, ...payload});
    if (url.startsWith('/department')) return {ok:true,json:async () => ({ok:true,department:'59'})};
    if (options.failSave && payload?.action === 'save') return {ok:false,json:async () => ({error:'Enregistrement refusé.'})};
    if (payload?.action === 'save') {
      payload.candidates.forEach(row => { const saved = data.candidates.find(c => c.id === row.id); saved.values = row.values; saved.revision += 'x'; });
    }
    const pdf = ['preview','generate'].includes(payload?.action) || url.includes('/preview');
    return {ok:true,headers:new w.Headers({'Content-Type':pdf ? 'application/pdf' : 'application/json'}),
      json:async () => JSON.parse(JSON.stringify(data)),blob:async () => new w.Blob(['%PDF'], {type:'application/pdf'})};
  };
  w.eval(fs.readFileSync('static/js/ssiap-birth-department.js','utf8'));
  w.eval(fs.readFileSync('static/js/ssiap-diplomas.js','utf8'));
  const click = async selector => { doc.querySelector(selector).click(); await tick(); await tick(); };
  const edit = (name, value) => { const field = doc.querySelector('[data-diploma-id=T1]').elements[name]; field.value = value; field.dispatchEvent(new w.Event('input',{bubbles:true})); };
  await click('[data-exam-tab=diplomas]');
  return {w,doc,panel,data,calls,click,edit,form:() => doc.querySelector('[data-diploma-id=T1]')};
}

test('review renders actual birth sentence, result counts and filters', async t => {
  const ui = await setup(t);
  assert.match(ui.form().textContent, /Clément VAILLANT, né le 16\/09\/1993 à SALLANCHES \(74\)/);
  assert.equal(ui.doc.querySelector('[data-diploma-generate-all]').disabled,true);
  const filter = ui.doc.getElementById('ssiapDiplomaFilter');
  filter.value = 'failed'; filter.dispatchEvent(new ui.w.Event('change'));
  assert.equal(ui.form().hidden,true);
  assert.equal(ui.doc.querySelector('[data-diploma-id=T2]').hidden,false);
});

test('uppercase city and foreign country update the preview sentence without losing drafts', async t => {
  const ui = await setup(t);
  ui.edit('birth_city','abidjan'); ui.edit('birth_country',"Côte d'Ivoire");
  assert.equal(ui.form().elements.birth_city.value,'ABIDJAN');
  assert.equal(ui.form().elements.birth_department.value,'');
  assert.match(ui.form().textContent,/ABIDJAN \(Côte d'Ivoire\)/);
  ui.doc.getElementById('ssiapExamDialog').dispatchEvent(new ui.w.Event('ssiap-exam-loaded'));
  await tick();
  assert.equal(ui.form().elements.birth_city.value,'ABIDJAN');
  assert.equal(ui.calls.length,1);
  await ui.click('[data-diploma-save]');
  assert.equal(ui.calls.at(-1).action,'save');
  assert.equal(ui.calls.at(-1).candidates[0].values.birth_city,'ABIDJAN');
  assert.equal(ui.doc.querySelector('[data-diploma-save]').disabled,true);
});

test('preview uses unsaved edits, retains the draft, and does not generate a number', async t => {
  const ui = await setup(t);
  ui.edit('first_name','Marie'); ui.edit('civility','Madame');
  await ui.click('[data-diploma-id=T1] [data-diploma-preview]');
  assert.deepEqual(ui.calls.slice(1).map(call => call.action),['preview']);
  assert.equal(ui.calls[1].candidates[0].values.first_name,'Marie');
  assert.equal(ui.doc.getElementById('ssiapDiplomaPreview').open,true);
  assert.equal(ui.form().dataset.dirty,'true');
  await ui.click('[data-diploma-preview-close]');
  assert.equal(ui.doc.getElementById('ssiapDiplomaPreview').open,false);
  assert.equal(ui.form().elements.first_name.value,'Marie');
});

test('generation saves changed results first and only then asks for the PDF', async t => {
  const ui = await setup(t);
  ui.edit('result','certified');
  await ui.click('[data-diploma-generate-all]');
  assert.deepEqual(ui.calls.slice(1).map(call => call.action || 'load'),['save','generate','load']);
  assert.equal(ui.data.candidates[0].values.result,'certified');
  assert.match(ui.doc.getElementById('ssiapDiplomaStatus').textContent,/générés et téléchargés/);
});

test('failed save preserves edits and prevents generation', async t => {
  const ui = await setup(t,{failSave:true});
  ui.edit('result','certified');
  await ui.click('[data-diploma-generate-all]');
  assert.deepEqual(ui.calls.slice(1).map(call => call.action),['save']);
  assert.equal(ui.form().elements.result.value,'certified');
  assert.equal(ui.form().dataset.dirty,'true');
  assert.match(ui.doc.getElementById('ssiapDiplomaStatus').textContent,/refusé/);
});

test('read-only staff can preview saved data but cannot edit or generate', async t => {
  const ui = await setup(t,{readOnly:true});
  assert.equal(ui.form().querySelector('fieldset').disabled,true);
  assert.equal(ui.doc.querySelector('[data-diploma-save]').disabled,true);
  await ui.click('[data-diploma-id=T1] [data-diploma-preview]');
  assert.equal(ui.calls.at(-1).url,'/api/diplomas/preview?trainee_id=T1');
  assert.equal(ui.calls.at(-1).action,undefined);
});
