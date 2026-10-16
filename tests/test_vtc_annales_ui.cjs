const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/vtc-annales.js'),'utf8');

function fixture({draft, contextKey='learner-one', savedContext=contextKey}={}) {
  const questions=[
    {id:'q1',number:1,page:2,prompt:'Une réponse <script>non exécuté</script>',status:'active',kind:'single',original_kind:'qcm',options:[{id:'a',text:'Première réponse'},{id:'b',text:'Seconde réponse'}]},
    {id:'q2',number:2,page:3,prompt:'Deux réponses',status:'active',kind:'multiple',original_kind:'qrc',adaptation_note:'Choix pédagogiques pour répondre sans rédaction.',options:[{id:'a',text:'Première condition'},{id:'b',text:'Autre condition'},{id:'c',text:'Condition inexacte'}]},
    {id:'q3',number:3,page:4,prompt:'Une ancienne règle',status:'historical',kind:'single',original_kind:'qcm',context:'Texte historique <img src=x onerror=alert(1)>',options:[{id:'a',text:'Ancienne réponse'},{id:'b',text:'Autre réponse'}]},
  ];
  const config={exam:{id:'annales-2023-a',version:'revision-test',title:'Sujet de test',source_filename:'sujet.pdf',scored_count:2,questions},contextKey,attemptId:'a'.repeat(32),submitUrl:'/submit',csrfToken:'csrf',preview:false};
  const key=`vtc-annales:${contextKey}:${config.exam.id}:${config.exam.version}`;
  const savedKey=`vtc-annales:${savedContext}:${config.exam.id}:${config.exam.version}`;
  const dom=new JSDOM(`<main><div id="annalesWorkspace"><span id="annalesAnswered"></span><progress id="annalesProgress" max="2"></progress><nav id="annalesGrid"></nav><button id="annalesReview"></button><span id="annalesPosition"></span><form id="annalesForm"><div id="annalesContext"></div><fieldset id="annalesQuestion"></fieldset><button type="button" id="annalesPrevious"></button><button type="button" id="annalesNext"></button><p id="annalesError" hidden></p><button id="annalesSubmit"></button></form><p id="annalesDraft"></p></div><section id="annalesResult" hidden tabindex="-1"></section><script type="application/json" id="annalesConfig">${JSON.stringify(config).replace(/</g,'\\u003c')}</script></main>`,{url:'https://test.invalid/annales',runScripts:'outside-only'});
  const {window}=dom,requests=[];
  if(draft!==undefined)window.sessionStorage.setItem(savedKey,typeof draft==='string'?draft:JSON.stringify(draft));
  let fail=false;
  window.fetch=async(url,opts)=>{
    requests.push({url,...opts});
    if(fail)throw new Error('Connexion perdue');
    return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true,result:{score:1,total:2,percent:50,historical_count:1,corrections:questions.map((q,i)=>({...q,answers:i===1?['a','b']:['a'],selected:i===2?[]:i===1?['a','b']:['b'],correct:i===2?null:i===1,explanation:`Correction ${q.number}`,update_note:i===2?'Ancienne règle remplacée.':'',original_answer:i===1?'Les deux conditions.':'',original_answer_origin:'pedagogical',correction_origin:'pedagogical',lesson_links:[{ref:'A.01',url:'/notions/A.01'}],sources:[{title:'Source officielle',url:'https://example.org/source'},{title:'Lien interdit',url:'javascript:alert(1)'}]}))}})};
  };
  window.eval(source);
  return {window,requests,key,config,fail:()=>fail=true,resolve:()=>fail=false,close:()=>window.close()};
}

