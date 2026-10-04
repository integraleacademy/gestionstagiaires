const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/aps62-exam.js'),'utf8');

function fixture() {
  const questions=[1,2,3].map(n=>({id:`q${n}`,prompt:`Question ${n}`,options:[{id:'1',text:'Une option'},{id:'2',text:'Une autre option'},{id:'3',text:'<script>non exécuté</script>'}]}));
  const config={exam:{id:'module-01',version:'v2',title:'Test',pass_percent:75,questions},attemptId:'a'.repeat(32),submitUrl:'/submit',csrfToken:'csrf',preview:false};
  const dom=new JSDOM(`<main><div id="examWorkspace"><span id="examAnswered"></span><progress id="examProgress"></progress><nav id="examGrid"></nav><button id="examReview"></button><span id="examPosition"></span><form id="examForm"><fieldset id="examQuestion"></fieldset><button type="button" id="examPrevious"></button><button type="button" id="examNext"></button><p id="examError" hidden></p><button id="examSubmit"></button></form><p id="examDraft"></p></div><section id="examResult" hidden tabindex="-1"></section><script type="application/json" id="apsExamConfig">${JSON.stringify(config).replace(/</g,"\\u003c")}</script></main>`,{url:'https://test.invalid/exam',runScripts:'outside-only'});
  const {window}=dom,requests=[];let fail=true;
  window.fetch=async(url,opts)=>{requests.push({url,...opts});if(fail)throw new Error('Connexion perdue');return{ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true,result:{score:2,total:3,percent:66.7,passed:false,pass_percent:75,corrections:questions.map((q,i)=>({...q,selected:'1',answer:i===0?'2':'1',correct:i!==0,explanation:'Explication du choix.',module:'Module 01',sources:[['Source','https://example.org/']]}))}})};};
  window.eval(source);
  return{dom,window,requests,resolve:()=>fail=false,close:()=>window.close()};
}

test('Unanswered questions prevent submission; navigation and draft retain selected choices',()=>{
  const f=fixture(),d=f.window.document;
  d.getElementById('examForm').dispatchEvent(new f.window.Event('submit',{cancelable:true}));
  assert.equal(f.requests.length,0);assert.equal(d.getElementById('examError').hidden,false);
  d.querySelector('input[value="2"]').click();d.getElementById('examNext').click();d.getElementById('examPrevious').click();
  assert.equal(d.querySelector('input:checked').value,'2');
  const draft=JSON.parse(f.window.sessionStorage.getItem('aps-exam:/exam:v2'));
  assert.equal(draft.answers.q1,'2');assert.equal(d.querySelector('#examQuestion script'),null);f.close();
});

test('Network retry reuses attempt identity, displays server correction and clears the draft',async()=>{
  const f=fixture(),d=f.window.document;
  for(let i=0;i<3;i++){d.querySelector('input[value="1"]').click();if(i<2)d.getElementById('examNext').click();}
  const submit=()=>d.getElementById('examForm').dispatchEvent(new f.window.Event('submit',{cancelable:true}));
  submit();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(d.getElementById('examWorkspace').hidden,false);assert.match(d.getElementById('examError').textContent,/Connexion/);
  f.resolve();submit();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.requests.length,2);assert.equal(JSON.parse(f.requests[0].body).attempt_id,JSON.parse(f.requests[1].body).attempt_id);
  assert.equal(f.requests[1].headers['X-Elearning-CSRF'],'csrf');assert.equal(d.getElementById('examWorkspace').hidden,true);
  assert.match(d.getElementById('examResult').textContent,/66.7 %/);assert.equal(d.querySelectorAll('.exam-correction').length,3);
  assert.equal(f.window.sessionStorage.getItem('aps-exam:/exam:v2'),null);assert.match(d.getElementById('examResult').textContent,/Recommencer/);f.close();
});
