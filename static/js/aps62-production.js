(() => {
  'use strict';
  const root = document.querySelector('[data-aps-production]');
  if (!root) return;
  const config = JSON.parse(document.getElementById('apsProductionConfig').textContent);
  const learner = document.getElementById('nativeElearningConfig');
  const native = learner ? JSON.parse(learner.textContent) : {};
  const fields = [...root.querySelectorAll('[data-production-field]')];
  const status = root.querySelector('[data-production-status]');
  const feedback = root.querySelector('[data-production-feedback]');
  const form = document.getElementById('apsProductionForm');
  let revealed = Boolean(config.production.feedback), busy = false, dirty = false, revision = 0, timer, queue = Promise.resolve();
  const saved = config.saved || {};
  fields.forEach(field => { field.value = saved.production_answers?.[field.dataset.productionField] || ''; });
  function collect() { return Object.fromEntries(fields.map(field => [field.dataset.productionField, field.value.trim()])); }
  function review() { return Object.fromEntries([...feedback.querySelectorAll('[data-production-review]')].map(field => [field.dataset.productionReview, field.value])); }
  function node(tag, text) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; }
  function send(payload) {
    const run = async () => {
      const response = await fetch(config.url, {method:'POST', credentials:'same-origin', headers:{
        'Content-Type':'application/json', 'X-Elearning-CSRF':config.csrfToken || native.csrfToken,
        ...(config.preview ? {} : {'X-Elearning-Token':config.accessToken || native.accessToken})
      }, body:JSON.stringify({...payload, ...(config.preview ? {} : {access_token:config.accessToken || native.accessToken})})});
      const result = (response.headers.get('content-type') || '').includes('application/json') ? await response.json() : {};
      if (!response.ok || !result.ok) throw new Error(result.error || 'Enregistrement impossible. Gardez cette page ouverte et réessayez.');
      return result;
    };
    const pending = queue.then(run, run); queue = pending.catch(() => {}); return pending;
  }
  function showFeedback(result) {
    const previous = review(); feedback.replaceChildren();
    feedback.append(node('h3','Comparer et améliorer votre travail'),node('p','Plusieurs formulations sont possibles. Ces repères servent à vérifier votre raisonnement ; ils ne constituent pas une note.'));
    config.production.response_fields.forEach(field => {
      const text = result.model_response?.[field.id];
      if (text) {const detail=node('details'),summary=node('summary','Exemple pour « '+field.label+' »'),body=node('p',text);body.dataset.model='';detail.append(summary,body);feedback.append(detail);}
    });
    (result.rubric || []).forEach(item => {
      const box=node('div');box.className='aps-production-criterion';
      const label=node('label',item.label),select=node('select');select.id='review-'+item.id;select.dataset.productionReview=item.id;label.htmlFor=select.id;
      [['','Je me situe…'],['checked','J’ai vérifié ou corrigé ce point'],['needs_help','Je souhaite revoir ce point avec le formateur']].forEach(([value,text])=>{const option=node('option',text);option.value=value;select.append(option);});
      select.value=Object.prototype.hasOwnProperty.call(previous,item.id)?previous[item.id]:(saved.production_self_review?.[item.id] || '');select.disabled=Boolean(config.completed);
      select.addEventListener('change',()=>{dirty=true;revision++;clearTimeout(timer);saveDraft();});
      box.append(label,node('p',item.expected),select);feedback.append(box);
    });
    feedback.hidden=false;revealed=true;
  }
  async function saveDraft() {
    if (config.preview || config.completed) return;
    const savingRevision=revision;
    try {await send({stage:'draft',production_answers:collect(),...(revealed?{production_self_review:review()}:{})});if(savingRevision===revision){dirty=false;status.textContent='Brouillon enregistré dans votre espace.';}}
    catch(error){status.textContent=error.message;}
  }
  fields.forEach(field=>field.addEventListener('input',()=>{dirty=true;revision++;clearTimeout(timer);status.textContent=config.preview?'Travail d’aperçu, sans enregistrement stagiaire.':'Enregistrement du brouillon…';timer=setTimeout(saveDraft,900);}));
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !form.reportValidity())return;clearTimeout(timer);busy=true;
    const savingRevision=revision;
    const button=form.querySelector('button');button.disabled=true;status.textContent='Préparation des repères…';
    try {const result=await send({stage:'compare',production_answers:collect()});if(savingRevision===revision)dirty=false;showFeedback(result.feedback);status.textContent=config.preview?'Repères affichés en aperçu. Aucun résultat stagiaire enregistré.':'Relisez votre travail, puis renseignez chaque critère avant de continuer.';feedback.scrollIntoView?.({behavior:'smooth',block:'start'});}
    catch(error){status.textContent=error.message;}finally{busy=false;button.disabled=false;}
  });
  if(config.production.feedback)showFeedback(config.production.feedback);
  status.textContent=config.completed?'Production enregistrée. Votre autoévaluation reste consultable.':config.preview?'Mode aperçu : aucun travail stagiaire ne sera enregistré.':saved.production_answers?'Votre brouillon a été restauré.':'Votre brouillon sera enregistré pendant la saisie.';
  window.addEventListener('beforeunload',event=>{if(!config.preview && !config.completed && dirty){event.preventDefault();event.returnValue='';}});
  window.aps62Production={
    markCompleted(){config.completed=true;dirty=false;clearTimeout(timer);fields.forEach(field=>{field.readOnly=true;});feedback.querySelectorAll('select').forEach(field=>{field.disabled=true;});form.querySelector('button').disabled=true;},
    collectForCompletion(){
      if(busy)throw new Error('Attendez la fin de la comparaison.');
      if(!form.reportValidity())throw new Error('Complétez votre production avant de continuer.');
      if(!revealed)throw new Error('Comparez d’abord votre travail aux repères.');
      const checks=review();
      if(!Object.keys(checks).length || Object.values(checks).some(value=>!['checked','needs_help'].includes(value)))throw new Error('Renseignez chaque critère de votre autoévaluation.');
      clearTimeout(timer);return {production_answers:collect(),production_self_review:checks};
    }
  };
})();
