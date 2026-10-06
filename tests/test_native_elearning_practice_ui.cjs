const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/aps62-practice.js'), 'utf8');

function fixture(preview = false, stored = null) {
  const kinds = ['single', 'sort', 'matching', 'order'];
  const config = {activityId:'atelier', courseVersion:'v2', completed:false, savedAnswers:{},
    practice:{revision:'click-only', exercises:kinds.map((kind,i)=>({id:'ex'+i,kind}))}};
  const fields = kinds.map((kind,i) => `<fieldset data-exercise-id="ex${i}" data-kind="${kind}">
    ${kind === 'single' ? '<input type="radio" name="decision" value="a"><input type="radio" name="decision" value="b">'
      : [0,1].map(n=>`<select data-row-id="r${n}"><option value=""></option><option value="a">A</option><option value="b">B</option></select>`).join('')}
    <div data-exercise-feedback hidden></div></fieldset>`).join('');
  const access = {answerUrl:'/preview', practiceUrl:'/practice', accessToken:'learner-token', csrfToken:'csrf'};
  const dom = new JSDOM(`<section data-aps-practice><form>${fields}<button class="aps-practice-check" type="submit">Vérifier</button>
    <button class="aps-practice-restart" type="button">Recommencer</button></form><p data-practice-result></p><p data-practice-draft></p>
    <script id="apsPracticeConfig" type="application/json">${JSON.stringify(config)}</script></section>
    <script id="${preview?'nativePreviewConfig':'nativeElearningConfig'}" type="application/json">${JSON.stringify(access)}</script>`,
    {url:'https://example.test/espace/alice/elearning/module',runScripts:'outside-only'});
  const {window}=dom, {document}=window;
  const key='aps62-practice:/espace/alice/elearning/module:v2:atelier:click-only';
  if(stored) window.sessionStorage.setItem(key,JSON.stringify(stored));
  const calls=[]; let correct=false, failure=false;
  window.fetch=async(url, options)=>{
    calls.push({url,options,body:JSON.parse(options.body)});
    if(failure) throw new Error('Connexion interrompue');
    return {ok:true,json:async()=>({ok:true,correct,passed:correct?4:3,total:4,
      feedback:kinds.map((kind,i)=>({id:'ex'+i,correct:correct||i>0,explanation:'Explication sûre <script>test</script>',correction:['Réponse attendue']}))})};
  };
  window.eval(source);
  const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
  const answers={ex0:'a',ex1:{r0:'a',r1:'b'},ex2:{r0:'a',r1:'b'},ex3:{r0:'a',r1:'b'}};
  function fill(){
    document.querySelector('input[value=a]').checked=true;
    document.querySelectorAll('fieldset').forEach(fieldset=>fieldset.querySelectorAll('select').forEach((el,i)=>{el.value=i?'b':'a';}));
    document.querySelector('input').dispatchEvent(new window.Event('change',{bubbles:true}));
  }
  return {window,document,calls,key,answers,fill,settle,correct:()=>{correct=true;},fail:()=>{failure=true;},
    submit:()=>document.querySelector('.aps-practice-check').click(),close:()=>window.close()};
}

test('preview supports all four interaction kinds, correction, retries and reset without student writes',async()=>{
  const f=fixture(true);
  try{
    f.submit();await f.settle();assert.equal(f.calls.length,0);
    f.fill();f.submit();await f.settle();
    assert.deepEqual(f.calls[0].body,{practice_answers:f.answers,review_answers:{}});
    assert.equal(f.calls[0].url,'/preview');
    assert.equal(f.calls[0].options.headers['X-Elearning-CSRF'],'csrf');
    assert.match(f.document.querySelector('[data-practice-result]').textContent,/3 exercices/);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion(),/Vérifiez/);
    assert.equal(f.document.querySelector('[data-exercise-feedback] script'),null,'feedback is text, never HTML');
    assert.equal(f.window.sessionStorage.length,0,'preview does not persist a learner draft');
    f.correct();f.submit();await f.settle();
    assert.equal(JSON.stringify(f.window.aps62Practice.collectForCompletion()),JSON.stringify(f.answers));
    f.document.querySelector('input[value=b]').checked=true;
    f.document.querySelector('input[value=b]').dispatchEvent(new f.window.Event('change',{bubbles:true}));
    assert.throws(()=>f.window.aps62Practice.collectForCompletion(),/Vérifiez/,'changed answers require another correction');
    f.document.querySelector('.aps-practice-restart').click();
    assert.equal(f.document.querySelectorAll('input:checked').length,0);
    assert.ok([...f.document.querySelectorAll('select')].every(el=>el.value===''));
  }finally{f.close();}
});

