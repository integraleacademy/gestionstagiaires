(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('apsExamConfig').textContent),exam=config.exam,questions=exam.questions;
  const $=id=>document.getElementById(id),key=`aps-exam:${location.pathname}:${exam.version}`;
  let answers={},position=0,attemptId=config.attemptId,submitting=false,finished=false;
  const optionOrders={};
  let draft=null;
  try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved&&typeof saved.attemptId==='string'&&/^[a-f0-9]{32}$/.test(saved.attemptId)){draft=saved;attemptId=saved.attemptId;questions.forEach(q=>{if(q.options.some(o=>o.id===saved.answers?.[q.id]))answers[q.id]=saved.answers[q.id];});if(Number.isInteger(saved.position)&&saved.position>=0&&saved.position<questions.length)position=saved.position;}}catch(_){}
  function randomIndex(size){
    if(window.crypto?.getRandomValues){
      const value=new Uint32Array(1),limit=0x100000000-(0x100000000%size);
      do{window.crypto.getRandomValues(value);}while(value[0]>=limit);
      return value[0]%size;
    }
    return Math.floor(Math.random()*size);
  }
  function validOrder(order,options){
    return Array.isArray(order)&&order.length===options.length&&new Set(order).size===order.length&&order.every(id=>options.some(o=>o.id===id));
  }
  questions.forEach(q=>{
    const saved=draft?.optionOrders?.[q.id];
    const order=validOrder(saved,q.options)?[...saved]:q.options.map(o=>o.id);
    // An existing draft without orders predates shuffling: keep its visible choices.
    // New attempts use independent permutations; saved IDs remain server-authoritative.
    if(!draft)for(let i=order.length-1;i>0;i--){const j=randomIndex(i+1);[order[i],order[j]]=[order[j],order[i]];}
    optionOrders[q.id]=order;
  });
  function optionsFor(question){
    const order=optionOrders[question.id];
    return validOrder(order,question.options)?order.map(id=>question.options.find(o=>o.id===id)):question.options;
  }
  function el(tag,text,css){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(css)node.className=css;return node;}
  function save(){try{sessionStorage.setItem(key,JSON.stringify({answers,position,attemptId,optionOrders}));$('examDraft').textContent='Brouillon conservé dans cet onglet.';}catch(_){$('examDraft').textContent='Le navigateur ne conserve pas le brouillon. Gardez cette page ouverte.';}}
  function update(){const count=Object.keys(answers).length;$('examAnswered').textContent=`${count} / ${questions.length} réponses`;$('examProgress').value=count;[...$('examGrid').children].forEach((b,i)=>{b.classList.toggle('is-answered',Boolean(answers[questions[i].id]));b.setAttribute('aria-current',String(i===position));b.setAttribute('aria-label',`Question ${i+1}${answers[questions[i].id]?', réponse saisie':', à compléter'}`);});}
  function render(focus=false){const q=questions[position],field=$('examQuestion');field.replaceChildren();const legend=el('legend',q.prompt);legend.tabIndex=-1;field.append(legend);optionsFor(q).forEach((o,i)=>{const label=el('label',undefined,'exam-option'),input=el('input');input.type='radio';input.name=q.id;input.value=o.id;input.checked=answers[q.id]===o.id;input.addEventListener('change',()=>{answers[q.id]=o.id;save();update();$('examError').hidden=true;});label.append(input,el('span',`${String.fromCharCode(65+i)}. ${o.text}`));field.append(label);});$('examPosition').textContent=`Question ${position+1} / ${questions.length}`;$('examPrevious').disabled=position===0;$('examNext').disabled=position===questions.length-1;update();if(focus)legend.focus();}
  questions.forEach((q,i)=>{const b=el('button',String(i+1));b.type='button';b.addEventListener('click',()=>{position=i;render(true);save();});$('examGrid').append(b);});
  $('examPrevious').addEventListener('click',()=>{position--;render(true);save();});$('examNext').addEventListener('click',()=>{position++;render(true);save();});
  function remaining(){const i=questions.findIndex(q=>!answers[q.id]);if(i>=0){position=i;render(true);}else $('examSubmit').focus();return i;}
  $('examReview').addEventListener('click',()=>{remaining();save();});
  function displayResult(result){finished=true;$('examWorkspace').hidden=true;const panel=$('examResult');panel.hidden=false;panel.replaceChildren();const hero=el('div',undefined,'exam-result-hero');hero.append(el('span','VOTRE BILAN','exam-eyebrow'),el('h2',result.passed?'Objectif d’entraînement atteint':'Des repères à consolider'),el('p',`${result.percent} %`,'exam-score'),el('p',`${result.score} réponses justes sur ${result.total}. Objectif : ${result.pass_percent} %.`),el('p',config.preview?'Résultat d’aperçu, sans enregistrement stagiaire.':'Votre tentative a été enregistrée. Vous pouvez revoir les explications puis recommencer.','exam-note'));const missed={};result.corrections.filter(c=>!c.correct).forEach(c=>{missed[c.module]=(missed[c.module]||0)+1;});if(Object.keys(missed).length){const box=el('div',undefined,'exam-suggestions'),list=el('ul');box.append(el('strong','Votre programme de révision'));Object.entries(missed).sort((a,b)=>b[1]-a[1]).forEach(([module,n])=>list.append(el('li',`${module} : ${n} réponse${n>1?'s':''} à revoir.`)));box.append(list);hero.append(box);}const actions=el('div',undefined,'exam-result-actions'),retry=el('button','Recommencer l’examen','exam-primary'),print=el('button','Imprimer ma correction','exam-secondary'),expand=el('button','Ouvrir toutes les corrections','exam-secondary');retry.type=print.type=expand.type='button';retry.addEventListener('click',()=>location.reload());print.addEventListener('click',()=>{panel.querySelectorAll('details').forEach(d=>d.open=true);window.print();});expand.addEventListener('click',()=>panel.querySelectorAll('details').forEach(d=>d.open=true));actions.append(retry,expand,print);hero.append(actions);panel.append(hero,el('h2','La correction, question par question'));result.corrections.forEach((q,i)=>{const detail=el('details',undefined,`exam-correction${q.correct?'':' is-wrong'}`),summary=el('summary');summary.append(el('span',q.correct?'✓ Juste':'À revoir'),document.createTextNode(`${i+1}. ${q.prompt}`));detail.append(summary);const body=el('div',undefined,'exam-correction-body'),list=el('ul');optionsFor(q).forEach(o=>list.append(el('li',`${o.text}${o.id===q.answer?' — Réponse attendue':''}${o.id===q.selected?' — Votre choix':''}`,o.id===q.answer?'right-answer':o.id===q.selected?'chosen-wrong':'')));body.append(list,el('p',q.explanation),el('p',q.module,'exam-note'));(q.sources||[]).forEach(s=>{const title=Array.isArray(s)?s[0]:typeof s==='string'?s:s.title,url=Array.isArray(s)?s[1]:s.url;if(/^https:\/\//.test(url||'')){const a=el('a',title+' ↗','exam-source');a.href=url;a.target='_blank';a.rel='noopener noreferrer';body.append(a);}else if(title)body.append(el('p',title,'exam-note'));});(q.lesson_links||[]).forEach(l=>{const a=el('a','Revoir la leçon '+l.ref,'exam-source');a.href=l.url;body.append(a);});detail.append(body);panel.append(detail);});try{sessionStorage.removeItem(key);}catch(_){}panel.focus();}
  $('examForm').addEventListener('submit',async event=>{event.preventDefault();if(submitting||finished)return;if(remaining()>=0){$('examError').textContent='Il reste des questions sans réponse. Complétez-les avant la correction.';$('examError').hidden=false;return;}submitting=true;$('examSubmit').disabled=true;$('examSubmit').textContent='Correction en cours…';try{const response=await fetch(config.submitUrl,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Elearning-CSRF':config.csrfToken},body:JSON.stringify({version:exam.version,attempt_id:attemptId,answers})});const data=(response.headers.get('content-type')||'').includes('application/json')?await response.json():{};if(!response.ok||!data.ok)throw new Error(data.error||(response.status===401||response.status===403?'Votre session a expiré ou cet examen n’est plus accessible. Rechargez la page.':'La correction n’a pas pu être enregistrée. Réessayez : vos réponses sont conservées.'));displayResult(data.result);}catch(error){$('examError').textContent=error.message;$('examError').hidden=false;}finally{submitting=false;$('examSubmit').disabled=false;$('examSubmit').textContent='Terminer et voir ma correction';}});
  save();
  render();
})();
