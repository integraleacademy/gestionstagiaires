const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

const root = path.join(__dirname, '..');
const fixture = JSON.parse(execFileSync(process.env.APS_TEST_PYTHON || 'python', ['-c', `
import json
from tests.test_aps62_depth import DepthHTTPTests
from elearning_native.academy import load_bundled_course
t = DepthHTTPTests(); t.setUp()
try:
 t._admin_login()
 c = load_bundled_course('academy-aps62-01')
 a = next(a for a in c['sections'][0]['activities'] if a.get('practice',{}).get('dossier'))
 page = t.client.get('/admin/elearning/courses/academy-aps62-01/preview?activity='+a['id'])
 assert page.status_code == 200
 print(json.dumps({'html':page.text,'practice':a['practice']}))
finally:
 t.tearDown()
`], {cwd:root, encoding:'utf8', maxBuffer:4*1024*1024}));

test('rendered dossier supports classification, association, chronology and decisions in sequence', async () => {
  const dom = new JSDOM(fixture.html, {url:'https://test.invalid/preview', runScripts:'outside-only'});
  const {window} = dom, {document} = window, calls=[];
  const exercises = fixture.practice.exercises;
  const expected = ex => ex.kind === 'single' ? ex.answer : Object.fromEntries(ex.rows.map(row=>[row.id,row.answer]));
  const same = (a,b) => typeof a === 'string' ? a === b : Object.keys(b).every(key=>a?.[key]===b[key]) && Object.keys(a||{}).length===Object.keys(b).length;
  const settle = async () => {for(let i=0;i<25;i++) await Promise.resolve();};
  window.fetch = async (_url, options) => {
    const body = JSON.parse(options.body); calls.push(body);
    const selected = body.practice_step ? exercises.filter(ex=>ex.id===body.practice_step) : exercises;
    const feedback = selected.map(ex=>({id:ex.id, correct:same(body.practice_answers[ex.id],expected(ex)), explanation:ex.explanation,
      correction:ex.kind==='single' ? [ex.options.find(o=>o.id===ex.answer).text] : ex.rows.map(row=>row.text+' → '+ex.options.find(o=>o.id===row.answer).text)}));
    return {ok:true,json:async()=>({ok:true,correct:feedback.every(x=>x.correct),feedback,review:[]})};
  };
  try {
    window.eval(fs.readFileSync(path.join(root,'static/js/aps62-guided.js'),'utf8'));
    assert.equal(document.querySelectorAll('#apsDossierDocuments article').length,3);
    assert.equal(document.querySelectorAll('[data-exercise-id]:not([hidden])').length,1);
    document.querySelector('.aps-practice-check').click(); await settle();
    assert.equal(calls.length,0,'incomplete classification must not submit');
    assert.throws(()=>window.aps62Practice.collectForCompletion(),/Terminez/);
    for (const [index,ex] of exercises.entries()) {
      const field=document.querySelector(`[data-exercise-id="${ex.id}"]`);
      assert.equal(field.hidden,false);
      if(ex.kind==='single') {
        field.querySelector(`input[value="${ex.answer}"]`).checked=true;
      } else {
        for(const row of ex.rows) field.querySelector(`[data-row-id="${row.id}"]`).value=row.answer;
      }
      field.dispatchEvent(new window.Event('change',{bubbles:true}));
      document.querySelector('.aps-practice-check').click(); await settle();
      assert.equal(document.querySelector('.aps-guided-next').hidden,false);
      assert.match(field.querySelector('[data-exercise-feedback]').textContent,/bonne réponse/);
      if(index < exercises.length-1) assert.throws(()=>window.aps62Practice.collectForCompletion(),/Terminez/);
      document.querySelector('.aps-guided-next').click(); await settle();
    }
    assert.equal(calls.length,exercises.length+1,'full authoritative verification still required');
    assert.equal(Object.keys(window.aps62Practice.collectForCompletion()).length,8);
    document.querySelector('.aps-practice-restart').click();
    assert.equal(document.querySelectorAll('select option:checked:not([value=""])').length,0);
    assert.throws(()=>window.aps62Practice.collectForCompletion(),/Terminez/);
  } finally {window.close();}
});
