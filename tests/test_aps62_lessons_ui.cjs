const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.join(__dirname, '..');
const fixture = JSON.parse(execFileSync(process.env.APS_TEST_PYTHON || 'python', ['-c', `
import json
from tests.test_aps62_lessons import ReadingHTTPTests
t=ReadingHTTPTests(); t.setUp()
try:
 t._admin_login()
 page=t.client.get('/admin/elearning/courses/academy-aps62-08/preview?activity=aps62-08-03-comprendre')
 assert page.status_code==200
 print(json.dumps({'html':page.text}))
finally:
 t.tearDown()
`], {cwd:root, encoding:'utf8', maxBuffer:4*1024*1024}));

test('new reading steps stay in pagination and never create submissions or writing fields', () => {
  const dom = new JSDOM(fixture.html, {url:'https://test.invalid/preview', runScripts:'outside-only'});
  const {window} = dom, {document} = window;
  let calls=0;
  window.fetch = () => {calls++; throw new Error('reading must not submit');};
  window.HTMLElement.prototype.scrollIntoView = function() {};
  try {
    window.eval(fs.readFileSync(path.join(root,'static/js/aps62-lesson.js'),'utf8'));
    const pages=[...document.querySelectorAll('[data-aps-lesson-page]')];
    const next=document.querySelector('[data-aps-lesson-next]');
    const completion=document.querySelector('[data-aps-lesson-completion]');
    assert.equal(document.querySelectorAll('[data-aps-reading]').length,3);
    assert.equal(document.querySelectorAll('textarea, [contenteditable] , .aps-book input[type="text"]').length,0);
    const seen=[];
    for(let i=0;i<pages.length;i++) {
      assert.equal(pages.filter(p=>!p.hidden).length,1);
      assert.equal(pages[i].hidden,false);
      assert.equal(completion.hidden,i!==pages.length-1);
      if(pages[i].dataset.apsReading) seen.push(pages[i].dataset.apsReading);
      if(i<pages.length-1) next.click();
    }
    assert.deepEqual(seen,['explanation','comparison','example']);
    assert.equal(next.hidden,true);
    assert.equal(calls,0);
  } finally {window.close();}
});