test('learner resumes choices, keeps them after network failure and clears draft only after successful completion',async()=>{
  const choices={ex0:'a',ex1:{r0:'a',r1:'b'},ex2:{r0:'a',r1:'b'},ex3:{r0:'a',r1:'b'}};
  const f=fixture(false,choices);
  try{
    assert.equal(f.document.querySelector('input:checked').value,'a');
    f.correct();f.submit();await f.settle();
    assert.equal(f.calls[0].url,'/practice');assert.equal(f.calls[0].body.access_token,'learner-token');
    assert.deepEqual(f.calls[0].body.practice_answers,choices);
    assert.ok(f.window.sessionStorage.getItem(f.key),'correction alone is not completion');
    f.fail();f.submit();await f.settle();
    assert.match(f.document.querySelector('[data-practice-result]').textContent,/Connexion interrompue/);
    assert.equal(f.document.querySelectorAll('input:disabled,select:disabled,button:disabled').length,0);
    assert.equal(f.document.querySelector('input:checked').value,'a');
    assert.ok(f.window.sessionStorage.getItem(f.key));
    f.window.aps62Practice.clearDraft();assert.equal(f.window.sessionStorage.getItem(f.key),null);
  }finally{f.close();}
});

test('v3 reveals decisions successively, displays targeted review and composes a journal without text entry',async()=>{
  const course=JSON.parse(fs.readFileSync(path.join(__dirname,'../elearning_native/aps62/courses/academy-aps62-01/20261006-aps62-v3.json'),'utf8'));
  for(const index of [2,7]){
    const activity=course.sections[0].activities[index];
    const practice=JSON.parse(JSON.stringify(activity.practice));
    const config={activityId:activity.id,courseVersion:course.version,completed:false,savedAnswers:{},practice};
    const fields=practice.exercises.map(ex=>`<fieldset data-exercise-id="${ex.id}" data-kind="single"><legend>${ex.prompt}</legend>${ex.options.map(o=>`<label><input type="radio" name="${ex.id}" value="${o.id}"><span>${o.text}</span></label>`).join('')}<p data-stage-consequence hidden></p><div data-exercise-feedback hidden></div></fieldset>`).join('');
    const dom=new JSDOM(`<section data-aps-practice><p data-stage-status></p><form>${fields}<button type="submit" class="aps-practice-check">Vérifier</button><button type="button" class="aps-practice-restart">Reset</button></form><dl data-journal-preview></dl><section data-remediation hidden><div data-remediation-items></div><button type="button" class="aps-practice-review">Réviser</button><p data-review-status></p></section><p data-practice-result></p><p data-practice-draft></p><script id="apsPracticeConfig" type="application/json">${JSON.stringify(config)}</script></section><script id="nativePreviewConfig" type="application/json">{"answerUrl":"/preview","csrfToken":"csrf"}</script>`,{url:'https://test.invalid/preview',runScripts:'outside-only'});
    const {window}=dom,{document}=window,calls=[];
    const ex=practice.exercises[0],drill=ex.remediation;
    window.fetch=async(url,options)=>{
      const body=JSON.parse(options.body);calls.push(body);
      return {ok:true,json:async()=>({ok:true,correct:false,passed:practice.exercises.length-1,total:practice.exercises.length,
        feedback:practice.exercises.map((e,i)=>({id:e.id,correct:i>0,explanation:e.explanation,correction:[]})),
        review:[{id:ex.id,lesson:drill.lesson,prompt:drill.prompt,options:drill.options,...(body.review_answers[ex.id]?{correct:true,explanation:drill.explanation}:{})}]})};
    };
    const settle=async()=>{for(let n=0;n<15;n++)await Promise.resolve();};
    try{
      window.eval(source);
      const stages=[...document.querySelectorAll('[data-exercise-id]')];
      if(practice.sequential){assert.equal(stages[0].hidden,false);assert.ok(stages.slice(1).every(s=>s.hidden));}
      for(const [i,stage] of stages.entries()){
        assert.equal(stage.hidden,false);
        const input=stage.querySelector('input');input.checked=true;input.dispatchEvent(new window.Event('change',{bubbles:true}));
        if(practice.sequential)assert.ok(stage.querySelector('[data-stage-consequence]').textContent);
      }
      assert.equal(document.querySelectorAll('textarea,input[type=text]').length,0);
      assert.equal(document.querySelectorAll('[data-journal-preview] dd').length,practice.exercises.length);
      document.querySelector('.aps-practice-check').click();await settle();
      assert.equal(document.querySelector('[data-remediation]').hidden,false);
      assert.ok(document.querySelector('[data-remediation]').textContent.includes(drill.prompt));
      assert.throws(()=>window.aps62Practice.collectForCompletion(),/Vérifiez/);
      document.querySelector('.aps-practice-review').click();await settle();assert.equal(calls.length,1);
      document.querySelector('[data-review-id] input').checked=true;
      document.querySelector('.aps-practice-review').click();await settle();
      assert.ok(calls[1].review_answers[ex.id]);
      assert.match(document.querySelector('[data-remediation]').textContent,/Compris/);
      document.querySelector('.aps-practice-restart').click();
      assert.equal(document.querySelector('[data-remediation]').hidden,true);
      if(practice.sequential)assert.ok(stages.slice(1).every(s=>s.hidden));
    }finally{window.close();}
  }
});
