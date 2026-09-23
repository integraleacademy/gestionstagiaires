const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('templates/admin_cnaps_tracking.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function runtime(){
  const timers=[];
  const context=vm.createContext({
    document:{querySelectorAll:()=>[],getElementById:()=>null,addEventListener:()=>{}},
    window:{},AbortController,queueMicrotask:()=>{},
    setTimeout:(fn,ms)=>{const t={fn,ms};timers.push(t);return t;},
    clearTimeout:t=>{if(t)t.cleared=true;},
    fetch:()=>Promise.resolve({ok:true,json:async()=>({ok:true,check_status:'success',active_titles:[]})})
  });
  vm.runInContext(source,context);
  vm.runInContext('cnapsFollowupQueue.delayMs=0;',context);
  return {context,timers};
}
function box(name,{hidden=false,saved=null}={}){
  const result={textContent:'Vérification en attente…',innerHTML:'',className:''};
  const message={textContent:''},retry={hidden:true};
  const row={style:{display:hidden?'none':''}};
  return {name,result,message,retry,row,getAttribute:key=>({'data-nom':name,'data-prenom':'Test','data-nub':'1234567','data-tracking-id':name,'data-cnaps-snapshot':JSON.stringify(saved)})[key],querySelector:key=>({'[data-card-pro-result]':result,'[data-card-pro-message]':message,'[data-cnaps-retry]':retry})[key],closest:()=>row};
}
test('searched visible dossier jumps ahead of hidden queued dossiers',async()=>{
  const {context}=runtime();const order=[];const pending=[];
  context.fetch=url=>{order.push(new URL(url,'https://example.test').searchParams.get('nom'));return new Promise(resolve=>pending.push(resolve));};
  context.boxes=[box('first'),box('hidden',{hidden:true}),box('searched')];
  vm.runInContext('cnapsFollowupQueue.maxActive=1;boxes.forEach(box=>enqueueCnapsFollowup(box));',context);
  await flush();assert.deepEqual(order,['first']);
  pending[0]({ok:true,json:async()=>({ok:true,check_status:'success',active_titles:[]})});
  await flush();assert.deepEqual(order,['first','searched']);
});
test('timeout releases queue and retains last successful result with retry',async()=>{
  const {context,timers}=runtime();const first=box('slow'),second=box('next');
  context.boxes=[first,second];
  let requests=0;
  context.fetch=(url,{signal})=>{
    requests++;
    if(requests>1)return Promise.resolve({ok:true,json:async()=>({ok:true,check_status:'success',active_titles:[]})});
    return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('timeout'))));
  };
  vm.runInContext('cnapsFollowupQueue.maxActive=1;cnapsSnapshots.set(boxes[0],{check_status:"success",active_titles:[{display_status:"AP A3P ACTIF"}]});boxes.forEach(box=>enqueueCnapsFollowup(box));',context);
  await flush();
  timers.find(t=>t.ms===20000&&!t.cleared).fn();
  await flush();await flush();
  assert.equal(requests,2);
  assert.match(first.result.innerHTML,/AP A3P ACTIF/);
  assert.match(first.message.textContent,/actualisation impossible/);
  assert.equal(first.retry.hidden,false);
  assert.doesNotMatch(second.result.innerHTML,/Chargement/);
});
test('server snapshot is displayed before a pending live request completes',async()=>{
  const {context}=runtime();const cached=box('cached',{saved:{check_status:'success',active_titles:[{display_status:'AP A3P ACTIF'}]}});
  cached.retry.addEventListener=()=>{};
  context.document.querySelectorAll=selector=>selector==='[data-card-pro-followup]'?[cached]:[];
  context.fetch=()=>new Promise(()=>{});
  vm.runInContext(source.slice(source.indexOf('// Display persisted successful checks')),context);
  await flush();
  assert.match(cached.result.innerHTML,/AP A3P ACTIF/);
  assert.equal(cached.message.textContent,'Actualisation en cours…');
});
