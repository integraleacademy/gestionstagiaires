(() => {
  'use strict';
  const root=document.querySelector('[data-vtc-production]'), raw=document.getElementById('vtcProductionConfig');
  if(!root || !raw)return;
  const config=JSON.parse(raw.textContent), fields=[...root.querySelectorAll('[data-production-field]')];
  const form=root.querySelector('form'), button=form.querySelector('button'), status=root.querySelector('[data-vtc-production-status]');
  const saveStatus=root.querySelector('[data-vtc-save-status]'), feedback=root.querySelector('[data-vtc-production-feedback]');
  const review=root.querySelector('[data-vtc-reviewed]'), reviewLabel=root.querySelector('[data-vtc-review-label]');
  const history=root.querySelector('[data-vtc-production-history]');
  let busy=false,dirty=false,revision=0,timer,queue=Promise.resolve(),correctedAnswers=null,latestFeedback=null;
  const saved=config.saved || {};
  fields.forEach(field=>{field.value=saved.production_answers?.[field.dataset.productionField] || '';});
  const collect=()=>Object.fromEntries(fields.map(field=>[field.dataset.productionField,field.value.trim()]));
  const same=(a,b)=>Boolean(a&&b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(key=>Object.prototype.hasOwnProperty.call(b,key)&&a[key]===b[key]);
  function node(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text);return el;}
  function list(title,items,parent=feedback){if(!Array.isArray(items)||!items.length)return;parent.append(node('h3',title));const ul=node('ul');items.forEach(text=>ul.append(node('li',text)));parent.append(ul);}
  function send(payload){
    const run=async()=>{
      const response=await fetch(config.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Elearning-CSRF':config.csrfToken},body:JSON.stringify({...payload,...(config.preview?{}:{access_token:config.accessToken})})});
      const result=(response.headers.get('content-type')||'').includes('application/json')?await response.json():{};
      if(!response.ok||!result.ok)throw new Error(result.error || 'Votre demande n’a pas abouti. Gardez votre copie et réessayez.');
      return result;
    };
    const result=queue.then(run,run);queue=result.catch(()=>{});return result;
  }
  function showFeedback(result,answers){
    latestFeedback=result;correctedAnswers={...answers};feedback.replaceChildren();
    feedback.append(node('h2','Votre correction détaillée'));
    const heading=node('div');heading.className='vtc-feedback-score';
    if(Number.isFinite(result.score)&&Number.isFinite(result.max_score))heading.append(node('strong',`${result.score} / ${result.max_score}`));
    heading.append(node('span',result.trainer_review?'Retour du formateur':'Évaluation pédagogique par IA'));feedback.append(heading);
    if(result.summary)feedback.append(node('p',result.summary));
    if(result.needs_human_review){const warning=node('p','Certains points nécessitent une relecture du formateur. Vous pouvez reprendre votre réponse et demander une nouvelle correction. Votre copie est conservée.');warning.className='vtc-feedback-warning';feedback.append(warning);list('Points à vérifier',result.human_review_reasons);}
    list('Ce que vous avez bien fait',result.strengths);
    (result.criteria||[]).forEach(criterion=>{
      const box=node('article');box.className='vtc-feedback-criterion';box.append(node('h4',`${criterion.label} · ${criterion.points} / ${criterion.max_points}`));
      if(criterion.feedback)box.append(node('p',criterion.feedback));
      if(criterion.evidence){const evidence=node('p',Array.isArray(criterion.evidence)?criterion.evidence.join('\n'):criterion.evidence);evidence.className='vtc-feedback-evidence';box.append(evidence);}
      if(criterion.improvement)box.append(node('p',criterion.improvement));feedback.append(box);
    });
    if(result.errors?.length){feedback.append(node('h3','Les erreurs à comprendre'));result.errors.forEach(error=>{const box=node('article');box.className='vtc-feedback-criterion';if(error.excerpt)box.append(node('p','Dans votre réponse : « '+error.excerpt+' »'));box.append(node('p',error.explanation));if(error.correction)box.append(node('p','À retenir : '+error.correction));feedback.append(box);});}
    config.production.response_fields.forEach(field=>{
      const model=result.model_response?.[field.id],improved=result.improved_response?.[field.id];
      if(model||improved){const detail=node('details');detail.append(node('summary','Exemples pour « '+field.label+' »'));if(improved)detail.append(node('h4','Une amélioration possible de votre réponse'),node('p',improved));if(model)detail.append(node('h4','Réponse de référence'),node('p',model));feedback.append(detail);}
    });
    list('Vos prochaines étapes',result.next_steps);
    if(result.revision_targets?.length){feedback.append(node('h3','Les notions à revoir'));const ul=node('ul');result.revision_targets.forEach(target=>ul.append(node('li',typeof target==='string'?target:(target.title||target.label||target.ref||''))));feedback.append(ul);}
    if(result.trainer_review){feedback.append(node('h3','Relecture du formateur'),node('p',result.trainer_review.comment));}
    feedback.append(node('p',result.notice||'Cette correction accompagne votre entraînement. Elle ne constitue pas un résultat à l’examen officiel.'));
    feedback.hidden=false;reviewLabel.hidden=Boolean(config.preview)||Boolean(result.needs_human_review);review.checked=Boolean(config.completed);
  }
  function showHistory(attempts){
    history.replaceChildren();if(!attempts?.length){history.hidden=true;return;}history.append(node('h3','Vos copies et vos progrès'));
    [...attempts].reverse().forEach((attempt,index)=>{
      const detail=node('details');const date=new Date(attempt.submitted_at).toLocaleString('fr-FR');
      const score=Number.isFinite(attempt.feedback?.score)?` · ${attempt.feedback.score}/${attempt.feedback.max_score}`:'';
      const state={processing:'Correction en cours',failed:'Correction à relancer',corrected:'Corrigé',needs_human_review:'Relecture demandée',trainer_reviewed:'Relu par le formateur'}[attempt.status]||'';
      detail.append(node('summary',`Copie ${index+1} · ${date} · ${state}${score}`));
      config.production.response_fields.forEach(field=>detail.append(node('h4',field.label),node('p',attempt.answers?.[field.id]||'Sans réponse')));
      if(attempt.feedback?.summary)detail.append(node('p',attempt.feedback.summary));history.append(detail);
    });history.hidden=false;
  }
  async function saveDraft(){
    if(config.preview||config.completed||busy)return;
    const currentRevision=revision,answers=collect();
    try{await send({stage:'draft',production_answers:answers});if(currentRevision===revision){dirty=false;saveStatus.textContent='Brouillon enregistré.';}}
    catch(error){saveStatus.textContent=error.message;}
  }
  fields.forEach(field=>field.addEventListener('input',()=>{
    dirty=true;revision++;review.checked=false;clearTimeout(timer);saveStatus.textContent=config.preview?'Copie d’aperçu.':'Enregistrement du brouillon…';timer=setTimeout(saveDraft,800);
    if(correctedAnswers&&!same(collect(),correctedAnswers))status.textContent='Votre réponse a changé. Demandez une nouvelle correction pour cette version.';
  }));
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||config.completed||!form.reportValidity())return;
    clearTimeout(timer);busy=true;button.disabled=true;fields.forEach(field=>{field.readOnly=true;});review.checked=false;
    status.textContent='Analyse de votre copie et du barème… La correction peut prendre quelques instants.';
    const answers=collect();
    try{const result=await send({stage:'correct',production_answers:answers});dirty=false;showFeedback(result.feedback,answers);showHistory(result.history||[]);saveStatus.textContent=config.preview?'Aperçu : aucun suivi stagiaire modifié.':'Copie et correction enregistrées.';status.textContent=result.current_copy===false?'Une autre copie a été enregistrée dans votre espace. Rechargez la page avant de continuer.':result.feedback.needs_human_review?'Reprenez les points signalés ou demandez une relecture à votre formateur.':'Lisez votre correction. Vous pouvez améliorer votre réponse, puis la faire corriger à nouveau.';feedback.scrollIntoView?.({behavior:'smooth',block:'start'});}
    catch(error){status.textContent=error.message;if(!config.preview)saveStatus.textContent='Votre copie reste affichée sur cette page. Vérifiez l’enregistrement avant de fermer.';}
    finally{busy=false;button.disabled=false;fields.forEach(field=>{field.readOnly=false;});}
  });
  if(saved.production_ai_feedback){showFeedback(saved.production_ai_feedback,saved.production_ai_answers||saved.production_answers||{});if(!same(collect(),correctedAnswers)){review.checked=false;status.textContent='La correction affichée concerne votre copie précédente. Faites corriger la version actuelle avant de continuer.';}}
  showHistory(config.history||[]);
  saveStatus.textContent=config.preview?'Mode aperçu.':saved.production_answers?'Votre brouillon a été restauré.':'Le brouillon s’enregistre pendant la saisie.';
  window.addEventListener('beforeunload',event=>{if(!config.preview&&!config.completed&&dirty){event.preventDefault();event.returnValue='';}});
  // The shared player delegates completion to the production currently mounted.
  window.aps62Production={
    markCompleted(){config.completed=true;dirty=false;clearTimeout(timer);fields.forEach(field=>{field.readOnly=true;});button.disabled=true;review.disabled=true;},
    collectForCompletion(){
      if(busy)throw new Error('Attendez la fin de la correction.');
      if(!form.reportValidity())throw new Error('Complétez votre production.');
      const answers=collect();
      if(!latestFeedback||!correctedAnswers||!same(answers,correctedAnswers))throw new Error('Faites corriger la version actuelle de votre travail avant de continuer.');
      if(latestFeedback.needs_human_review)throw new Error('Reprenez les points signalés ou faites relire cette copie par votre formateur.');
      if(!latestFeedback.trainer_review && Number(latestFeedback.score)<Number(config.production.pass_points||12))throw new Error('Améliorez votre réponse avec les conseils pour atteindre l’objectif de 12/20.');
      if(!review.checked)throw new Error('Confirmez que vous avez lu la correction et les conseils.');
      clearTimeout(timer);return{production_answers:answers,production_reviewed:true};
    }
  };
})();
