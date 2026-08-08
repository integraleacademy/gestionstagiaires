(() => {
  const modal = document.querySelector('#wedof-manual-modal');
  if (!modal) return;
  const form = document.querySelector('#wedof-manual-form');
  const sessionSearch = document.querySelector('#wedof-session-search');
  const traineeSearch = document.querySelector('#wedof-trainee-search');
  const sessionResults = document.querySelector('#wedof-session-results');
  const traineeResults = document.querySelector('#wedof-trainee-results');
  let folder = {}, chosenSession = null, chosenTrainee = null, currentRow = null, timer;
  const esc = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fr = value => value ? value.slice(0, 10).split('-').reverse().join('/') : '—';
  async function json(url) { const response = await fetch(url, {headers:{Accept:'application/json'}}); if (!response.ok) throw new Error('Recherche indisponible.'); return response.json(); }
  function dateWarnings() {
    const mismatch = !!chosenSession && (chosenSession.date_start !== folder.dateStart || chosenSession.date_end !== folder.dateEnd);
    document.querySelector('#wedof-date-warning').hidden = !mismatch;
    const label = document.querySelector('#wedof-date-confirm'); label.hidden = !mismatch; label.querySelector('input').required = mismatch;
    document.querySelector('#wedof-archive-warning').hidden = !(chosenSession && chosenSession.archived);
    const comparison=document.querySelector('#wedof-date-comparison'); comparison.hidden=!chosenSession;
    document.querySelector('#wedof-remote-dates').textContent=`du ${fr(folder.dateStart)} au ${fr(folder.dateEnd)}`;
    document.querySelector('#wedof-local-dates').textContent=chosenSession?`du ${fr(chosenSession.date_start)} au ${fr(chosenSession.date_end)}`:'—';
  }
  async function sessions(q='') {
    const payload = await json(`/admin/wedof/matching/manual/sessions?q=${encodeURIComponent(q)}`);
    sessionResults.innerHTML = '';
    payload.items.forEach(item => { const button=document.createElement('button'); button.type='button'; button.className='wedof-choice'; button.innerHTML=`<strong>${esc(item.name)}</strong> — du ${fr(item.date_start)} au ${fr(item.date_end)}${item.archived?' — <strong>Session archivée</strong>':''}`; button.onclick=()=>selectSession(item, button); sessionResults.append(button); });
    return payload.items;
  }
  async function selectSession(item, button) {
    chosenSession=item; chosenTrainee=null; form.session_id.value=item.id; form.trainee_id.value=''; traineeSearch.disabled=false; traineeResults.innerHTML='';
    sessionResults.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===button)); document.querySelector('#wedof-confirm-session').textContent=item.name; document.querySelector('#wedof-confirm-trainee').textContent='—'; dateWarnings(); await trainees('');
  }
  async function trainees(q='') {
    if (!chosenSession) return; const payload=await json(`/admin/wedof/matching/manual/trainees?session_id=${encodeURIComponent(chosenSession.id)}&q=${encodeURIComponent(q)}`); traineeResults.innerHTML='';
    payload.items.forEach(item=>{const button=document.createElement('button');button.type='button';button.className='wedof-choice';button.textContent=`${item.last_name} ${item.first_name} — ${item.email || '—'} — ${item.phone || '—'}`;button.onclick=()=>{chosenTrainee=item;form.trainee_id.value=item.id;traineeResults.querySelectorAll('button').forEach(x=>x.classList.toggle('selected',x===button));document.querySelector('#wedof-confirm-trainee').textContent=`${item.first_name} ${item.last_name}`;};traineeResults.append(button);});
  }
  document.querySelectorAll('[data-manual-link]').forEach(button=>button.addEventListener('click',async()=>{
    form.reset(); chosenSession=chosenTrainee=null; currentRow=button.closest('tr'); folder={externalId:button.dataset.externalId,state:button.dataset.state,identity:button.dataset.identity,email:button.dataset.email,phone:button.dataset.phone,dateStart:button.dataset.dateStart,dateEnd:button.dataset.dateEnd};form.external_id.value=folder.externalId;traineeSearch.disabled=true;traineeResults.innerHTML='';document.querySelector('#wedof-folder-summary').innerHTML=`<strong>Numéro WEDOF :</strong> ${esc(folder.externalId)}<br><strong>État :</strong> ${esc(folder.state)}<br><strong>Identité :</strong> ${esc(folder.identity)}<br><strong>Email :</strong> ${esc(folder.email)||'—'}<br><strong>Téléphone :</strong> ${esc(folder.phone)||'—'}<br><strong>Dates de formation :</strong> ${fr(folder.dateStart)} — ${fr(folder.dateEnd)}`;document.querySelector('#wedof-confirm-folder').textContent=`${folder.externalId} — ${folder.identity}`;document.querySelector('#wedof-confirm-session').textContent='—';document.querySelector('#wedof-confirm-trainee').textContent='—';dateWarnings();modal.showModal();const items=await sessions('');const preset=items.find(x=>x.id===button.dataset.sessionId);if(preset){const buttons=[...sessionResults.children];selectSession(preset,buttons[items.indexOf(preset)]);}
  }));
  sessionSearch.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>sessions(sessionSearch.value),180)}); traineeSearch.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>trainees(traineeSearch.value),180)});document.querySelector('#wedof-modal-cancel').onclick=()=>modal.close();
  form.addEventListener('submit',async event=>{if(!chosenSession||!chosenTrainee){event.preventDefault();alert('Sélectionnez une session et un stagiaire.');return;}event.preventDefault();const response=await fetch(form.action,{method:'POST',headers:{Accept:'application/json','X-Requested-With':'XMLHttpRequest'},body:new FormData(form)});const payload=await response.json();if(!response.ok){alert(payload.message);return;}currentRow.querySelector('[data-local-session]').textContent=payload.session;currentRow.querySelector('[data-local-trainee]').textContent=payload.trainee;currentRow.querySelector('[data-local-association]').textContent='Associée manuellement';currentRow.querySelector('[data-manual-link]').remove();document.querySelector('#wedof-links-count').textContent=payload.count;const feedback=document.querySelector('#wedof-manual-feedback');feedback.hidden=false;feedback.className='card';feedback.style.background='#dcfce7';feedback.textContent=payload.message;modal.close();});
})();
