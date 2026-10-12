const {JSDOM}=require('jsdom');
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/js/vtc-production.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const ANSWER='Je confirme le point de rendez-vous et l’heure de prise en charge.';
const FEEDBACK={score:17,max_score:20,needs_human_review:false,summary:'Votre réponse est précise.',strengths:['Le rendez-vous est confirmé.'],criteria:[{label:'Informer',points:17,max_points:20,feedback:'Préciser le nom de réservation.',evidence:'Je confirme',improvement:'Ajouter la référence.'}],errors:[],next_steps:['Vérifier le numéro.'],model_response:{report:'<img src=x onerror=alert(1)> Exemple de référence.'}};
function fixture(options={}){
 const config={production:{response_fields:[{id:'report',label:'Votre message'}],pass_points:12},url:'/production',csrfToken:'csrf',accessToken:'signed',saved:{production_answers:{report:ANSWER}},...options};
 const textareas=config.production.response_fields.map(field=>`<textarea data-production-field="${field.id}" required></textarea>`).join('');
 const dom=new JSDOM(`<section data-aps-production data-vtc-production><form id="vtcProductionForm">${textareas}<button>Corriger</button><span data-vtc-save-status></span></form><p data-vtc-production-status></p><section data-vtc-production-feedback hidden></section><label data-vtc-review-label hidden><input type="checkbox" data-vtc-reviewed></label><section data-vtc-production-history hidden></section><script id="vtcProductionConfig" type="application/json">${JSON.stringify(config).replace(/</g,'\\u003c')}</script></section><a id="vtcOptionalSkip" href="#next">Passer cet atelier facultatif →</a>`,{url:'https://test.invalid/course',runScripts:'outside-only'});
 const w=dom.window,requests=[];let failed=false,result=FEEDBACK;
 w.fetch=async(url,opts)=>{requests.push({url,...opts});return{ok:!failed,headers:{get:()=> 'application/json'},json:async()=>failed?{ok:false,error:'Correction indisponible'}:{ok:true,feedback:result,history:[{id:'one',submitted_at:'2026-10-12T06:00:00Z',status:'corrected',answers:{report:ANSWER},feedback:result}]}};};
 w.eval(source);
 return{w,requests,setFeedback(value){result=value;},fail(){failed=true;},close(){w.close();},input(value){const field=w.document.querySelector('textarea');field.value=value;field.dispatchEvent(new w.Event('input'));},async skip(){w.document.getElementById('vtcOptionalSkip').click();await flush();await new Promise(resolve=>setTimeout(resolve,0));},async submit(){w.document.getElementById('vtcProductionForm').dispatchEvent(new w.Event('submit',{cancelable:true}));await flush();}};
}
test('Correction is escaped, saved and must be read before completion',async()=>{
 const f=fixture(),d=f.w.document;
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/corriger/);
 await f.submit();
 assert.equal(f.requests.length,1);
 const sent=JSON.parse(f.requests[0].body);assert.equal(sent.stage,'correct');assert.equal(sent.access_token,'signed');assert.equal(f.requests[0].headers['X-Elearning-CSRF'],'csrf');
 assert.equal(d.querySelector('[data-vtc-production-feedback]').hidden,false);
 assert.equal(d.querySelector('img'),null);assert.match(d.querySelector('[data-vtc-production-feedback]').textContent,/<img/);
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/Confirmez/);
 d.querySelector('[data-vtc-reviewed]').checked=true;
 assert.equal(f.w.aps62Production.collectForCompletion().production_reviewed,true);
 assert.equal(d.querySelector('[data-vtc-production-history]').hidden,false);f.close();
});
test('Edited text invalidates an earlier correction and guards navigation',async()=>{
 const f=fixture(),d=f.w.document;await f.submit();d.querySelector('[data-vtc-reviewed]').checked=true;
 const field=d.querySelector('textarea');field.value='Nouvelle réponse différente de la première copie.';field.dispatchEvent(new f.w.Event('input'));
 assert.equal(d.querySelector('[data-vtc-reviewed]').checked,false);
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/version actuelle/);
 const event=new f.w.Event('beforeunload',{cancelable:true});f.w.dispatchEvent(event);assert.equal(event.defaultPrevented,true);f.close();
});
test('Provider failure preserves text and does not invent feedback',async()=>{
 const f=fixture();f.fail();await f.submit();assert.equal(f.w.document.querySelector('textarea').value,ANSWER);
 assert.equal(f.w.document.querySelector('[data-vtc-production-feedback]').hidden,true);
 assert.match(f.w.document.querySelector('[data-vtc-production-status]').textContent,/indisponible/);
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/corriger/);f.close();
});
test('Insufficient scores and uncertain feedback both require further work',async()=>{
 for(const result of [{...FEEDBACK,score:8},{...FEEDBACK,needs_human_review:true}]){
  const f=fixture();f.setFeedback(result);await f.submit();f.w.document.querySelector('[data-vtc-reviewed]').checked=true;
  assert.throws(()=>f.w.aps62Production.collectForCompletion(),/12\/20|formateur/);f.close();
 }
});
test('A changed draft restored after reload is not treated as the corrected copy',()=>{
 const f=fixture({saved:{production_answers:{report:'Une nouvelle copie encore non corrigée.'},production_ai_answers:{report:ANSWER},production_ai_feedback:FEEDBACK}});
 f.w.document.querySelector('[data-vtc-reviewed]').checked=true;
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/version actuelle/);f.close();
});
test('Restored correction accepts identical fields despite JSON key sorting',()=>{
 const f=fixture({production:{response_fields:[{id:'z_message',label:'Message'},{id:'a_reason',label:'Justification'}],pass_points:12},saved:{production_answers:{a_reason:'La réservation doit être identifiable.',z_message:ANSWER},production_ai_answers:{a_reason:'La réservation doit être identifiable.',z_message:ANSWER},production_ai_feedback:FEEDBACK}});
 f.w.document.querySelector('[data-vtc-reviewed]').checked=true;
 assert.deepEqual(JSON.parse(JSON.stringify(f.w.aps62Production.collectForCompletion().production_answers)),{z_message:ANSWER,a_reason:'La réservation doit être identifiable.'});f.close();
});
test('Preview calls the provider without learner access token or completion credit',async()=>{
 const f=fixture({preview:true});await f.submit();const sent=JSON.parse(f.requests[0].body);assert.equal('access_token' in sent,false);
 assert.equal(f.w.document.querySelector('[data-vtc-review-label]').hidden,true);
 assert.match(f.w.document.querySelector('[data-vtc-save-status]').textContent,/aucun suivi stagiaire/);f.close();
});
test('Requested analysis message is exact and the correction uses neutral labels',async()=>{
 const f=fixture(),d=f.w.document;
 f.setFeedback({...FEEDBACK,notice:'Correction pédagogique par IA avec OpenAI et ChatGPT.'});
 d.getElementById('vtcProductionForm').dispatchEvent(new f.w.Event('submit',{cancelable:true}));
 assert.equal(d.querySelector('[data-vtc-production-status]').textContent,'Analyse de vos réponses… La correction peut prendre quelques instants');
 await flush();
 const visible=d.querySelector('[data-vtc-production-feedback]').textContent;
 assert.match(visible,/Retour pédagogique/);
 assert.match(visible,/atelier facultatif/);
 assert.doesNotMatch(visible,/intelligence artificielle|ChatGPT|OpenAI|\bIA\b/i);
 assert.doesNotMatch(visible,/Retour du formateur/);
 f.close();
});
test('Restored legacy notice and review reason use neutral wording',()=>{
 const legacy={...FEEDBACK,needs_human_review:true,notice:'Correction pédagogique formative réalisée avec l’IA.',human_review_reasons:['Le correcteur IA demande une relecture du formateur.']};
 const f=fixture({saved:{production_answers:{report:ANSWER},production_ai_answers:{report:ANSWER},production_ai_feedback:legacy}});
 const visible=f.w.document.querySelector('[data-vtc-production-feedback]').textContent;
 assert.doesNotMatch(visible,/intelligence artificielle|ChatGPT|OpenAI|\bIA\b/i);
 assert.match(visible,/vous pouvez poursuivre le parcours/);
 assert.match(visible,/relecture du formateur est nécessaire/);
 f.close();
});
test('The workshop score never claims to be a condition for continuing the course',async()=>{
 const f=fixture();f.setFeedback({...FEEDBACK,score:8});await f.submit();
 f.w.document.querySelector('[data-vtc-reviewed]').checked=true;
 assert.throws(()=>f.w.aps62Production.collectForCompletion(),/Vous pouvez poursuivre le parcours sans valider cet atelier facultatif/);
 f.close();
});
test('Skipping flushes the latest draft without correction or field validation, including empty text',async()=>{
 for(const answer of ['x','']){
  const f=fixture(),d=f.w.document;
  try{
   d.querySelector('form').reportValidity=()=>{throw new Error('Skipping must not validate the form');};
   f.input(answer);await f.skip();
   assert.equal(f.w.location.hash,'#next');
   assert.equal(f.requests.length,1);
   assert.deepEqual(JSON.parse(f.requests[0].body),{stage:'draft',production_answers:{report:answer},access_token:'signed'});
   assert.equal(d.querySelector('[data-vtc-production-feedback]').hidden,true);
   const event=new f.w.Event('beforeunload',{cancelable:true});f.w.dispatchEvent(event);assert.equal(event.defaultPrevented,false);
  }finally{f.close();}
 }
});
test('Skipping waits for older draft saves then saves the current text in order',async()=>{
 const f=fixture(),pending=[];
 try{
  f.w.fetch=(url,opts)=>new Promise(resolve=>{f.requests.push({url,...opts});pending.push(()=>resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true})}));});
  f.input('Premier brouillon.');
  const older=f.w.aps62Production.saveDraftForNavigation();await flush();
  f.input('Dernière saisie à conserver.');
  f.w.document.getElementById('vtcOptionalSkip').click();await flush();
  assert.equal(f.w.location.hash,'');assert.equal(f.requests.length,1);
  pending.shift()();await flush();
  assert.equal(f.w.location.hash,'');assert.equal(f.requests.length,2);
  pending.shift()();await flush();
  // A concurrent flush can enqueue the same latest draft; none may restore the older text.
  while(pending.length){pending.shift()();await flush();}
  await older;
  assert.equal(f.w.location.hash,'#next');
  assert.ok(f.requests.every(request=>JSON.parse(request.body).stage==='draft'));
  assert.ok(f.requests.slice(1).every(request=>JSON.parse(request.body).production_answers.report==='Dernière saisie à conserver.'));
 }finally{f.close();}
});
test('A failed skip save preserves text and offers passage without claiming it was saved',async()=>{
 const f=fixture();
 try{
  f.fail();f.input('Brouillon conservé à l’écran.');await f.skip();
  assert.equal(f.w.location.hash,'');
  assert.equal(f.w.document.querySelector('textarea').value,'Brouillon conservé à l’écran.');
  assert.match(f.w.document.querySelector('[data-vtc-save-status]').textContent,/Cliquez de nouveau.*sans enregistrer cette dernière saisie/);
  await f.skip();assert.equal(f.w.location.hash,'#next');assert.equal(f.requests.length,1);
 }finally{f.close();}
});
test('Skipping never waits for an already submitted correction',async()=>{
 const f=fixture();let resolveCorrection;
 try{
  f.w.fetch=(url,opts)=>new Promise(resolve=>{f.requests.push({url,...opts});resolveCorrection=()=>resolve({ok:true,headers:{get:()=> 'application/json'},json:async()=>({ok:true,feedback:FEEDBACK})});});
  f.input(ANSWER);await f.submit();
  assert.equal(f.requests.length,1);assert.equal(JSON.parse(f.requests[0].body).stage,'correct');
  await f.skip();
  assert.equal(f.w.location.hash,'#next');assert.equal(f.requests.length,1);
  const event=new f.w.Event('beforeunload',{cancelable:true});f.w.dispatchEvent(event);assert.equal(event.defaultPrevented,false);
  resolveCorrection();await flush();
 }finally{f.close();}
});
test('Unedited drafts, previews and completed workshops pass without any save or grading request',async()=>{
 for(const options of [{},{preview:true},{completed:true}]){
  const f=fixture(options);
  try{
   if(options.preview||options.completed)f.input('Aucune sauvegarde nécessaire.');
   await f.skip();assert.equal(f.w.location.hash,'#next');assert.equal(f.requests.length,0);
  }finally{f.close();}
 }
});
