const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('templates/admin_cnaps_tracking.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const card=fs.readFileSync('static/js/cnaps-card.js','utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function runtime(boxes=[]){
  const context=vm.createContext({
    document:{querySelectorAll:s=>s==='[data-card-pro-followup]'?boxes:[],getElementById:()=>null,addEventListener:()=>{}},
    window:{cnapsRead(){throw new Error('unexpected request');}},URLSearchParams,queueMicrotask:()=>{},
    setTimeout,clearTimeout
  });
  vm.runInContext(card,context);
  vm.runInContext(source,context);
  vm.runInContext('cnapsFollowupQueue.delayMs=0;',context);
  return context;
}
function box(name,{hidden=false,saved=null,nub='1234567'}={}){
  const result={textContent:'Aucune vérification enregistrée',innerHTML:'',className:''};
  const message={textContent:''},date={textContent:''};
  const retry={hidden:!nub, addEventListener(event,fn){this.click=fn;}};
  const row={style:{display:hidden?'none':''}};
  return {name,result,date,message,retry,row,getAttribute:key=>({'data-nom':name,'data-prenom':'Test','data-nub':nub,'data-tracking-id':name,'data-cnaps-snapshot':JSON.stringify(saved)})[key],querySelector:key=>({'[data-card-pro-result]':result,'[data-card-pro-message]':message,'[data-card-pro-date]':date,'[data-cnaps-retry]':retry})[key],closest:()=>row};
}
test('opening the tracking page renders saved results and dates without queueing external checks',async()=>{
  const cached=box('cached',{saved:{check_status:'success',checked_at:'2026-09-19T10:00:00Z',active_titles:[{display_status:'AP A3P ACTIF'}]}});
  const unchecked=box('unchecked'),missing=box('missing',{nub:''});
  const context=runtime([cached,unchecked,missing]);
  await flush();
  assert.match(cached.result.innerHTML,/AP A3P ACTIF/);
  assert.match(cached.date.textContent,/19\/09\/2026/);
  assert.equal(cached.message.textContent,'');
  assert.equal(unchecked.result.textContent,'Aucune vérification enregistrée');
  assert.match(missing.result.innerHTML,/NUB absent/);
  assert.equal(vm.runInContext('cnapsFollowupQueue.lastStart',context),0);
  const requests=[];
  context.window.cnapsRead=async url=>{
    requests.push(new URL(url,'https://example.test'));
    return {ok:true,json:async()=>({ok:true,check_status:'success',checked_at:'2026-11-12T10:00:00Z',active_titles:[]})};
  };
  unchecked.retry.click();
  await flush();
  assert.equal(requests.length,1);
  assert.equal(requests[0].searchParams.get('nom'),'unchecked');
  assert.equal(requests[0].searchParams.get('cache'),'bypass');
  assert.match(unchecked.result.innerHTML,/Aucun titre CNAPS trouvé/);
  assert.match(unchecked.date.textContent,/12\/11\/2026/);
});
test('a failing manual check retains the last result and date and enables retry',async()=>{
  const saved=box('saved',{saved:{check_status:'success',checked_at:'2026-09-19T10:00:00Z',active_titles:[{display_status:'AP A3P ACTIF'}]}});
  const context=runtime([saved]);
  context.window.cnapsRead=async()=>{throw new Error('timeout');};
  saved.retry.click();
  await flush();
  assert.match(saved.result.innerHTML,/AP A3P ACTIF/);
  assert.match(saved.date.textContent,/19\/09\/2026/);
  assert.match(saved.message.textContent,/actualisation impossible/);
  assert.equal(saved.retry.disabled,false);
});
test('list, trainee and ADEF cards start external work only on demand and share a pending refresh',async()=>{
  const context=runtime();
  let calls=0,resolve;
  context.window.cnapsRead=url=>{
    calls++;
    assert.equal(new URL(url,'https://example.test').searchParams.get('nub'),'1234567');
    return new Promise(done=>{resolve=done;});
  };
  const data={dataset:{nom:'Test',prenom:'Jean',nub:'1234567',cnapsSnapshot:'{"check_status":"success","active_titles":[]}',cnapsCheckedAt:'2026-09-22T10:00:00Z'}};
  const button={addEventListener(_,handler){this.click=handler;}},message={},date={};
  data.querySelector=key=>({'[data-card-pro-refresh]':button,'[data-card-pro-message]':message,'[data-card-pro-date]':date})[key];
  const renders=[];
  const wait=context.window.cnapsCards.bind(data,result=>renders.push(result));
  assert.equal(calls,0);
  assert.equal(renders.length,1);
  assert.match(date.textContent,/22\/09\/2026/);
  button.click();button.click();
  assert.equal(calls,1);
  assert.equal(button.disabled,true);
  resolve({ok:false,json:async()=>({ok:false})});
  await wait();
  assert.equal(renders.length,1);
  assert.match(date.textContent,/22\/09\/2026/);
  assert.equal(button.disabled,false);
  assert.match(message.textContent,/Actualisation impossible/);
});
test('an upstream NUB is visible without any title and survives a failed title check', async () => {
  const context = runtime();
  const number = {}, result = {}, message = {}, date = {};
  const button = {addEventListener(event, handler) { this.click = handler; }};
  const elements = {
    '[data-card-pro-refresh]': button, '[data-card-pro-message]': message,
    '[data-card-pro-date]': date, '[data-card-pro-nub]': number,
    '[data-card-pro-result], [data-trainee-card-pro-result]': result
  };
  const box = {dataset: {nub: '', nubUrl: '/source', nom: 'TEST'}, querySelector: selector => elements[selector]};
  let calls = 0;
  context.window.cnapsRead = async url => {
    calls++;
    if (url !== '/source') throw new Error('directory unavailable');
    return {ok: true, json: async () => ({ok: true, nub: '0123456', snapshot: {result: null}})};
  };
  const wait = context.window.cnapsCards.bind(box, () => assert.fail('No title to render'));
  await wait();
  assert.equal(calls, 1);
  assert.equal(number.textContent, 'NUB : 0123456');
  assert.equal(result.textContent, 'Aucune vérification enregistrée');
  button.click();
  await wait();
  assert.equal(number.textContent, 'NUB : 0123456');
  assert.match(message.textContent, /Actualisation impossible/);
});
test('visible manually requested dossiers have priority over hidden requests',async()=>{
  const context=runtime(),pending=[],order=[];
  context.window.cnapsRead=url=>{
    order.push(new URL(url,'https://example.test').searchParams.get('nom'));
    return new Promise(resolve=>pending.push(resolve));
  };
  context.boxes=[box('first'),box('hidden',{hidden:true}),box('searched')];
  vm.runInContext('cnapsFollowupQueue.maxActive=1;boxes.forEach(box=>enqueueCnapsFollowup(box));',context);
  await flush();assert.deepEqual(order,['first']);
  pending[0]({ok:true,json:async()=>({ok:true,check_status:'success',active_titles:[]})});
  await flush();assert.deepEqual(order,['first','searched']);
});
test('the external status scheduler paces checks, waits for completion and pauses in the background',async()=>{
  const template=fs.readFileSync('templates/admin_trainees.html','utf8');
  const start=template.indexOf('  function scheduleExternalStatusChecks()');
  const end=template.indexOf('  {% if not is_read_only %}scheduleExternalStatusChecks();',start);
  const scheduler=template.slice(start,end);
  for(const count of [2,250]){
    const rows=Array.from({length:count},(_,i)=>({id:i,isConnected:true,querySelector(){return {};} }));
    let visibility,now,finish;
    const timers=new Map(),requests=[];
    const document={hidden:false,querySelectorAll(){return rows;},addEventListener(_,fn){visibility=fn;}};
    const sandbox={document,setTimeout(fn,delay){const id=Symbol();timers.set(id,{fn,delay});return id;},
      clearTimeout(id){timers.delete(id);},refreshExternalForRow(row,automatic){
        requests.push([row.id,automatic]);
        return new Promise(done=>{finish=done;});
      }};
    vm.runInNewContext(scheduler+'\nscheduleExternalStatusChecks();',sandbox);
    assert.equal(timers.size,1);
    const timer=()=>[...timers.values()][0];
    const pop=()=>{now=timer();timers.clear();return now.fn();};
    assert.equal(timer().delay,60000);
    assert.equal(requests.length,0);
    document.hidden=true;visibility();
    assert.equal(timers.size,0);
    document.hidden=false;visibility();
    assert.equal(timer().delay,60000);
    const completion=pop();
    assert.deepEqual(requests,[[0,true]]);
    visibility();
    assert.equal(timers.size,0);
    finish();await completion;
    assert.equal(timer().delay,Math.max(5000,900000/count));
    const next=pop();
    assert.deepEqual(requests,[[0,true],[1,true]]);
    document.hidden=true;visibility();finish();await next;
    assert.equal(timers.size,0);
  }
});

test('failed CNAPSV3 refresh leaves an existing trainee status and history intact', async () => {
  const sheet = fs.readFileSync('static/js/trainee-sheet.js', 'utf8');
  const script = sheet.slice(sheet.indexOf('  async function cnapsLookup('), sheet.indexOf('  const cnapsContactBtn'));
  let click;
  const existing = {cnaps: 'ACCEPTÉ', statut_cnaps_history: [{status: 'ACCEPTÉ'}]};
  const alerts = [];
  vm.runInNewContext(script, {
    document: { getElementById: () => ({addEventListener(_, handler) { click = handler; }}) },
    sheetContext: {lastName: 'TEST', firstName: 'Camille'},
    window: {cnapsRead: async () => ({ok: false, status: 502})},
    fetch: async (_, options) => { Object.assign(existing, JSON.parse(options.body)); },
    alert: text => alerts.push(text)
  });
  await click();
  assert.deepEqual(existing, {cnaps: 'ACCEPTÉ', statut_cnaps_history: [{status: 'ACCEPTÉ'}]});
  assert.deepEqual(alerts, ['Erreur CNAPS']);
});
