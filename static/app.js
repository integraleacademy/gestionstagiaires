const qs = (sel, root=document) => root.querySelector(sel);
const qsa = (sel, root=document) => Array.from(root.querySelectorAll(sel));

function toast(msg, ok=true) {
  const t = qs("#toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.remove("show", "ok", "bad");
  t.classList.add("show", ok ? "ok" : "bad");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function openModal(id) {
  const el = qs(`#${id}`);
  if (!el) return;
  if (typeof window.closeAllPanels === "function") window.closeAllPanels({ exceptId: id });
  el.setAttribute("aria-hidden", "false");
  el.classList.add("open", "show");
  el.style.display = (el.classList.contains("trainee-search-drawer") || el.classList.contains("docs-to-control-drawer")) ? "block" : "flex";
  el.style.pointerEvents = "auto";
  document.body.style.overflow = "hidden";
}
function closeModal(id) {
  const el = qs(`#${id}`);
  if (!el) return;
  el.setAttribute("aria-hidden", "true");
  el.classList.remove("open", "show", "active", "is-open");
  el.style.display = "none";
  el.style.pointerEvents = "none";
  if (typeof window.closeAllPanels === "function") window.closeAllPanels();
  else document.body.style.overflow = "";
}

function withAdminKey(url) {
  const qsKey = window.__ADMIN_KEY_QS || "";
  if (!qsKey) return url;
  return url.includes("?") ? `${url}&${qsKey}` : `${url}?${qsKey}`;
}

async function api(url, method="GET", body=null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(withAdminKey(url), opts);
  const data = await res.json().catch(()=> ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `Erreur HTTP ${res.status}`);
  }
  return data;
}

/* ------------------------
   SESSIONS PAGE
------------------------- */
(function initSessions(){
  if (document.body.classList.contains("endpoint-admin-sessions")) return;
  const btnOpen = qs("#btnOpenCreateSession");
  const modalId = "createSessionModal";
  if (btnOpen) {
    btnOpen.addEventListener("click", () => openModal(modalId));
  }
  qsa("[data-close-modal]").forEach(b => {
    b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal")));
  });

  const btnCreate = qs("#btnCreateSession");
  if (btnCreate) {
    btnCreate.addEventListener("click", async () => {
      const payload = {
        name: (qs("#sessionName")?.value || "").trim(),
        training_type: (qs("#sessionType")?.value || "").trim(),
        date_start: qs("#dateStart")?.value,
        date_end: qs("#dateEnd")?.value,
        exam_date: qs("#examDate")?.value,
        exam_theory_date: qs("#examTheoryDate")?.value,
        exam_practice_date: qs("#examPracticeDate")?.value,
        practice_training_date: qs("#practiceTrainingDate")?.value,
        aps_in_person_start: qs("#apsInPersonStart")?.value,
        aps_elearning_enabled: !!qs("#apsElearningEnabled")?.checked,
        dirigeant_remote_start: qs("#dirigeantRemoteStart")?.value,
        dirigeant_remote_end: qs("#dirigeantRemoteEnd")?.value,
        dirigeant_in_person_start: qs("#dirigeantInPersonStart")?.value,
        dirigeant_in_person_end: qs("#dirigeantInPersonEnd")?.value
      };
      try {
        await api("/api/sessions/create", "POST", payload);
        toast("Session créée ✅");
        closeModal(modalId);
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  }

  qsa("[data-delete-session]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-delete-session");
      if (!(await AppModal.confirm({type:"danger", title:"Supprimer cette session", message:"Supprimer cette session ? (stagiaires inclus). Cette action est définitive.", primaryText:"Supprimer définitivement"}))) return;
      try {
        await api(`/admin/sessions/${id}/delete`, "POST");
        toast("Session supprimée");
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  });
})();

/* ------------------------
   TRAINEES PAGE
------------------------- */
(function initTrainees(){
  const table = qs("#traineesTable");
  if (!table) return;

  const sessionId = table.getAttribute("data-session-id");
  const modalId = "createTraineeModal";

  const btnPrintTrainees = qs("#btnPrintTrainees");
  if (btnPrintTrainees) {
    btnPrintTrainees.addEventListener("click", () => {
      window.print();
    });
  }

  const btnOpen = qs("#btnOpenCreateTrainee");
  if (btnOpen) btnOpen.addEventListener("click", () => openModal(modalId));
  qsa("[data-close-modal]").forEach(b => b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal"))));

  const btnCreate = qs("#btnCreateTrainee");
  if (btnCreate) {
    btnCreate.addEventListener("click", async () => {
      const payload = {
        session_id: sessionId,
        last_name: (qs("#tLastName")?.value || "").trim(),
        first_name: (qs("#tFirstName")?.value || "").trim(),
        email: (qs("#tEmail")?.value || "").trim(),
        phone: (qs("#tPhone")?.value || "").trim()
      };
      try {
        await api("/api/trainees/add", "POST", payload);
        toast("Stagiaire ajouté + message envoyé ✅");
        closeModal(modalId);
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  }

  // Autosave (selects + input commentaire)
  let saveTimer = null;
  function scheduleSave(fn) {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(fn, 250);
  }

  async function saveField(row, field, value) {
    const traineeId = row.getAttribute("data-trainee-id");
    return await api("/api/trainees/update", "POST", { trainee_id: traineeId, field, value });
  }

  function applyBadges(row) {
    // Convention
    const conv = qs(".sel-convention", row)?.value;
    const test = qs(".sel-testfr", row)?.value;
    const dos = qs(".sel-dossier", row)?.value;
    const fin = qs(".sel-finance", row)?.value;

    const badge = (kind, val) => {
      const el = qsa(`[data-badge="${kind}"]`, row)[0];
      if (!el) return;
      el.className = "badge " + statusClass(kind, val);
    };

    badge("convention_status", conv);
    badge("test_fr_status", test);
    badge("dossier_status", dos);
    badge("financement_status", fin);
  }

  function statusClass(kind, val) {
    // mapping couleurs
    const map = {
      convention_status: { soon:"red", signing:"yellow", signed:"green" },
      test_fr_status: { soon:"red", in_progress:"yellow", validated:"green", relance:"orange" },
      dossier_status: { complete:"green", incomplete:"red" },
      financement_status: { soon:"red", in_review:"orange", validated:"green" }
    };
    return (map[kind] && map[kind][val]) ? map[kind][val] : "neutral";
  }

  qsa("tbody tr", table).forEach(row => {
    applyBadges(row);

    qsa("select.status", row).forEach(sel => {
      sel.addEventListener("change", () => {
        const field = sel.getAttribute("data-field");
        const value = sel.value;
        scheduleSave(async () => {
          try {
            const data = await saveField(row, field, value);
            if (data?.dossier_status) {
              const dossierSel = qs('select[data-field="dossier_status"]', row);
              if (dossierSel) dossierSel.value = data.dossier_status;
            }
            applyBadges(row);
            toast("Enregistré ✅");
          } catch (e) {
            toast(e.message, false);
          }
        });
      });
    });

    const comment = qs("input.comment", row);
    if (comment) {
      comment.addEventListener("input", () => {
        scheduleSave(async () => {
          try {
            await saveField(row, "comment", comment.value);
            // surlignage + warning
            if ((comment.value || "").trim().length > 0) row.classList.add("row-warning");
            else row.classList.remove("row-warning");
            toast("Enregistré ✅");
          } catch (e) {
            toast(e.message, false);
          }
        });
      });
    }

    const forceDossier = qs("input.force-dossier", row);
    if (forceDossier) {
      const dossierSel = qs('select[data-field="dossier_status"]', row);
      if (dossierSel) {
        dossierSel.disabled = forceDossier.checked;
        if (forceDossier.checked) dossierSel.value = "complete";
      }
      forceDossier.addEventListener("change", () => {
        scheduleSave(async () => {
          try {
            const data = await saveField(row, "force_dossier_complete", forceDossier.checked);
            if (dossierSel) {
              dossierSel.disabled = forceDossier.checked;
              if (data?.dossier_status) {
                dossierSel.value = data.dossier_status;
              } else if (forceDossier.checked) {
                dossierSel.value = "complete";
              }
            }
            applyBadges(row);
            toast("Enregistré ✅");
          } catch (e) {
            toast(e.message, false);
          }
        });
      });
    }

    // Refresh CNAPS / hosting
    const refresh = qs("[data-refresh]", row);
    if (refresh) {
      refresh.addEventListener("click", async () => {
        const traineeId = row.getAttribute("data-trainee-id");
        try {
          const data = await api("/api/trainees/refresh_external", "POST", { trainee_id: traineeId });
          const cnapsEl = qs("[data-cnaps]", row);
          if (cnapsEl) cnapsEl.textContent = data.cnaps_status || "unknown";
          const hostingEl = qs("[data-hosting]", row);
          if (hostingEl && data.hosting_status) {
            hostingEl.textContent = (data.hosting_status === "reserved") ? "réservé" : "inconnu";
          }
          toast("Statuts mis à jour ✅");
        } catch (e) {
          toast(e.message, false);
        }
      });
    }
  });
})();
(function(){
  const root=document.getElementById('commandSearch');
  if(!root)return;
  const input=root.querySelector('#commandSearchInput');
  const panel=root.querySelector('#commandSearchPanel');
  const results=root.querySelector('#commandSearchResults');
  const status=root.querySelector('#commandSearchStatus');
  let functions=[];
  try{functions=JSON.parse(root.querySelector('#commandSearchFunctions').textContent||'[]');}catch(_error){}
  let timer=0,sequence=0,activeIndex=-1,currentItems=[];
  const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const open=()=>{panel.hidden=false;input.setAttribute('aria-expanded','true');render(input.value);};
  const close=()=>{panel.hidden=true;input.setAttribute('aria-expanded','false');activeIndex=-1;};
  function functionMatches(query){
    const needle=normalize(query);
    return functions.filter(item=>!needle||normalize(`${item.label} ${item.description} ${item.keywords}`).includes(needle)).slice(0,8)
      .map(item=>({...item,type:'Fonction'}));
  }
  function draw(items,query,loading=false){
    currentItems=items;activeIndex=-1;
    status.textContent=loading?'Recherche en cours…':(query?`${items.length} résultat${items.length>1?'s':''}`:'Suggestions');
    if(!items.length){results.innerHTML='<div class="command-search__empty"><strong>Aucun résultat</strong><span>Essayez un nom, une formation ou un outil.</span></div>';return;}
    let lastType='';
    results.innerHTML=items.map((item,index)=>{
      const heading=item.type!==lastType?`<div class="command-search__group">${escapeHtml(item.type)}</div>`:'';lastType=item.type;
      const actions=item.type==='Stagiaires'?`<span class="command-search__actions"><a href="${escapeHtml(item.href)}">Fiche</a><a href="${escapeHtml(item.publicUrl)}" target="_blank" rel="noopener">Espace</a><button type="button" data-summary-url="${escapeHtml(item.summaryUrl)}">Synthèse</button></span>`:`<span class="command-search__type">${escapeHtml(item.type)}</span><span class="command-search__arrow">↗</span>`;
      return `${heading}<div class="command-search__result" role="option" data-command-index="${index}" data-command-href="${escapeHtml(item.href)}"><span class="command-search__icon">${escapeHtml(item.icon)}</span><span class="command-search__copy"><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.description)}</small></span>${actions}</div>`;
    }).join('');
  }
  async function remoteSearch(query,id){
    try{
      const [traineesResponse,sessionsResponse]=await Promise.all([
        fetch(`/api/trainees_search?q=${encodeURIComponent(query)}`,{headers:{Accept:'application/json'}}),
        fetch(`/api/sessions_search?q=${encodeURIComponent(query)}`,{headers:{Accept:'application/json'}})
      ]);
      const [trainees,sessions]=await Promise.all([traineesResponse.json(),sessionsResponse.json()]);
      if(id!==sequence)return;
      const people=(trainees.items||[]).slice(0,6).map(item=>({type:'Stagiaires',icon:'●',label:`${item.first_name||''} ${item.last_name||''}`.trim(),description:`${item.session_name||'Session'}${item.training_type?' · '+item.training_type:''}`,href:item.admin_url,publicUrl:item.public_url,summaryUrl:item.summary_api_url}));
      const courses=(sessions.items||[]).slice(0,6).map(item=>({type:'Sessions',icon:'□',label:item.session_name||item.training_type||'Session',description:`${item.training_type||'Formation'}${item.date_range?' · '+item.date_range:''}`,href:item.admin_url}));
      draw([...functionMatches(query),...people,...courses],query);
    }catch(_error){if(id===sequence){draw(functionMatches(query),query);status.textContent='Résultats des outils uniquement';}}
  }
  function render(value){
    const query=value.trim();window.clearTimeout(timer);
    if(query.length<2){draw(functionMatches(query),query);return;}
    const id=++sequence;draw(functionMatches(query),query,true);
    timer=window.setTimeout(()=>remoteSearch(query,id),180);
  }
  function select(index){
    const options=[...results.querySelectorAll('[data-command-index]')];if(!options.length)return;
    activeIndex=(index+options.length)%options.length;
    options.forEach((option,i)=>option.classList.toggle('is-active',i===activeIndex));
    options[activeIndex].scrollIntoView({block:'nearest'});
  }
  input.addEventListener('focus',open);
  input.addEventListener('input',()=>{if(panel.hidden)open();else render(input.value);});
  input.addEventListener('keydown',event=>{
    if(event.key==='ArrowDown'){event.preventDefault();select(activeIndex+1);}
    else if(event.key==='ArrowUp'){event.preventDefault();select(activeIndex-1);}
    else if(event.key==='Enter'&&activeIndex>=0){event.preventDefault();const option=results.querySelector(`[data-command-index="${activeIndex}"]`);if(option?.dataset.commandHref)window.location.href=option.dataset.commandHref;}
    else if(event.key==='Escape'){event.preventDefault();close();input.blur();}
  });
  document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();input.focus();open();}});
  document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))close();});
  results.addEventListener('click',async event=>{
    const button=event.target.closest('[data-summary-url]');
    if(!button){const option=event.target.closest('[data-command-href]');if(option&&!event.target.closest('a,button'))window.location.href=option.dataset.commandHref;return;}
    event.preventDefault();event.stopPropagation();
    button.disabled=true;button.textContent='Chargement…';
    try{const response=await fetch(button.dataset.summaryUrl,{headers:{Accept:'application/json'}});const payload=await response.json();if(!response.ok)throw new Error();showTraineeSummary(payload);close();}
    catch(_error){window.AppModal?.alert('Impossible de charger la synthèse du stagiaire.',{type:'error'});}
    finally{button.disabled=false;button.textContent='Synthèse';}
  });
  function showTraineeSummary(payload){
    let modal=document.getElementById('traineeSummaryModal');
    if(!modal){modal=document.createElement('div');modal.id='traineeSummaryModal';modal.className='trainee-summary-modal';document.body.appendChild(modal);}
    const person=payload.trainee||{},progress=payload.progress||{};
    modal.innerHTML=`<div class="trainee-summary__backdrop" data-summary-close></div><section class="trainee-summary__card" role="dialog" aria-modal="true" aria-labelledby="traineeSummaryTitle"><header><div><span class="trainee-summary__kicker">Vue à 360°</span><h2 id="traineeSummaryTitle">${escapeHtml(`${person.first_name||''} ${person.last_name||''}`)}</h2><p>${escapeHtml(person.session_name||'Session')} · ${escapeHtml(person.training_type||'Formation')}</p></div><button type="button" data-summary-close aria-label="Fermer">×</button></header><div class="trainee-summary__score"><div class="trainee-summary__ring" style="--progress:${Number(progress.percent)||0}"><strong>${Number(progress.percent)||0}%</strong></div><div><strong>${progress.completed||0} étapes validées sur ${progress.total||0}</strong><span>${progress.percent===100?'Le dossier est prêt.':'Les points restants sont visibles ci-dessous.'}</span></div></div><div class="trainee-summary__grid">${(payload.statuses||[]).map(item=>`<article class="is-${escapeHtml(item.state)}"><span class="trainee-summary__check">${item.state==='complete'?'✓':item.state==='neutral'?'—':'!'}</span><div><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.detail)}</small></div></article>`).join('')}</div><footer><a href="${escapeHtml(payload.public_url)}" target="_blank" rel="noopener">Ouvrir l’espace stagiaire</a><a class="is-primary" href="${escapeHtml(payload.admin_url)}">Ouvrir la fiche</a></footer></section>`;
    modal.classList.add('is-visible');document.body.classList.add('trainee-summary-open');
    modal.querySelectorAll('[data-summary-close]').forEach(el=>el.addEventListener('click',()=>{modal.classList.remove('is-visible');document.body.classList.remove('trainee-summary-open');}));
  }
})();
(function(){
  if(window.AppModal) return;
  const tones={danger:{icon:'🗑️',k:'Action sensible'},success:{icon:'✓',k:'Succès'},info:{icon:'i',k:'Information'},warning:{icon:'!',k:'Attention'},loading:{icon:'⏳',k:'Traitement'}};
  function ensure(){let r=document.getElementById('appModalRoot');if(r)return r;r=document.createElement('div');r.id='appModalRoot';r.innerHTML=`<div class="app-modal-backdrop" role="presentation"><section class="app-modal-card" role="dialog" aria-modal="true" aria-labelledby="appModalTitle"><button type="button" class="app-modal-x" aria-label="Fermer">×</button><div class="app-modal-content"><div class="app-modal-icon" aria-hidden="true"></div><div class="app-modal-copy"><div class="app-modal-kicker"></div><h2 id="appModalTitle"></h2><p class="app-modal-message"></p><div class="app-modal-extra"></div></div></div><div class="app-modal-actions"><button type="button" class="app-modal-btn app-modal-secondary"></button><button type="button" class="app-modal-btn app-modal-tertiary"></button><button type="button" class="app-modal-btn app-modal-primary"></button></div></section></div>`;document.body.appendChild(r);return r;}
  function show(opts={}){return new Promise(resolve=>{const tone=opts.type||'info',meta=tones[tone]||tones.info,root=ensure(),bd=root.firstElementChild,card=bd.querySelector('.app-modal-card'),x=bd.querySelector('.app-modal-x'),primary=bd.querySelector('.app-modal-primary'),secondary=bd.querySelector('.app-modal-secondary'),tertiary=bd.querySelector('.app-modal-tertiary'),extra=bd.querySelector('.app-modal-extra');card.className=`app-modal-card app-modal-${tone}`;bd.querySelector('.app-modal-icon').textContent=opts.icon||meta.icon;bd.querySelector('.app-modal-kicker').textContent=opts.kicker||meta.k;bd.querySelector('h2').textContent=opts.title||'Information';bd.querySelector('.app-modal-message').textContent=opts.message||'';extra.innerHTML=opts.html||'';primary.textContent=opts.primaryText||'Fermer';secondary.textContent=opts.secondaryText||'Annuler';tertiary.textContent=opts.tertiaryText||'';secondary.style.display=opts.showSecondary?'':'none';tertiary.style.display=opts.tertiaryText?'':'none';x.style.display=opts.closable===false?'none':'';function value(v){if(opts.input)return v===true?(extra.querySelector('.app-modal-input')?.value??''):null;return v;}function done(v){bd.classList.remove('is-visible');document.body.classList.remove('app-modal-open');setTimeout(()=>{primary.onclick=secondary.onclick=tertiary.onclick=x.onclick=bd.onclick=document.onkeydown=null;resolve(value(v));},120)}primary.onclick=()=>done(true);secondary.onclick=()=>done(false);tertiary.onclick=()=>done('tertiary');x.onclick=()=>done(false);bd.onclick=e=>{if(e.target===bd&&opts.closable!==false)done(false)};document.onkeydown=e=>{if(e.key==='Escape'&&opts.closable!==false)done(false);if(e.key==='Enter'&&opts.input)done(true)};requestAnimationFrame(()=>{bd.classList.add('is-visible');document.body.classList.add('app-modal-open');(extra.querySelector('.app-modal-input')||primary).focus();});});}
  function escapeHtml(v){return String(v??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  window.AppModal={show,alert:(message,options={})=>show({message,type:options.type||'info',title:options.title||((options.type==='error'||options.type==='danger')?'Action impossible':'Information'),primaryText:options.primaryText||'Fermer'}),confirm:(options={})=>show({type:options.type||'warning',title:options.title||'Confirmer l’action',message:options.message||'',primaryText:options.primaryText||'Confirmer',secondaryText:options.secondaryText||'Annuler',tertiaryText:options.tertiaryText||'',showSecondary:true,closable:true}),prompt:(message,defaultValue='',options={})=>show({type:options.type||'info',title:options.title||'Saisie requise',message,primaryText:options.primaryText||'Valider',secondaryText:options.secondaryText||'Annuler',showSecondary:true,closable:true,input:true,html:`<input class="app-modal-input" type="text" value="${escapeHtml(defaultValue)}" autocomplete="off">`})};
  document.addEventListener('submit',function(e){const form=e.target;if(form.dataset.appModalConfirmed==='1'){delete form.dataset.appModalConfirmed;return;}const attr=form.getAttribute('onsubmit')||'';const m=attr.match(/confirm\((['"])(.*?)\1\)/);if(!m)return;e.preventDefault();e.stopImmediatePropagation();AppModal.confirm({type:/supprimer|retirer|réinitialiser/i.test(m[2])?'danger':'warning',title:/supprimer/i.test(m[2])?'Suppression définitive':'Confirmation',message:m[2]+(/supprimer/i.test(m[2])?' Cette action est définitive.':''),primaryText:/supprimer/i.test(m[2])?'Supprimer définitivement':'Confirmer'}).then(ok=>{if(ok){form.dataset.appModalConfirmed='1';form.submit();}});},true);
})();
