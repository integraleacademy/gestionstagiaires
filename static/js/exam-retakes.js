(() => {
  'use strict';
  const dialog = document.getElementById('retakeDialog'), open = document.getElementById('retakeOpen');
  if (!dialog || !open) return;
  const form = document.getElementById('retakeForm'), history = document.getElementById('retakeHistory');
  const feedback = document.getElementById('retakeFeedback'), days = document.getElementById('retakeDays');
  const field = name => form.elements.namedItem(name);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const euros = n => new Intl.NumberFormat('fr-FR', {style:'currency',currency:'EUR'}).format(n);
  let state = null, editing = null, busy = false, timer = null;
  function say(message = '', error = false) {feedback.textContent = message;feedback.classList.toggle('error',error);}
  async function api(url, payload) {
    const response = await fetch(url, payload === undefined ? {headers:{Accept:'application/json'}} : {method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({...payload,csrf:state.csrf})});
    const result = await response.json().catch(() => ({error:'Votre session a expiré. Rechargez la page.'}));
    if (!response.ok || !result.ok) throw new Error(result.error || 'Opération indisponible. Réessayez.');
    return result;
  }
  function calc() {
    const noDays = field('no_days').checked;
    document.getElementById('retakeDaysSection').hidden = noDays;
    field('exam_price').disabled = field('exam_offered').checked;
    field('exam_price').required = !field('exam_offered').checked;
    field('day_price').disabled = noDays || field('days_offered').checked;
    field('day_price').required = !field('day_price').disabled;
    days.querySelectorAll('input').forEach(input => {input.disabled = noDays;});
    const exam = field('exam_offered').checked ? 0 : Number(field('exam_price').value || 0);
    const training = noDays || field('days_offered').checked ? 0 : Number(field('day_price').value || 0) * days.children.length;
    document.getElementById('retakeTotal').textContent = euros(exam+training);
    document.getElementById('retakeFlow').textContent = exam+training > 0 ? 'Après signature : facture Qonto et lien de paiement par carte. Le règlement intégral confirme le rattrapage.' : 'Si tout est offert : aucune facture. Le rattrapage est confirmé dès la signature de la convention.';
  }
  function addDay(day = {}) {
    const row = document.createElement('div');row.className = 'retake-day';
    row.innerHTML = `<label>Date<input data-day="date" type="date" value="${esc(day.date)}" required></label><label>Début<input data-day="start" type="time" value="${esc(day.start || '09:00')}" required></label><label>Fin<input data-day="end" type="time" value="${esc(day.end || '17:00')}" required></label><button type="button" aria-label="Supprimer la journée">×</button><label class="retake-wide">Programme / module<input data-day="topic" maxlength="300" value="${esc(day.topic || 'Révision et préparation à l’examen')}"></label>`;
    row.querySelector('button').onclick = () => {row.remove();calc();}; days.append(row);calc();
  }
  function defaults() {
    const current = state.defaults.find(d => d.kind === field('kind').value);
    if (!current) return;
    field('target_session').innerHTML = '<option value="">Choisir une session d’accueil</option>' + current.sessions.map(s => `<option value="${esc(s.id)}">${esc(s.name)} · ${esc(s.date_label)}</option>`).join('');
    if (current.sessions.length) {field('target_session').value = current.sessions[0].id;field('exam_date').value = current.sessions[0].exam_date;}
    else field('exam_date').value = '';
    field('exam_price').value = current.prices.exam_price;field('day_price').value = current.prices.day_price;
    document.getElementById('retakeExamSource').textContent = current.prices.source + ' · ' + current.prices.exam_clause;
    document.getElementById('retakeDaySource').textContent = current.prices.source + ' · ' + current.prices.day_clause;
    document.getElementById('retakePriceNote').textContent = current.prices.note;
    calc();
  }
  function edit(record = null) {
    editing = record;form.reset();days.replaceChildren();form.hidden = false;
    field('kind').innerHTML = state.defaults.map(d => `<option value="${esc(d.kind)}">${esc(d.label)}</option>`).join('');
    if (record) field('kind').value = record.kind;
    defaults();field('location').value = state.location || '';
    if (record) {
      if (![...field('target_session').options].some(o => o.value === record.target_session)) field('target_session').add(new Option(record.target_name,record.target_session));
      for (const key of ['target_session','exam_date','exam_time','location','exam_price','day_price','notes']) field(key).value = record[key] || '';
      for (const key of ['exam_offered','days_offered','no_days']) field(key).checked = Boolean(record[key]);
      record.days.forEach(addDay);
    }
    calc();
  }
  function renderHistory() {
    history.innerHTML = state.records.map(r => `<article class="retake-record"><h3>${esc(r.kind)} · ${esc(r.exam_date_label)}</h3><span class="retake-status ${esc(r.status)}">${esc(r.label)}</span><p>${esc(r.target_name)}<br>${esc(r.location)}<br><strong>${esc(r.total)} TTC</strong>${r.email_sent ? ' · Documents envoyés par e-mail' : ''}</p>${r.days.length ? '<p>'+r.days.map(d=>`${esc(d.date.split('-').reverse().join('/'))} · ${esc(d.start)}–${esc(d.end)} · ${esc(d.topic)}`).join('<br>')+'</p>' : '<p>Aucune journée de cours supplémentaire.</p>'}${r.error ? `<p class="retake-error" role="alert">${esc(r.error)}</p>` : ''}<div class="retake-links"><a class="btn btn-outline" target="_blank" rel="noopener" href="${esc(r.convention_url)}">Convention${r.signed_at?' signée':''}</a>${r.invoice_url ? `<a class="btn btn-outline" target="_blank" rel="noopener" href="${esc(r.invoice_url)}">Facture Qonto</a>`:''}${r.payment_url ? `<a class="btn btn-outline" target="_blank" rel="noopener" href="${esc(r.payment_url)}">Lien de paiement</a>`:''}${state.read_only?'':r.status==='draft'?`<button type="button" class="btn btn-outline" data-edit="${esc(r.id)}">Modifier</button><button type="button" class="btn btn-primary" data-action="send" data-id="${esc(r.id)}">Envoyer en signature</button><button type="button" class="btn btn-outline" data-action="cancel" data-id="${esc(r.id)}">Annuler le brouillon</button>`:r.status!=='cancelled'?`<button type="button" class="btn btn-outline" data-action="refresh" data-id="${esc(r.id)}">Actualiser le suivi</button>`:''}</div></article>`).join('');
    document.getElementById('retakeNew').hidden = state.read_only || !state.records.length;
  }
  async function load(initial = false) {
    const result = await api(dialog.dataset.api + (!initial && state ? '?status=1' : ''));
    state = {...state,...result};renderHistory();
    if (initial) {form.hidden = state.records.length > 0 || state.read_only;if (!form.hidden) edit();}
    clearTimeout(timer);
    if (dialog.open && state.records.some(r=>['queued','signed','signing','payment'].includes(r.status))) timer = setTimeout(()=>load().catch(e=>say(e.message,true)),5000);
  }
  open.onclick = async () => {dialog.showModal();say('Chargement du rattrapage…');try {await load(true);say();} catch(e){say(e.message,true);}};
  dialog.querySelector('[data-retake-close]').onclick = () => dialog.close();
  dialog.addEventListener('close',()=>clearTimeout(timer));
  form.addEventListener('input',calc);
  field('kind').addEventListener('change',defaults);
  field('target_session').addEventListener('change',()=>{const current=state.defaults.find(d=>d.kind===field('kind').value);const chosen=current?.sessions.find(s=>s.id===field('target_session').value);if(chosen?.exam_date)field('exam_date').value=chosen.exam_date;});
  field('no_days').addEventListener('change',()=>{if(!field('no_days').checked&&!days.children.length)addDay();calc();});
  document.getElementById('retakeAddDay').onclick = () => addDay();
  document.getElementById('retakeNew').onclick = () => edit();
  form.onsubmit = async event => {
    event.preventDefault();if(busy)return;busy=true;say('Préparation de votre convention…');
    const payload={id:editing?.id,revision:editing?.revision};
    for(const key of ['kind','target_session','exam_date','exam_time','location','exam_price','day_price','notes'])payload[key]=field(key).value;
    for(const key of ['exam_offered','days_offered','no_days'])payload[key]=field(key).checked;
    payload.days=[...days.children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-day]')].map(input=>[input.dataset.day,input.value])));
    try{await api(dialog.dataset.api,payload);form.hidden=true;editing=null;await load();say('Convention préparée. Vous pouvez la consulter puis l’envoyer en signature.');}catch(e){say(e.message,true);}finally{busy=false;}
  };
  history.onclick=async event=>{
    const editButton=event.target.closest('[data-edit]');if(editButton){edit(state.records.find(r=>r.id===editButton.dataset.edit));return;}
    const button=event.target.closest('[data-action]');if(!button||busy)return;
    const record=state.records.find(r=>r.id===button.dataset.id);busy=true;button.disabled=true;
    say(button.dataset.action==='send'?'Convention en cours de transmission pour signature…':'Mise à jour du suivi…');
    try{await api(`/api/rattrapages/${encodeURIComponent(record.id)}/${button.dataset.action}`,{revision:record.revision});form.hidden=true;await load();say(button.dataset.action==='send'?'Transmission lancée. Le suivi se met à jour automatiquement.':'Demande enregistrée. Le suivi se met à jour automatiquement.');}catch(e){say(e.message,true);}finally{busy=false;button.disabled=false;}
  };
  if(location.hash==='#rattrapage')open.click();
})();