const submit=f=>f.window.document.getElementById('annalesForm').dispatchEvent(new f.window.Event('submit',{cancelable:true}));
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('Missing answers block submission; multiple choices persist while historical questions stay outside progress',()=>{
  const f=fixture(),d=f.window.document;
  submit(f);assert.equal(f.requests.length,0);assert.equal(d.getElementById('annalesError').hidden,false);
  assert.equal(d.querySelector('#annalesQuestion script'),null);
  d.querySelector('input[value="b"]').click();d.getElementById('annalesNext').click();
  assert.equal(d.querySelectorAll('input[type="checkbox"]').length,3);
  d.querySelector('input[value="a"]').click();d.querySelector('input[value="b"]').click();
  assert.match(d.getElementById('annalesAnswered').textContent,/2 \/ 2/);
  assert.deepEqual(JSON.parse(f.window.sessionStorage.getItem(f.key)).answers.q2,['a','b']);
  d.getElementById('annalesNext').click();
  assert.equal(d.querySelectorAll('#annalesQuestion input').length,0);
  assert.match(d.getElementById('annalesQuestion').textContent,/ne compte pas dans votre score/);
  assert.equal(d.querySelector('#annalesContext img'),null);
  assert.match(d.getElementById('annalesContext').textContent,/<img/);
  d.getElementById('annalesPrevious').click();
  assert.deepEqual(Array.from(d.querySelectorAll('input:checked'),n=>n.value),['a','b']);
  d.querySelector('input[value="a"]').click();d.querySelector('input[value="b"]').click();
  submit(f);assert.equal(f.requests.length,0);assert.match(d.getElementById('annalesPosition').textContent,/Question 2/);
  f.close();
});

test('Retry keeps its attempt identity, excludes historical answers, presents corrections and clears draft',async()=>{
  const f=fixture(),d=f.window.document;
  d.querySelector('input[value="b"]').click();d.getElementById('annalesNext').click();
  d.querySelector('input[value="a"]').click();d.querySelector('input[value="b"]').click();
  f.fail();submit(f);await flush();
  assert.match(d.getElementById('annalesError').textContent,/Connexion perdue/);
  assert.notEqual(f.window.sessionStorage.getItem(f.key),null);
  assert.equal(d.getElementById('annalesWorkspace').hidden,false);
  f.resolve();submit(f);await flush();
  assert.equal(f.requests.length,2);
  const first=JSON.parse(f.requests[0].body),second=JSON.parse(f.requests[1].body);
  assert.equal(first.attempt_id,second.attempt_id);assert.equal(second.version,'revision-test');
  assert.deepEqual(Object.keys(second.answers).sort(),['q1','q2']);
  assert.equal(f.requests[1].headers['X-Elearning-CSRF'],'csrf');
  assert.equal(d.getElementById('annalesWorkspace').hidden,true);
  assert.match(d.getElementById('annalesResult').textContent,/1 \/ 2 questions justes · 50 %/);
  assert.equal(d.querySelectorAll('.exam-correction').length,3);
  assert.match(d.getElementById('annalesResult').textContent,/Hors score/);
  assert.match(d.getElementById('annalesResult').textContent,/Les cours à revoir en priorité/);
  assert.match(d.getElementById('annalesResult').textContent,/Correction pédagogique proposée/);
  assert.equal(d.querySelectorAll('a[href^="javascript:"]').length,0);
  assert.equal(d.querySelectorAll('a[href="https://example.org/source"][rel="noopener noreferrer"]').length,3);
  assert.equal(f.window.sessionStorage.getItem(f.key),null);
  submit(f);await flush();assert.equal(f.requests.length,2);
  f.close();
});

test('Reload resumes valid draft choices, position and attempt id; a different learner ignores them',async()=>{
  const draft={answers:{q1:['b'],q2:['a','b'],q3:['a']},position:1,attemptId:'b'.repeat(32)};
  const f=fixture({draft}),d=f.window.document;
  assert.match(d.getElementById('annalesPosition').textContent,/Question 2/);
  assert.deepEqual(Array.from(d.querySelectorAll('input:checked'),n=>n.value),['a','b']);
  submit(f);await flush();
  const request=JSON.parse(f.requests[0].body);
  assert.equal(request.attempt_id,draft.attemptId);assert.equal(request.answers.q3,undefined);
  f.close();
  const other=fixture({draft,contextKey:'learner-two',savedContext:'learner-one'});
  assert.equal(other.window.document.querySelectorAll('input:checked').length,0);
  assert.match(other.window.document.getElementById('annalesAnswered').textContent,/0 \/ 2/);
  other.close();
});

test('Malformed draft values never inject invalid choices or prevent opening the paper',()=>{
  for(const draft of ['{broken',{answers:{q1:['a','b'],q2:['unknown']},position:99,attemptId:'invalid'},{answers:{q1:['a'],q2:['a','a']},position:-1}]){
    const f=fixture({draft}),d=f.window.document;
    assert.match(d.getElementById('annalesPosition').textContent,/Question 1/);
    d.getElementById('annalesNext').click();assert.equal(d.querySelectorAll('input:checked').length,0);
    submit(f);assert.equal(f.requests.length,0);f.close();
  }
});
