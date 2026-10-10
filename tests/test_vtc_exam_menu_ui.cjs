const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const examSource=fs.readFileSync(path.join(__dirname,'../static/js/aps62-exam.js'),'utf8');
const menuSource=fs.readFileSync(path.join(__dirname,'../static/js/native-elearning-menu.js'),'utf8');

function examFixture({vtc=true,draft,attempt='a'.repeat(32),random=0,storage=true}={}){
  const questions=[1,2,3].map(n=>({id:`q${n}`,prompt:`Question ${n}`,options:[{id:'x',text:'Premier choix'},{id:'y',text:'Deuxième choix'},{id:'z',text:'Troisième choix'},{id:'w',text:'Quatrième choix'}]}));
  const config={exam:{id:vtc?'vtc-d':'module-01',training_label:vtc?'VTC':'APS',version:'v1',questions},attemptId:attempt,csrfToken:'csrf',submitUrl:'/submit'};
  const dom=new JSDOM(`<main><div id="examWorkspace"><p id="examAnswered"></p><progress id="examProgress"></progress><nav id="examGrid"></nav><button id="examReview"></button><p id="examPosition"></p><form id="examForm"><fieldset id="examQuestion"></fieldset><button type="button" id="examPrevious"></button><button type="button" id="examNext"></button><p id="examError" hidden></p><button id="examSubmit"></button></form><p id="examDraft"></p></div><section id="examResult" tabindex="-1" hidden></section><script id="apsExamConfig" type="application/json">${JSON.stringify(config)}</script></main>`,{url:'https://test.invalid/exam',runScripts:'outside-only'});
  const {window}=dom,d=window.document,key='aps-exam:/exam:v1',requests=[];
  if(draft!==undefined)window.sessionStorage.setItem(key,JSON.stringify(draft));
  let randomCalls=0,fail=false;
  window.crypto.getRandomValues=values=>{randomCalls++;values.fill(random);return values;};
  if(!storage)Object.defineProperty(window,'sessionStorage',{get(){throw new Error('Blocked storage');}});
  window.fetch=async(url,options)=>{
    requests.push(JSON.parse(options.body));if(fail)throw new Error('Connexion interrompue');
    return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true,result:{score:3,total:3,percent:100,passed:true,pass_percent:80,corrections:questions.map(q=>({...q,selected:'x',answer:'x',correct:true,explanation:'Explication',module:'D',sources:[]}))}})};
  };
  window.eval(examSource);
  return {window,d,key,requests,randomCalls:()=>randomCalls,fail:value=>fail=value,
    order:()=>Array.from(d.querySelectorAll('#examQuestion input'),n=>n.value),
    draft:()=>JSON.parse(window.sessionStorage.getItem(key)),close:()=>window.close()};
}
const submit=f=>f.d.getElementById('examForm').dispatchEvent(new f.window.Event('submit',{cancelable:true}));
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('VTC option permutations are saved before answering and remain stable after reload and navigation',()=>{
  const first=examFixture();let saved,order;
  try{
    order=first.order();assert.notDeepEqual(order,['x','y','z','w']);
    assert.deepEqual([...order].sort(),['w','x','y','z']);
    assert.equal(first.randomCalls(),9);
    first.d.querySelector('input[value=x]').click();
    first.d.getElementById('examNext').click();first.d.getElementById('examPrevious').click();
    assert.deepEqual(first.order(),order);assert.equal(first.d.querySelector('input:checked').value,'x');
    saved=first.draft();assert.deepEqual(saved.optionOrders.q1,order);
  }finally{first.close();}
  const resumed=examFixture({draft:saved,attempt:'b'.repeat(32),random:1});
  try{assert.deepEqual(resumed.order(),order);assert.equal(resumed.randomCalls(),0);assert.equal(resumed.draft().attemptId,'a'.repeat(32));assert.equal(resumed.d.querySelector('input:checked').value,'x');}finally{resumed.close();}
  const fresh=examFixture({attempt:'b'.repeat(32),random:1});
  try{assert.notDeepEqual(fresh.order(),order);assert.equal(fresh.draft().attemptId,'b'.repeat(32));}finally{fresh.close();}
});

test('Original answer IDs survive shuffling and network retry; correction follows the displayed order',async()=>{
  const f=examFixture();try{
    const order=f.order();
    for(let i=0;i<3;i++){f.d.querySelector('input[value=x]').click();if(i<2)f.d.getElementById('examNext').click();}
    f.fail(true);submit(f);await settle();const before=f.draft();
    f.fail(false);submit(f);await settle();
    assert.deepEqual(f.requests[0],f.requests[1]);assert.deepEqual(f.requests[1].answers,{q1:'x',q2:'x',q3:'x'});
    assert.equal(f.requests[1].attempt_id,before.attemptId);assert.equal(f.window.sessionStorage.getItem(f.key),null);
    const texts={x:'Premier choix',y:'Deuxième choix',z:'Troisième choix',w:'Quatrième choix'};
    assert.deepEqual(Array.from(f.d.querySelectorAll('.exam-correction:first-of-type li'),n=>n.textContent.split(' — ')[0]),order.map(id=>texts[id]));
  }finally{f.close();}
});

