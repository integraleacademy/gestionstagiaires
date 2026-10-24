(() => {
  'use strict';
  const root=document.getElementById('afc-documents'); if(!root)return;
  const $=id=>document.getElementById(id), dialog=$('afc-documents-dialog'), run=$('afc-doc-run');
  let plan=null, documentKind='', action='', busy=false, previewVersion=0;
  const statuses=new Map();
  const closeButtons=dialog.querySelectorAll('[data-afc-doc-close]');
  closeButtons.forEach(button=>button.addEventListener('click',()=>{if(!busy){previewVersion++;dialog.close();}}));
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();else previewVersion++;});
  window.addEventListener('beforeunload',event=>{if(busy){event.preventDefault();event.returnValue='';}});
  const node=(tag,text)=>{const el=document.createElement(tag);if(text)el.textContent=text;return el;};
  async function json(url, options={}) {
    const response=await fetch(url,{credentials:'same-origin',headers:{'Content-Type':'application/json','Accept':'application/json'},...options});
    if(response.redirected||response.status===401||response.status===403)throw Error('Votre session a expiré ou cet accès est indisponible. Reconnectez-vous puis rechargez la liste.');
    const value=await response.json();if(!response.ok)throw Error(value.error||'Le traitement est indisponible. Rechargez la liste.');return value;
  }
  root.querySelectorAll('[data-afc-document]').forEach(button=>button.addEventListener('click',async()=>{
    if(busy)return; const version=++previewVersion;documentKind=button.dataset.afcDocument;action=button.dataset.afcAction;plan=null;statuses.clear();
    const plural=documentKind==='convention'?'conventions':'convocations', send=action==='send';
    $('afc-doc-title').textContent=`${send?'Envoyer':'Générer'} les ${plural}`;
    $('afc-doc-description').textContent=send?(documentKind==='convention'?'Chaque stagiaire recevra son lien de signature de la convention par e-mail.':'Chaque stagiaire recevra sa convocation personnalisée en pièce jointe par e-mail.'):'Les PDF seront préparés et disponibles dans les fiches stagiaires. Aucun e-mail ne sera envoyé.';
    $('afc-doc-rows').replaceChildren();$('afc-doc-feedback').textContent='Préparation de la liste…';$('afc-doc-progress').hidden=true;run.hidden=false;run.disabled=true;run.textContent=send?'Envoyer':'Générer';dialog.showModal();
    try {
      const nextPlan=await json(`${root.dataset.previewUrl}?document=${documentKind}&action=${action}`);
      if(version!==previewVersion)return;
      plan=nextPlan;
      plan.rows.forEach(row=>{
        const tr=node('tr'), identity=node('td'), name=node('strong',row.name);identity.append(name,node('small',row.email||'E-mail non renseigné'));
        const preview=node('td'), link=node('a','Aperçu PDF');link.href=row.preview_url;link.target='_blank';link.rel='noopener';preview.append(link);
        const status=node('td',row.eligible?'Prête':row.reason);status.className=row.eligible?'':'is-skipped';tr.append(identity,preview,status);$('afc-doc-rows').append(tr);statuses.set(row.id,status);
      });
      const count=plan.rows.filter(row=>row.eligible).length;
      const excluded=plan.rows.length-count, label=count===1?documentKind:plural;
      $('afc-doc-feedback').textContent=`${count} ${label} à ${send?'envoyer':'générer'} · ${excluded} ${excluded===1?'exclue':'exclues'}`;
      run.textContent=`${send?'Envoyer':'Générer'} ${count} ${label}`;run.disabled=!count;
    } catch(error){if(version===previewVersion)$('afc-doc-feedback').textContent=error.message;}
  }));
  run.addEventListener('click',async()=>{
    if(busy||!plan)return;busy=true;run.disabled=true;closeButtons.forEach(b=>b.disabled=true);
    const rows=plan.rows.filter(r=>r.eligible), progress=$('afc-doc-progress');progress.hidden=false;progress.max=rows.length;progress.value=0;
    let succeeded=0, failed=0, skipped=0, stopped=false;
    for(const [index,row] of rows.entries()){
      const status=statuses.get(row.id);status.textContent='En cours…';
      $('afc-doc-feedback').textContent=`${index+1} / ${rows.length} · ${row.name} — gardez cette page ouverte.`;
      try{
        const result=await json(row.execute_url,{method:'POST',body:JSON.stringify({csrf:plan.csrf,document:documentKind,action,revision:row.revision,request_id:crypto.randomUUID()})});
        status.textContent=result.message||result.error||'Erreur';status.className=result.skipped?'is-skipped':result.ok?'is-success':'is-error';
        if(result.skipped)skipped++;else if(result.ok)succeeded++;else failed++;
      }catch(error){
        status.textContent='Résultat à vérifier. '+error.message;status.className='is-error';failed++;stopped=true;
        for(const pending of rows.slice(index+1))statuses.get(pending.id).textContent='Non traitée';
        break;
      }finally{progress.value=index+1;}
    }
    const completed=action==='send'?'envoyée':'générée';
    $('afc-doc-feedback').textContent=`${succeeded} ${completed}${succeeded===1?'':'s'} · ${failed} en erreur · ${skipped} ${skipped===1?'exclue':'exclues'}.${stopped?' Traitement interrompu : rechargez la liste pour vérifier les résultats et reprendre.':''}`;
    busy=false;run.hidden=true;closeButtons.forEach(b=>b.disabled=false);
  });
})();
