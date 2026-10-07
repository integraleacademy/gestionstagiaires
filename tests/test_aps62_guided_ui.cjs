const {test} = require('node:test');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../static/js/aps62-guided.js'),'utf8');
const course = JSON.parse(fs.readFileSync(path.join(__dirname,'../elearning_native/aps62/courses/academy-aps62-01/20261007-aps62-v6.json'),'utf8'));

function fixture() {
  const activity = course.sections[0].activities[2], practice = activity.practice;
  const publicPractice = {...practice, exercises:practice.exercises.map(({answer, explanation, remediation, ...rest})=>rest)};
  const fields = practice.exercises.map(ex=>`<fieldset data-exercise-id="${ex.id}" data-kind="single"><legend tabindex="-1">${ex.prompt}</legend>${ex.options.map(o=>`<label><input type="radio" name="${ex.id}" value="${o.id}"><span>${o.text}</span></label>`).join('')}<div data-exercise-feedback hidden></div></fieldset>`).join('');
  const dom = new JSDOM(`<section data-aps-practice><p data-stage-status></p><form>${fields}<button type="submit" class="aps-practice-check">Vérifier</button><button type="button" class="aps-guided-next" hidden>Suite</button><button type="button" class="aps-practice-restart">Recommencer</button></form><section data-remediation hidden><h3>Réviser</h3><p>Révision</p><div data-remediation-items></div><button type="button" class="aps-practice-review">Réviser</button></section><p data-practice-result></p><p data-practice-draft></p><script id="apsPracticeConfig" type="application/json">${JSON.stringify({activityId:activity.id,courseVersion:course.version,practice:publicPractice,completed:false,savedAnswers:{}})}</script></section><script id="nativePreviewConfig" type="application/json">{"answerUrl":"/preview","csrfToken":"csrf"}</script>`,{url:'https://test.invalid/preview',runScripts:'outside-only'});
  const {window}=dom, {document}=window, calls=[];
  window.fetch=async(url,opts)=>{
    const body=JSON.parse(opts.body);calls.push(body);
    const selected=body.practice_step?practice.exercises.filter(e=>e.id===body.practice_step):practice.exercises;
    assert.deepEqual(Object.keys(body.practice_answers).sort(),selected.map(e=>e.id).sort());
    const feedback=selected.map(ex=>({id:ex.id,correct:body.practice_answers[ex.id]===ex.answer,explanation:ex.explanation,correction:[ex.options.find(o=>o.id===ex.answer).text]}));
    const review=selected.filter((ex,i)=>!feedback[i].correct).map(ex=>({id:ex.id,...ex.remediation}));
    return {ok:true,json:async()=>({ok:true,correct:feedback.every(f=>f.correct),feedback,review})};
  };
  window.eval(source);
  const choose=(i,correct=true)=>{
    const ex=practice.exercises[i], value=correct?ex.answer:ex.options.find(o=>o.id!==ex.answer).id;
    const input=document.querySelector(`[data-exercise-id="${ex.id}"] input[value="${value}"]`);
    input.checked=true;input.dispatchEvent(new window.Event('change',{bubbles:true}));
  };
  return {window,document,practice,calls,choose,close:()=>window.close(),
    settle:async()=>{for(let i=0;i<20;i++)await Promise.resolve();}};
}

test('one question at a time; wrong choices cannot advance; complete grading remains mandatory',async()=>{
  const f=fixture(), fields=[...f.document.querySelectorAll('[data-exercise-id]')];
  try {
    assert.equal(fields.filter(e=>!e.hidden).length,1);
    f.choose(0,false);f.document.querySelector('.aps-practice-check').click();await f.settle();
    assert.equal(f.document.querySelector('.aps-guided-next').hidden,true);
    assert.match(fields[0].textContent,/Reprenons ensemble/);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion(),/Terminez/);
    for(let i=0;i<3;i++) {
      assert.equal(fields.filter(e=>!e.hidden).length,1);assert.equal(fields[i].hidden,false);
      f.choose(i);f.document.querySelector('.aps-practice-check').click();await f.settle();
      assert.equal(f.document.querySelector('.aps-guided-next').hidden,false);
      assert.equal(f.document.querySelector('.aps-practice-check').hidden,true);
      if(i<2)assert.throws(()=>f.window.aps62Practice.collectForCompletion(),/Terminez/);
      f.document.querySelector('.aps-guided-next').click();await f.settle();
    }
    assert.equal(f.calls.length,5);assert.equal(f.calls.at(-1).practice_step,undefined);
    assert.equal(Object.keys(f.window.aps62Practice.collectForCompletion()).length,3);
    assert.match(f.document.querySelector('[data-practice-result]').textContent,/Exercice réussi/);
    assert.equal(f.document.querySelector('[data-remediation]').hidden,false);
    f.document.querySelector('.aps-practice-restart').click();
    assert.equal(fields[0].hidden,false);assert.equal(fields.filter(e=>!e.hidden).length,1);
    assert.throws(()=>f.window.aps62Practice.collectForCompletion(),/Terminez/);
  } finally {f.close();}
});

test('a failed request preserves the answer and permits a retry',async()=>{
  const f=fixture();
  try {
    f.window.fetch=async()=>{throw new Error('Connexion interrompue');};
    f.choose(0);f.document.querySelector('.aps-practice-check').click();await f.settle();
    assert.equal(f.document.querySelector('input:checked').value,f.practice.exercises[0].answer);
    assert.equal(f.document.querySelectorAll('input:disabled,button:disabled').length,0);
    assert.match(f.document.querySelector('[data-practice-result]').textContent,/Connexion interrompue/);
    assert.equal(f.document.querySelector('.aps-guided-next').hidden,true);
  } finally {f.close();}
});
