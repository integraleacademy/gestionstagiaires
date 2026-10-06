(() => {
  'use strict';
  const root = document.querySelector('[data-vtc-journey]');
  if (!root) return;
  const config = JSON.parse(document.getElementById('vtcJourneyConfig').textContent);
  const preview = Boolean(document.getElementById('nativePreviewConfig'));
  const access = JSON.parse(document.getElementById(preview ? 'nativePreviewConfig' : 'nativeElearningConfig').textContent);
  const form = root.querySelector('form'), message = root.querySelector('[data-vtc-message]');
  const check = root.querySelector('[data-vtc-check]'), next = root.querySelector('[data-vtc-next]');
  const prev = root.querySelector('[data-vtc-prev]'), review = root.querySelector('[data-vtc-review]');
  const definitions = new Map(config.practice.exercises.map(ex => [ex.id, ex]));
  const fields = new Map([...root.querySelectorAll('[data-exercise-id]')].map(el => [el.dataset.exerciseId, el]));
  const weak = new Set(config.weakRefs || []), results = new Map();
  let sequence = [...fields.keys()], index = 0, busy = false, verified = '';
  let answers = {...(config.saved.practice_answers || {})};
  const key = `vtc-journey:${location.pathname}:${config.courseVersion}:${config.activityId}`;
  const readOnly = check.disabled;
  if (config.practice.adaptive && weak.size) {
    sequence.sort((a,b) => Number(weak.has(definitions.get(b).competency)) - Number(weak.has(definitions.get(a).competency)));
    const priority = root.querySelector('[data-vtc-priority]');
    priority.textContent = `Les situations liées à vos premières erreurs passent en priorité : ${[...weak].join(', ')}. Toutes les notions seront ensuite révisées.`;
    priority.hidden = false;
  }
  if (!preview && !config.completed) {
    try { answers = {...answers, ...JSON.parse(sessionStorage.getItem(key) || '{}')}; } catch (_) { /* optional draft */ }
    for (const [id, item] of Object.entries(config.saved.practice_diagnostics || {})) {
      if (fields.has(id) && JSON.stringify(answers[id]) === JSON.stringify(config.saved.practice_answers?.[id])) results.set(id, {correct:item.correct});
    }
  }
  function restore() {
    fields.forEach((el,id) => {
      el.querySelectorAll('input[type=radio]').forEach(input => { input.checked = input.value === answers[id]; });
      el.querySelectorAll('select[data-row-id]').forEach(select => { select.value = answers[id]?.[select.dataset.rowId] || ''; });
    });
  }
  function collect(id) {
    const el = fields.get(id), definition = definitions.get(id);
    if (definition.kind === 'single') {
      const value = el.querySelector('input:checked')?.value;
      if (!value) throw new Error('Sélectionnez une réponse pour continuer.');
      return value;
    }
    const values = [...el.querySelectorAll('select[data-row-id]')];
    if (values.some(e=>!e.value)) throw new Error('Choisissez une proposition pour chaque élément.');
    if (['matching','order'].includes(definition.kind) && new Set(values.map(e=>e.value)).size !== values.length)
      throw new Error('Utilisez chaque proposition une seule fois.');
    return Object.fromEntries(values.map(e=>[e.dataset.rowId,e.value]));
  }
  function cache() {
    if (!preview && !config.completed) try {sessionStorage.setItem(key,JSON.stringify(answers));} catch (_) {}
  }
  function stopAudio() { root.querySelectorAll('audio').forEach(audio=>audio.pause()); }
  function show() {
    stopAudio(); form.hidden=false; review.hidden=true; message.textContent='';
    fields.forEach(el=>{el.hidden=true;});
    const id=sequence[index]; fields.get(id).hidden=false;
    root.querySelector('[data-vtc-step]').textContent=`Étape ${index+1} sur ${sequence.length}`;
    root.querySelector('progress').value=[...results.values()].filter(r=>r.correct).length;
    prev.disabled=busy||index===0;
    next.hidden=!results.has(id); next.disabled=busy;
    check.disabled=readOnly||busy;
  }
  async function post(body) {
    const response=await fetch(preview?access.answerUrl:access.practiceUrl,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','Accept':'application/json','X-Elearning-CSRF':access.csrfToken},
      body:JSON.stringify({...body,...(!preview?{access_token:access.accessToken}:{})})});
    const result=await response.json().catch(()=>({}));
    if(!response.ok||!result.ok) throw new Error(result.error||'Connexion interrompue. Vos choix sont conservés ; réessayez.');
    return result;
  }
  function feedback(id,item) {
    const box=fields.get(id).querySelector('[data-step-feedback]'); box.replaceChildren();box.hidden=false;
    box.dataset.correct=String(item.correct);
    const h=document.createElement('h4');h.textContent=item.correct?'Décision validée':'Cette décision est à reprendre';box.append(h);
    for(const value of [item.consequence,item.explanation,!item.correct&&item.coaching]) {
      if(value){const p=document.createElement('p');p.textContent=value;box.append(p);}
    }
    if(!item.correct){const ul=document.createElement('ul');for(const value of item.correction||[]){const li=document.createElement('li');li.textContent=value;ul.append(li);}box.append(ul);}
  }
  async function finish() {
    if(busy)return;
    stopAudio();form.hidden=true;review.hidden=false;root.querySelector('[data-vtc-step]').textContent='Bilan de l’activité';
    const wrong=[...fields.keys()].filter(id=>!results.get(id)?.correct);
    const text=root.querySelector('[data-vtc-summary]'), box=root.querySelector('[data-vtc-weak]');box.replaceChildren();
    root.querySelector('[data-vtc-retry]').hidden=!wrong.length;
    const verify=root.querySelector('[data-vtc-verify]');verify.hidden=true;
    if(wrong.length){
      text.textContent=`${fields.size-wrong.length} étapes réussies sur ${fields.size}. Reprenez les ${wrong.length} situations à revoir ; vos réponses correctes sont conservées.`;
      for(const ref of new Set(wrong.map(id=>definitions.get(id).competency).filter(Boolean))){const p=document.createElement('p');p.textContent=`À réviser : ${ref}`;box.append(p);}
      return;
    }
    if(readOnly){text.textContent='Le compte en lecture seule ne peut pas vérifier les réponses.';return;}
    busy=true;text.textContent='Vérification de l’ensemble des décisions…';
    try {
      const result=await post({practice_answers:answers});
      if(!result.correct) throw new Error('Une réponse doit être revue. Reprenez les étapes.');
      verified=JSON.stringify(answers);
      text.textContent=preview?'Activité réussie. Vous pouvez explorer la suite du parcours.':'Activité réussie. Cliquez sur « Terminer l’activité » pour enregistrer votre progression et poursuivre.';
      root.querySelector('progress').value=fields.size;
    } catch(error){verified='';text.textContent=error.message;verify.hidden=false;} finally{busy=false;}
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||readOnly)return;
    const id=sequence[index];let value;
    try{value=collect(id);}catch(error){message.textContent=error.message;return;}
    busy=true;check.disabled=true;next.disabled=true;prev.disabled=true;message.textContent='Correction…';
    const activeControls=[...fields.get(id).querySelectorAll('input[type=radio],select[data-row-id]')];
    activeControls.forEach(control=>{control.disabled=true;});
    answers[id]=value;verified='';cache();
    try{
      const result=await post({practice_answers:{[id]:value},practice_step:id});
      const item=result.feedback[0];results.set(id,item);feedback(id,item);next.hidden=false;
      message.textContent=item.correct?'Lisez l’explication puis passez à la suite.':'Lisez le conseil de révision. Vous pouvez modifier votre choix ou poursuivre pour reprendre cette erreur au bilan.';
      root.querySelector('progress').value=[...results.values()].filter(r=>r.correct).length;
    }catch(error){results.delete(id);next.hidden=true;message.textContent=error.message;}
    finally{busy=false;activeControls.forEach(control=>{control.disabled=false;});check.disabled=readOnly;next.disabled=false;prev.disabled=index===0;}
  });
  form.addEventListener('change',event=>{
    const el=event.target.closest('[data-exercise-id]');
    if(!el||(!event.target.matches('input[type=radio]')&&!event.target.matches('select[data-row-id]')))return;
    const id=el.dataset.exerciseId;results.delete(id);verified='';next.hidden=true;el.querySelector('[data-step-feedback]').hidden=true;
    try{answers[id]=collect(id);}catch(_){delete answers[id];}cache();
  });
  next.addEventListener('click',()=>{if(busy)return;if(index+1<sequence.length){index++;show();}else finish();});
  prev.addEventListener('click',()=>{if(!busy&&index>0){index--;show();}});
  root.querySelector('[data-vtc-retry]').addEventListener('click',()=>{if(busy)return;sequence=[...fields.keys()].filter(id=>!results.get(id)?.correct);index=0;show();});
  root.querySelector('[data-vtc-all]').addEventListener('click',()=>{if(busy)return;sequence=[...fields.keys()];index=0;show();});
  root.querySelector('[data-vtc-verify]').addEventListener('click',finish);
  root.querySelectorAll('[data-audio-speed]').forEach(select=>select.addEventListener('change',()=>{select.closest('.vtc-listen').querySelector('audio').playbackRate=Number(select.value);}));
  root.querySelectorAll('[data-vtc-simulator]').forEach(sim=>{
    const cfg=JSON.parse(sim.dataset.config), price=sim.querySelector('[data-sim-price]'), km=sim.querySelector('[data-sim-km]'), commission=sim.querySelector('[data-sim-commission]');
    function calculate(){const p=Number(price.value),k=Number(km.value),c=Number(commission.value);const contribution=p*(1-c/100)-k*Number(cfg.cost_km);
      sim.querySelector('[data-sim-price-label]').textContent=`${p} €`;sim.querySelector('[data-sim-km-label]').textContent=`${k} km`;
      sim.querySelector('[data-sim-result]').textContent=`Recette après commission : ${(p*(1-c/100)).toFixed(2)} € · Coût variable : ${(k*Number(cfg.cost_km)).toFixed(2)} € · Contribution : ${contribution.toFixed(2)} €`;
    }sim.addEventListener('input',calculate);calculate();
  });
  restore();
  const first=sequence.findIndex(id=>!results.get(id)?.correct);index=Math.max(0,first);show();
  window.aps62Practice={clearDraft(){try{sessionStorage.removeItem(key);}catch(_){}},collectForCompletion(){
    if(busy||verified!==JSON.stringify(answers))throw new Error('Terminez les étapes, reprenez vos erreurs et consultez le bilan avant de continuer.');
    return answers;
  }};
  if(first===-1 && !readOnly) finish();
})();
