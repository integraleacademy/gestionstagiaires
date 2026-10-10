const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/aps62-production.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(options={}) {
 const model={rubric:[{id:'facts',label:'Faits vérifiés',expected:'Distinguer la déclaration du constat.'}],model_response:{report:'<img src=x onerror=alert(1)> Exemple factuel.'}};
 const config={production:{response_fields:[{id:'report',label:'Compte rendu'}]},url:'/production',csrfToken:'csrf',accessToken:'signed-token',saved:{production_answers:{report:'Brouillon restauré.'}},...options};
 const dom=new JSDOM(`<section data-aps-production><form id="apsProductionForm"><textarea data-production-field="report" required></textarea><button>Comparer</button></form><p data-production-status></p><section data-production-feedback hidden></section></section><script id="apsProductionConfig" type="application/json">${JSON.stringify(config).replace(/</g,'\\u003c')}</script>`,{url:'https://test.invalid/course',runScripts:'outside-only'});
 const {window}=dom,requests=[];
 let fail=false;
 window.fetch=async(url,opts)=>{requests.push({url,...opts});return {ok:!fail,headers:{get:()=> 'application/json'},json:async()=>fail?{ok:false,error:'Connexion perdue'}:{ok:true,feedback:model}};};
 window.eval(source);
 return {window,requests,close:()=>window.close(),fail:()=>{fail=true;},submit:async()=>{window.document.getElementById('apsProductionForm').dispatchEvent(new window.Event('submit',{cancelable:true}));await flush();}};
}
test('Restored draft remains editable; comparison is required before completion',async()=>{
 const f=fixture(),d=f.window.document,field=d.querySelector('textarea');
 assert.equal(field.value,'Brouillon restauré.');assert.equal(d.querySelector('[data-production-feedback]').hidden,true);
 assert.throws(()=>f.window.aps62Production.collectForCompletion(),/Comparez/);
 field.value='Une nouvelle observation précise.';await f.submit();
 assert.equal(f.requests.length,1);const payload=JSON.parse(f.requests[0].body);
 assert.equal(payload.access_token,'signed-token');assert.equal(payload.stage,'compare');assert.equal(payload.production_answers.report,field.value);
 assert.equal(f.requests[0].headers['X-Elearning-CSRF'],'csrf');assert.equal(d.querySelector('[data-production-feedback]').hidden,false);
 assert.equal(d.querySelector('img'),null);assert.match(d.querySelector('[data-model]').textContent,/<img/);
 assert.throws(()=>f.window.aps62Production.collectForCompletion(),/chaque critère/);
 d.querySelector('select').value='needs_help';const completion=f.window.aps62Production.collectForCompletion();
 assert.equal(completion.production_self_review.facts,'needs_help');assert.equal(completion.production_answers.report,field.value);f.close();
});
test('A failed comparison keeps the production and blocks completion',async()=>{
 const f=fixture();f.fail();await f.submit();
 assert.equal(f.window.document.querySelector('textarea').value,'Brouillon restauré.');
 assert.match(f.window.document.querySelector('[data-production-status]').textContent,/Connexion perdue/);
 assert.throws(()=>f.window.aps62Production.collectForCompletion(),/Comparez/);f.close();
});
test('Completed self-review is restored without inventing a trainer approval',()=>{
 const f=fixture({completed:true,production:{response_fields:[{id:'report',label:'Compte rendu'}],feedback:{rubric:[{id:'facts',label:'Faits',expected:'Vérifier'}],model_response:{report:'Exemple'}}},saved:{production_answers:{report:'Travail conservé'},production_self_review:{facts:'needs_help'}}});
 assert.equal(f.window.document.querySelector('select').value,'needs_help');assert.equal(f.window.document.querySelector('select').disabled,true);
 assert.match(f.window.document.querySelector('[data-production-status]').textContent,/autoévaluation/);f.close();
});

test('Pending edits guard navigation; a saved partial self-review survives reload',async()=>{
 const f=fixture(),d=f.window.document;
 d.querySelector('textarea').value='Un nouveau brouillon en attente.';
 d.querySelector('textarea').dispatchEvent(new f.window.Event('input'));
 const pending=new f.window.Event('beforeunload',{cancelable:true});
 f.window.dispatchEvent(pending);assert.equal(pending.defaultPrevented,true);
 await f.submit();
 const checked=d.querySelector('select');checked.value='needs_help';checked.dispatchEvent(new f.window.Event('change'));
 await flush();
 const last=JSON.parse(f.requests.at(-1).body);
 assert.equal(last.stage,'draft');assert.equal(last.production_self_review.facts,'needs_help');
 const saved=new f.window.Event('beforeunload',{cancelable:true});f.window.dispatchEvent(saved);assert.equal(saved.defaultPrevented,false);
 f.window.aps62Production.markCompleted();assert.equal(d.querySelector('textarea').readOnly,true);assert.equal(checked.disabled,true);f.close();
});

test('Clearing a restored self-review stays cleared after comparing again',async()=>{
 const f=fixture({production:{response_fields:[{id:'report',label:'Compte rendu'}],feedback:{rubric:[{id:'facts',label:'Faits',expected:'Vérifier'}],model_response:{report:'Exemple'}}},saved:{production_answers:{report:'Travail à reprendre'},production_self_review:{facts:'needs_help'}}});
 const choice=f.window.document.querySelector('select');choice.value='';choice.dispatchEvent(new f.window.Event('change'));await flush();await f.submit();
 assert.equal(f.window.document.querySelector('select').value,'');
 assert.throws(()=>f.window.aps62Production.collectForCompletion(),/chaque critère/);f.close();
});
