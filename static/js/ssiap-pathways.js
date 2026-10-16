(() => {
  const feedback = document.getElementById('ssiapFeedback');
  const message = text => { if (feedback) feedback.textContent = text; };
  async function post(url, payload) {
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || !result.ok) { const error = new Error(result.error || 'Enregistrement impossible.'); error.data = result; throw error; }
    return result;
  }
  const settings = document.getElementById('ssiapSettingsForm');
  if (settings) {
    const days = document.getElementById('ssiapSstDates');
    days.addEventListener('click', event => { if (event.target.closest('[data-remove-sst-date]')) event.target.closest('.ssiap-date-row').remove(); });
    document.getElementById('addSsiapSstDate').addEventListener('click', () => {
      if (days.children.length >= 10) { message('10 journées SST au maximum.'); return; }
      const row = document.createElement('div'); row.className = 'ssiap-date-row';
      row.innerHTML = '<input name="sst_date" type="date" aria-label="Journée SST"><button type="button" class="btn btn-outline" data-remove-sst-date>Retirer</button>';
      days.append(row);
    });
    settings.addEventListener('submit', async event => {
      event.preventDefault(); const button = event.submitter; button.disabled = true; message('Enregistrement…');
      const values = new FormData(settings);
      const config = Object.fromEntries(['ssiap_hours','sst_hours','ssiap_schedule','sst_schedule','ssiap_price','ssiap_sst_price'].map(key=>[key,values.get(key)]));
      config.sst_dates = values.getAll('sst_date').filter(Boolean);
      const payload = {date_start:values.get('date_start'),date_end:values.get('date_end'),exam_date:values.get('exam_date'),ssiap_pathways:config};
      try {
        try { await post(settings.dataset.url,payload); }
        catch(error) {
          if (error.data?.error !== 'wedof_date_change_confirmation_required') throw error;
          const confirmed = await (window.AppModal ? window.AppModal.confirm({title:'Dates liées à WEDOF',message:'Ces dossiers ont des dates WEDOF. Les liens seront conservés, mais les nouvelles dates locales peuvent différer. Enregistrer les dates SSIAP ?',primaryText:'Enregistrer',secondaryText:'Annuler'}) : window.confirm('Les nouvelles dates locales peuvent différer des dates WEDOF. Enregistrer ?'));
          if (!confirmed) { message('Modification des dates annulée.'); return; }
          await post(settings.dataset.url,{...payload,confirm_wedof_date_change:true});
        }
        window.location.assign(settings.dataset.return);
      } catch(error) { message(error.message); } finally { button.disabled = false; }
    });
  }
  const trainee = document.getElementById('ssiapTraineeForm');
  if (trainee) {
    const select = trainee.elements.ssiap_pathway;
    select.addEventListener('change', () => {
      document.getElementById('ssiapSstSummary').hidden = select.value !== 'ssiap_sst';
      const price = JSON.parse(trainee.dataset.prices)[select.value];
      if (price !== '' && price !== null) {
        trainee.elements.training_price.value = price;
        document.getElementById('ssiapPriceHint').textContent = 'Tarif proposé pour ce parcours. Vous pouvez l’ajuster avant d’enregistrer.';
      } else { document.getElementById('ssiapPriceHint').textContent = 'Aucun tarif défini pour ce parcours : vérifiez le montant du dossier.'; }
    });
    trainee.addEventListener('submit',async event=>{
      event.preventDefault(); const button=event.submitter; button.disabled=true; message('Enregistrement…');
      try { await post(trainee.dataset.url,Object.fromEntries(new FormData(trainee))); window.location.assign(trainee.dataset.return); }
      catch(error) { message(error.message); } finally { button.disabled=false; }
    });
  }
  const send=document.getElementById('ssiapBulkSend');
  if (send) {
    const rows=[...document.querySelectorAll('[data-ssiap-bulk-row]')];
    const filter=document.getElementById('ssiapBulkFilter');
    filter.addEventListener('change',()=>rows.forEach(row=>{row.hidden=filter.value!=='all'&&row.dataset.pathway!==filter.value;if(row.hidden)row.querySelector('input').checked=false;}));
    document.getElementById('ssiapSelectVisible').addEventListener('click',()=>rows.forEach(row=>{const box=row.querySelector('input');box.checked=!row.hidden&&!box.disabled;}));
    send.addEventListener('click',async()=>{
      const chosen=rows.filter(row=>!row.hidden&&row.querySelector('input').checked&&!row.querySelector('input').disabled);
      if(!chosen.length){message('Sélectionnez au moins un stagiaire.');return;}
      send.disabled=true;filter.disabled=true;document.getElementById('ssiapSelectVisible').disabled=true;
      let sent=0,failed=0,skipped=0;
      for (const [i,row] of chosen.entries()) {
        const state=row.querySelector('[data-send-status]'); const box=row.querySelector('input');box.disabled=true;
        message(`Envoi ${i+1} sur ${chosen.length}… Gardez cette page ouverte.`);state.textContent='Envoi en cours…';
        try {const result=await post(row.dataset.sendUrl,{skip_if_already_sent:true});if(result.skipped){skipped++;state.textContent='Déjà envoyée';}else{sent++;state.textContent='Envoyée';}box.checked=false;}
        catch(error){failed++;state.textContent=error.message;box.checked=false;}
      }
      message(`${sent} convocation(s) envoyée(s) · ${skipped} déjà envoyée(s) · ${failed} échec(s).${failed?' Consultez les statuts avant de relancer depuis les fiches.':''}`);
      send.disabled=false;filter.disabled=false;document.getElementById('ssiapSelectVisible').disabled=false;
    });
  }
})();
