const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/aps62-exam.js'),'utf8');

function fixture(draft=null, randomValue=null) {
  const questions=[1,2,3].map(n=>({id:`q${n}`,prompt:`Question ${n}`,options:[{id:'1',text:'Une option'},{id:'2',text:'Une autre option'},{id:'3',text:'<script>non exécuté</script>'},{id:'4',text:'Quatrième choix'}]}));
  const config={exam:{id:'module-01',version:'v2',title:'Test',pass_percent:75,questions},attemptId:'a'.repeat(32),submitUrl:'/submit',csrfToken:'csrf',preview:false};
  const dom=new JSDOM(`<main><div id="examWorkspace"><span id="examAnswered"></span><progress id="examProgress"></progress><nav id="examGrid"></nav><button id="examReview"></button><span id="examPosition"></span><form id="examForm"><fieldset id="examQuestion"></fieldset><button type="button" id="examPrevious"></button><button type="button" id="examNext"></button><p id="examError" hidden></p><button id="examSubmit"></button></form><p id="examDraft"></p></div><section id="examResult" hidden tabindex="-1"></section><script type="application/json" id="apsExamConfig">${JSON.stringify(config).replace(/</g,"\\u003c")}</script></main>`,{url:'https://test.invalid/exam',runScripts:'outside-only'});
  const {window}=dom,requests=[];let fail=true;
  window.fetch=async(url,opts)=>{requests.push({url,...opts});if(fail)throw new Error('Connexion perdue');return{ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true,result:{score:2,total:3,percent:66.7,passed:false,pass_percent:75,corrections:questions.map((q,i)=>({...q,selected:'1',answer:i===0?'2':'1',correct:i!==0,explanation:'Explication du choix.',module:'Module 01',sources:[['Source','https://example.org/'],'Manuel VTC — référence texte',{title:'Source objet',url:'https://example.org/reference'}],lesson_links:[{ref:'A.01',url:'/cours-a'}]}))}})};};
  if(draft)window.sessionStorage.setItem('aps-exam:/exam:v2',JSON.stringify(draft));
  if(randomValue!==null)window.crypto.getRandomValues=(array)=>{array.fill(randomValue);return array;};
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
  assert.equal(draft.answers.q1,'2');assert.equal(d.querySelector('#examQuestion script'),null);assert.match(d.getElementById('examQuestion').textContent,/[A-D]\. Quatrième choix/);assert.doesNotMatch(d.getElementById('examQuestion').textContent,/undefined/);f.close();
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
  assert.equal(f.window.sessionStorage.getItem('aps-exam:/exam:v2'),null);assert.match(d.getElementById('examResult').textContent,/Recommencer/);assert.match(d.getElementById('examResult').textContent,/Manuel VTC — référence texte/);assert.equal(d.querySelector('a[href="/cours-a"]').textContent,'Revoir la leçon A.01');f.close();
});


test('APS choices shuffle by stable ID and preserve their positions when a draft is reopened',()=>{
 const first=fixture(null,0),d=first.window.document;
 const order=[...d.querySelectorAll('input')].map(i=>i.value);
 assert.deepEqual(order,['2','3','4','1']);
 d.querySelector('input[value="3"]').click();
 const draft=JSON.parse(first.window.sessionStorage.getItem('aps-exam:/exam:v2'));
 assert.deepEqual(draft.optionOrders.q1,order);
 first.close();
 const reopened=fixture(draft,2);
 assert.deepEqual([...reopened.window.document.querySelectorAll('input')].map(i=>i.value),order);
 assert.equal(reopened.window.document.querySelector('input:checked').value,'3');
 reopened.close();
});

test('The module timer continues through exam correction and stops when leaving the page', async()=>{
  const f=fixture(),w=f.window,d=w.document;
  f.resolve();
  const tracking={activityId:'aps62-01-examen-blanc',accessToken:'module-access',csrfToken:'csrf',
    startUrl:'/time/start',heartbeatUrl:'/time/heartbeat',finishUrl:'/time/finish',
    initialActiveSeconds:12600,initialRemainingSeconds:1800,heartbeatSeconds:15,idleSeconds:300};
  const panel=d.createElement('section');
  panel.innerHTML='<strong id="nativeActiveTimer"></strong><strong id="nativeRemainingTime"></strong><span id="nativeDurationStatus"></span><div id="nativeTrackingState"><span></span></div>';
  d.body.prepend(panel);
  const cfg=d.createElement('script');cfg.id='nativeElearningConfig';cfg.type='application/json';cfg.textContent=JSON.stringify(tracking);d.body.append(cfg);
  let now=0,seconds=12600,last=0,active=false,visible=true;
  const calls=[],intervals=[];
  w.Date.now=()=>now;
  w.setInterval=(fn,delay)=>{intervals.push({fn,delay});return intervals.length;};
  Object.defineProperty(d,'visibilityState',{get:()=>visible?'visible':'hidden'});
  d.hasFocus=()=>visible;
  const examFetch=w.fetch;
  w.fetch=async(url,options)=>{
    if(!url.startsWith('/time/'))return examFetch(url,options);
    const body=JSON.parse(options.body);calls.push({url,body,keepalive:options.keepalive});
    if(active)seconds+=Math.min(20,(now-last)/1000);
    active=url==='/time/heartbeat'&&body.visible&&body.focused&&body.recent_activity;
    last=now;
    return{ok:true,json:async()=>({ok:true,tracking_session_id:'exam-session',active,
      progress:{active_seconds:seconds,remaining_seconds:14400-seconds,module_complete:false}})};
  };
  const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
  try{
    w.eval(fs.readFileSync(path.join(__dirname,'../static/js/native-elearning-player.js'),'utf8'));
    await settle();
    assert.equal(calls[0].url,'/time/start');
    assert.equal(calls[0].body.activity_id,'aps62-01-examen-blanc');
    assert.equal(d.getElementById('nativeActiveTimer').textContent,'03:30:00');
    for(let i=0;i<3;i++){d.querySelector('input[value="1"]').click();if(i<2)d.getElementById('examNext').click();}
    d.getElementById('examForm').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await settle();
    assert.equal(d.getElementById('examResult').hidden,false);
    const heartbeat=intervals.find(i=>i.delay===15000).fn;
    now=15000;await heartbeat();
    assert.equal(d.getElementById('nativeActiveTimer').textContent,'03:30:15');
    assert.equal(d.getElementById('nativeRemainingTime').textContent,'00:29:45');
    visible=false;d.dispatchEvent(new w.Event('visibilitychange'));await settle();
    now=45000;await heartbeat();
    assert.equal(d.getElementById('nativeActiveTimer').textContent,'03:30:15');
    visible=true;w.dispatchEvent(new w.Event('focus'));await settle();
    now=60000;await heartbeat();
    assert.equal(d.getElementById('nativeActiveTimer').textContent,'03:30:30');
    w.dispatchEvent(new w.Event('pagehide'));await settle();
    assert.equal(calls.at(-1).url,'/time/finish');
    assert.equal(calls.at(-1).keepalive,true);
    const count=calls.length;await heartbeat();assert.equal(calls.length,count);
  }finally{f.close();}
});
