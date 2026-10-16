const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..');
const fixtures = JSON.parse(execFileSync(process.env.APS_TEST_PYTHON || 'python',
  ['-m', 'tests.shared_reader_fixtures'], {cwd:root, encoding:'utf8', maxBuffer:16*1024*1024}));
const script = fs.readFileSync(path.join(root, 'static/js/aps62-lesson.js'), 'utf8');
const shell = html => `<div data-aps-lesson data-lesson-key="test"><div data-aps-lesson-progress hidden><strong data-aps-lesson-status></strong><div><i data-aps-lesson-bar></i></div></div>${html}<nav data-aps-lesson-navigation hidden><button data-aps-lesson-previous></button><span data-aps-lesson-count></span><button data-aps-lesson-next>Suivant</button><div data-aps-lesson-completion hidden></div></nav></div><div class="native-navigation-actions"><button id="nativeActionButton">Terminer</button></div>`;

test('all 322 MAC APS, A3P and VTC lessons match the server plan after real DOM pagination', () => {
  assert.equal(fixtures.length, 322);
  for (const row of fixtures) {
    const dom = new JSDOM(shell(row.html), {url:'https://test.invalid/reader', runScripts:'outside-only'});
    dom.window.HTMLElement.prototype.scrollIntoView = function() {};
    try {
      dom.window.eval(script);
      const pages = [...dom.window.document.querySelectorAll('[data-aps-lesson-page]')];
      assert.equal(pages.length, row.plan.length, row.id);
      assert.equal(pages.filter(p=>!p.hidden).length, 1, row.id);
      assert.equal(dom.window.document.querySelectorAll('textarea, [contenteditable]').length, 0, row.id);
    } finally {dom.window.close();}
  }
});

for (const family of ['macaps', 'a3p', 'vtc']) {
  test(`${family}: countdown, no anchor skipping, confirmed unlock and rereading`, () => {
    const row = fixtures.find(r=>r.family === family);
    const dom = new JSDOM(shell(row.html), {url:'https://test.invalid/reader', runScripts:'outside-only'});
    const {window} = dom, {document} = window;
    window.HTMLElement.prototype.scrollIntoView = function() {};
    let unlocked = 0, selected = -1;
    window.nativeLessonTiming = {pages:row.plan, firstPending:()=>unlocked,
      ready:i=>i<unlocked, remaining:i=>i<unlocked?0:row.plan[i].required_seconds,
      select:i=>selected=i};
    try {
      window.eval(script);
      const next = document.querySelector('[data-aps-lesson-next]');
      const previous = document.querySelector('[data-aps-lesson-previous]');
      assert.equal(next.disabled, true);
      next.click(); assert.equal(selected,0);
      const anchor = document.querySelector('a[href^="#"]');
      if(anchor){anchor.click(); assert.equal(selected,0);}
      unlocked = 1;
      document.dispatchEvent(new window.CustomEvent('native-lesson-timing'));
      assert.equal(next.disabled, false);
      next.click(); assert.equal(selected,1); assert.equal(next.disabled,true);
      previous.click(); assert.equal(selected,0); assert.equal(next.disabled,false);
      assert.match(document.querySelector('[data-aps-lesson-timing]').textContent,/validé|complémentaire/);
    } finally {window.close();}
  });
}

test('the shared player waits for server receipts for both viewing and reading', async () => {
  const pages = [{id:'video', required_seconds:0, video_id:'clip', media:true},
    {id:'text', required_seconds:60}];
  const config = {activityId:'lesson', lessonPages:pages, initialLessonSeconds:{}, initialVideoProgress:{},
    startUrl:'/start', heartbeatUrl:'/heartbeat', finishUrl:'/finish', idleSeconds:300,
    accessToken:'test', csrfToken:'test', initialRemainingSeconds:600};
  const dom = new JSDOM(`<button id="nativeActionButton" data-mode="complete"></button><script id="nativeElearningConfig" type="application/json">${JSON.stringify(config)}</script>`,
    {url:'https://test.invalid/reader', runScripts:'outside-only'});
  const {window} = dom;
  window.document.hasFocus=()=>true;
  Object.defineProperty(window.document,'visibilityState',{value:'visible'});
  window.fetch=async()=>({ok:true,json:async()=>({ok:true,tracking_session_id:'test',progress:{}})});
  try {
    window.eval(fs.readFileSync(path.join(root,'static/js/native-elearning-player.js'),'utf8'));
    for(let i=0;i<15;i++) await Promise.resolve();
    const timing=window.nativeLessonTiming;
    assert.equal(timing.firstPending(),0);
    timing.apply({video_progress:{lesson:{clip:{completed:true}}}});
    assert.equal(timing.firstPending(),1);
    timing.pageId='text'; timing.active=true; timing.receivedAt=0;
    timing.seconds={text:59};
    Object.defineProperty(window.performance,'now',{value:()=>2000});
    assert.equal(timing.remaining(1),0);
    assert.equal(timing.ready(1),false);
    timing.apply({lesson_seconds:{lesson:{text:60}}});
    assert.equal(timing.allReady(),true);
  } finally {window.close();}
});