test('APS order and legacy drafts are preserved; malformed orders never remove options',()=>{
  for(const opts of [{vtc:false},{draft:{attemptId:'b'.repeat(32),answers:{q1:'y'},position:0}},
    {draft:{attemptId:'b'.repeat(32),answers:{q1:'y'},position:1.5,optionOrders:{q1:['x','x','unknown','w']}}}]){
    const f=examFixture(opts);try{assert.deepEqual(f.order(),['x','y','z','w']);assert.equal(f.randomCalls(),0);if(opts.draft)assert.equal(f.d.querySelector('input:checked').value,'y');}finally{f.close();}
  }
  const f=examFixture({storage:false});try{assert.equal(f.order().length,4);assert.match(f.d.getElementById('examDraft').textContent,/ne conserve pas/);}finally{f.close();}
});

function menuFixture(initialMobile=true){
  const dom=new JSDOM(`<header class="native-topbar"><button id="nativeMenuButton" aria-expanded="false">Sommaire</button></header><aside id="nativeSidebar" tabindex="-1" aria-label="Sommaire"><button id="nativeMenuClose">Fermer</button><a href="#one" aria-current="page">Leçon 1</a><a href="#two">Leçon 2</a></aside><button id="nativeSidebarOverlay" tabindex="-1" aria-hidden="true"></button><main class="native-main" aria-hidden="false"><button id="contentAction">Continuer</button></main>`,{url:'https://test.invalid/course',runScripts:'outside-only'});
  const {window}=dom,d=window.document;let listener;
  const media={matches:initialMobile,addEventListener:(_,fn)=>listener=fn};window.matchMedia=()=>media;
  d.body.style.overflow='auto';window.eval(menuSource);
  return {window,d,sidebar:d.getElementById('nativeSidebar'),button:d.getElementById('nativeMenuButton'),closeButton:d.getElementById('nativeMenuClose'),
    key:(key,shiftKey=false)=>window.dispatchEvent(new window.KeyboardEvent('keydown',{key,shiftKey,bubbles:true,cancelable:true})),
    resize:mobile=>{media.matches=mobile;listener();},close:()=>window.close()};
}

test('Mobile menu hides closed links, contains keyboard focus and restores the opener on Escape or close',()=>{
  const f=menuFixture();try{
    assert.equal(f.sidebar.hasAttribute('inert'),true);assert.equal(f.sidebar.getAttribute('aria-hidden'),'true');
    f.button.focus();f.button.click();
    assert.equal(f.d.activeElement,f.closeButton);assert.equal(f.sidebar.getAttribute('role'),'dialog');assert.equal(f.sidebar.getAttribute('aria-modal'),'true');
    assert.equal(f.d.querySelector('main').hasAttribute('inert'),true);assert.equal(f.d.body.style.overflow,'hidden');
    const last=f.sidebar.querySelector('a:last-child');last.focus();f.key('Tab');assert.equal(f.d.activeElement,f.closeButton);
    f.key('Tab',true);assert.equal(f.d.activeElement,last);
    f.d.getElementById('contentAction').focus();assert.equal(f.d.activeElement,f.closeButton);
    f.key('Escape');assert.equal(f.d.activeElement,f.button);assert.equal(f.sidebar.hasAttribute('inert'),true);
    assert.equal(f.d.querySelector('main').hasAttribute('inert'),false);assert.equal(f.d.querySelector('main').getAttribute('aria-hidden'),'false');
    assert.equal(f.d.body.style.overflow,'auto');assert.equal(f.button.getAttribute('aria-expanded'),'false');
    f.button.click();f.closeButton.click();assert.equal(f.d.activeElement,f.button);
    f.button.click();f.d.getElementById('nativeSidebarOverlay').click();assert.equal(f.d.activeElement,f.button);
  }finally{f.close();}
});

test('Responsive breakpoint changes restore normal desktop navigation and close the mobile dialog safely',()=>{
  const f=menuFixture(false);try{
    assert.equal(f.sidebar.hasAttribute('inert'),false);assert.equal(f.sidebar.hasAttribute('aria-hidden'),false);
    f.resize(true);assert.equal(f.sidebar.hasAttribute('inert'),true);
    f.button.click();f.resize(false);
    assert.equal(f.sidebar.hasAttribute('inert'),false);assert.equal(f.sidebar.hasAttribute('aria-modal'),false);
    assert.equal(f.d.querySelector('main').hasAttribute('inert'),false);assert.equal(f.d.body.style.overflow,'auto');
    assert.equal(f.d.activeElement,f.sidebar.querySelector('a[aria-current=page]'));
    f.resize(true);assert.equal(f.sidebar.hasAttribute('inert'),true);assert.equal(f.d.activeElement,f.button);
  }finally{f.close();}
});
