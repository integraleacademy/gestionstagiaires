(() => {
  'use strict';
  const dialog = document.getElementById('ssiapExamDialog');
  if (!dialog) return;
  const base = dialog.dataset.url;
  const status = document.getElementById('ssiapExamStatus');
  const configForm = document.getElementById('ssiapExamConfig');
  const mailDialog = document.getElementById('ssiapExamMailDialog');
  const sendButton = document.getElementById('ssiapExamSend');
  const textButton = document.getElementById('ssiapExamMailTextToggle');
  const mailLoading = document.getElementById('ssiapExamMailLoading');
  const mailText = document.getElementById('ssiapExamMailText');
  let previewTimer, mailSendLocked = false;
  let data, preview, busy = false, configDirty = false;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const field = (label, key, value, type = 'text', extra = '') => `<label class="exam-field ${extra}">${esc(label)}<input name="${key}" type="${type}" value="${esc(value)}" ${type === 'number' ? 'min="0" max="20" step="0.01"' : ''}></label>`;
  const select = (label, key, value, options) => `<label class="exam-field">${esc(label)}<select name="${key}">${options.map(([v,t]) => `<option value="${v}"${v === value ? ' selected' : ''}>${t}</option>`).join('')}</select></label>`;
  const textarea = (label, key, value, limit) => `<label class="exam-field wide">${label}<textarea name="${key}" rows="3" maxlength="${limit}">${esc(value)}</textarea></label>`;
  function message(text, error = false) { status.textContent = text; status.className = 'exam-status ' + (error ? 'error' : 'success'); }
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', ...options, headers:{'Accept':'application/json', ...options.headers}});
    let result;
    try { result = await response.json(); } catch { throw new Error('La réponse est indisponible. Rechargez la page ou reconnectez-vous.'); }
    if (!response.ok || result.ok === false) throw new Error(result.error || 'Cette action n’a pas pu être effectuée.');
    return result;
  }
  const post = (url, payload) => api(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({csrf:data.csrf, ...payload})});
  function tab(name) {
    dialog.querySelectorAll('[data-exam-panel]').forEach(el => { el.hidden = el.dataset.examPanel !== name; });
    dialog.querySelectorAll('[data-exam-tab]').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.examTab === name)));
  }
  function chip(label, ok, review = false) { return `<span class="exam-chip ${ok && !review ? 'ok' : 'warn'}">${ok && !review ? '✓' : '!'} ${esc(label)}</span>`; }
  function renderCandidate(row) {
    const c = row.candidate;
    return `<article class="exam-card" data-candidate-id="${esc(row.id)}"><div class="exam-candidate-top"><div><div class="exam-candidate-name">${esc(row.first_name)} ${esc(row.last_name)}</div><span class="exam-muted">${c.included ? 'Présenté à l’examen' : 'Non présenté à l’examen'}</span></div><div class="exam-actions"><a class="btn btn-primary" data-dossier-link href="${esc(row.dossier_url)}" target="_blank" rel="noopener">Dossier examen PDF</a><a class="btn btn-outline" data-dossier-link href="${esc(row.dossier_url)}?download=1" target="_blank" rel="noopener">Télécharger</a></div></div>
      <div class="exam-chips">${row.documents.map(d => chip(d.label + (!d.available ? ' manquant' : d.review ? ' à vérifier' : ''), d.available, !!d.review)).join('')}${chip('Attestations signées et tamponnées', true)}</div>
      <div class="exam-actions"><a href="${esc(row.edit_url)}" target="_blank" rel="noopener">Ouvrir la fiche et les pièces</a><span class="exam-muted">·</span><a data-dossier-link href="${esc(row.pv_url)}?download=1" target="_blank" rel="noopener">Télécharger le PV individuel</a></div>
      <details class="exam-details"><summary>Présentation à l’examen</summary><form data-candidate-form="${esc(row.id)}"><fieldset ${data.read_only ? 'disabled' : ''}>
      <label class="exam-check"><input name="included" type="checkbox" ${c.included ? 'checked' : ''}>Présenter ce candidat à l’examen et l’inclure dans le PV collectif</label>
      <button type="submit" class="btn btn-primary exam-save">Enregistrer</button></fieldset></form></details></article>`;
  }
  const parisDate = value => value ? new Date(value).toLocaleString('fr-FR', {timeZone:'Europe/Paris',dateStyle:'short',timeStyle:'short'}) : '';
  function mailState(member, kind) {
    const recorded = data.config.jury.find(m => m.id === member.id);
    if (recorded && recorded.email.toLowerCase() !== (member.email || '').toLowerCase()) return {};
    return (data.mail_status || {})[member.id]?.[kind] || {};
  }
  function mailTracking(member) {
    return ['invitation', 'reminder'].map(kind => {
      const sent = mailState(member, kind);
      const label = kind === 'invitation' ? 'Invitation' : 'Rappel';
      const labels = {sent:'Envoyé',failed:'Échec de l’envoi',sending:'Envoi en cours ou à vérifier'};
      const tone = sent.status === 'sent' ? 'sent' : ['failed','sending'].includes(sent.status) ? 'failed' : 'pending';
      return `<div class="exam-mail-state ${tone}"><span class="exam-mail-state-label">${label}</span><strong>${esc(labels[sent.status] || 'Non envoyé')}</strong><span>${sent.at ? esc(parisDate(sent.at)) : 'Aucun envoi à cette adresse pour cet examen'}</span>${sent.last_sent_at && sent.status !== 'sent' ? `<small>Dernier envoi réussi : ${esc(parisDate(sent.last_sent_at))}</small>` : ''}</div>`;
    }).join('');
  }
  function renderMailOverview() {
    const members = data.config.jury;
    const sent = kind => members.filter(m => mailState(m, kind).last_sent_at).length;
    const area = document.getElementById('ssiapExamMailOverview');
    if (area) area.innerHTML = `<div class="exam-mail-overview"><div><span>INVITATIONS ENVOYÉES</span><strong>${sent('invitation')} <small>/ ${members.length}</small></strong></div><div><span>RAPPELS ENVOYÉS</span><strong>${sent('reminder')} <small>/ ${members.length}</small></strong></div><p>Suivi des envois pour cet examen<br><span>Dates et heures de Paris</span></p></div>`;
    configForm.querySelectorAll('[data-juror]').forEach(el => {
      const member = {id:el.dataset.juror, email:el.querySelector('[name=email]').value};
      el.querySelector('[data-juror-mail-status]').innerHTML = mailTracking(member);
    });
  }

  function juror(member) {
    return `<div class="exam-juror" data-juror="${esc(member.id)}"><div class="exam-juror-head"><strong>Membre du jury</strong><button type="button" class="exam-link-button" data-remove-juror>Retirer de la liste</button></div><div class="exam-grid three">${field('Prénom', 'first_name', member.first_name)}${field('Nom', 'last_name', member.last_name)}${select('Rôle', 'role', member.role, [['member','Membre du jury'],['president','Président du jury']])}${field('E-mail', 'email', member.email, 'email')}${field('Téléphone', 'phone', member.phone, 'tel')}${field('Entreprise ou structure', 'company', member.company)}</div><div class="exam-juror-mail-status" data-juror-mail-status>${mailTracking(member)}</div><div class="exam-actions exam-save"><button type="button" class="btn btn-outline" data-preview-kind="invitation">Prévisualiser l’invitation</button><button type="button" class="btn btn-outline" data-preview-kind="reminder">Prévisualiser le rappel</button></div></div>`;
  }
  function render() {
    const c = data.config;
    const count = data.candidates.filter(row => row.candidate.included).length;
    document.getElementById('ssiapExamCandidates').innerHTML = `<div class="exam-summary"><div><h3>${data.candidates.length} dossier${data.candidates.length > 1 ? 's' : ''} candidat${data.candidates.length > 1 ? 's' : ''}</h3><p class="exam-muted">Un PDF portrait par candidat, avec les 7 éléments du dossier.${data.excluded_count ? ` ${data.excluded_count} inscription(s) annulée(s) exclue(s).` : ''}</p></div><button type="button" class="btn btn-outline" data-refresh-exam>Actualiser les pièces</button></div>${!c.date || !c.time ? '<div class="exam-note" style="margin-bottom:15px">Renseignez la date et les horaires dans « Organisation et jury » pour compléter les documents et préparer les mails.</div>' : ''}${data.candidates.map(renderCandidate).join('') || '<p class="exam-empty">Aucun candidat actif dans cette session.</p>'}`;
    configForm.innerHTML = `<fieldset ${data.read_only ? 'disabled' : ''}><div class="exam-card"><h3>Organisation de l’examen</h3><div class="exam-grid three">${select('Niveau', 'level', c.level, [['SSIAP 1','SSIAP 1'],['SSIAP 2','SSIAP 2'],['SSIAP 3','SSIAP 3']])}${field('Date de l’examen SSIAP', 'date', c.date, 'date')}${field('Heure de début', 'time', c.time, 'time')}${field('Accueil du jury', 'arrival_time', c.arrival_time, 'time')}${field('Fin prévisionnelle', 'end_time', c.end_time, 'time')}${field('Lieu', 'location', c.location)}${field('Adresse de l’examen', 'address', c.address, 'text', 'wide')}${field('Agrément SSIAP', 'approval', c.approval, 'text', 'wide')}${textarea('Informations pratiques à inclure dans les mails', 'instructions', c.instructions, 3000)}${textarea('Outils pédagogiques et techniques (PV collectif)', 'equipment', c.equipment, 220)}</div></div>
      <div class="exam-card"><h3>Contact du centre</h3><div class="exam-grid three">${field('Nom du contact', 'contact_name', c.contact_name)}${field('E-mail', 'contact_email', c.contact_email, 'email')}${field('Téléphone', 'contact_phone', c.contact_phone, 'tel')}</div></div>
      <div class="exam-card"><h3>Jury et examinateurs</h3><p class="exam-muted">Les coordonnées sont enregistrées dans votre répertoire et réutilisables pour les autres examens. Les invitations et rappels restent propres à cette session.</p><div id="ssiapExamMailOverview"></div><div class="exam-directory"><label class="exam-field">Choisir un membre déjà enregistré<select id="ssiapExamDirectory"><option value="">Sélectionner dans le répertoire (${data.directory.length})</option>${data.directory.map(m => `<option value="${esc(m.id)}">${esc(m.first_name)} ${esc(m.last_name)}${m.company ? ' · ' + esc(m.company) : ''}${m.email ? ' · ' + esc(m.email) : ''}</option>`).join('')}</select></label><button type="button" data-reuse-juror class="btn btn-outline">Ajouter à cet examen</button></div><div id="ssiapExamJurors">${c.jury.map(juror).join('')}</div><button type="button" data-add-juror class="btn btn-outline">+ Ajouter un membre du jury</button></div><button type="submit" class="btn btn-primary">Enregistrer l’organisation et le jury</button></fieldset>`;
    configDirty = false;
    document.getElementById('ssiapExamCollective').innerHTML = `<div class="exam-card"><span class="exam-eyebrow" style="color:#008da8">PROCÈS-VERBAL DE LA SESSION</span><h3 style="margin-top:12px">PV collectif ${esc(c.level)}</h3><div class="exam-pv-count">${count}</div><p>candidat${count > 1 ? 's' : ''} présenté${count > 1 ? 's' : ''}</p><p class="exam-muted">La date, les candidats et les informations du jury sont préremplis dans le modèle fourni. Le tampon du centre et la signature de Clément VAILLANT sont apposés dans la zone de l’organisme de formation. Le jury complète les résultats et signe à la main. Le modèle contient 14 places ; une page identique est ajoutée si nécessaire. Les inscriptions annulées et les candidats non présentés sont exclus.</p><div class="exam-actions"><a class="btn btn-primary" href="${esc(data.collective_url)}" target="_blank" rel="noopener">Ouvrir le PV collectif</a><a class="btn btn-outline" href="${esc(data.collective_url)}?download=1" target="_blank" rel="noopener">Télécharger</a></div></div>`;
    renderHistory();
    renderMailOverview();
  }
  function renderHistory() {
    const labels = {sent:'Envoyé', failed:'Échec de l’envoi', sending:'Envoi en cours ou à vérifier'};
    document.getElementById('ssiapExamMailHistory').innerHTML = `<div class="exam-card" style="margin-top:22px"><h3>Historique des mails au jury</h3>${data.history.length ? data.history.map(entry => `<div class="exam-history"><strong>${esc(labels[entry.status] || entry.status)}</strong> · ${esc(entry.at ? new Date(entry.at).toLocaleString('fr-FR', {timeZone:'Europe/Paris'}) : '')}<br>${esc(entry.to)}<br>${esc(entry.subject)}</div>`).join('') : '<p class="exam-muted">Aucun mail envoyé pour cet examen.</p>'}</div>`;
  }
  async function load({keepDrafts = false, savedCandidate = ''} = {}) {
    const drafts = keepDrafts ? [...dialog.querySelectorAll('[data-candidate-form][data-dirty="true"]')]
      .filter(form => form.dataset.candidateForm !== savedCandidate)
      .map(form => ({id:form.dataset.candidateForm, values:Object.fromEntries(new FormData(form)),
        checks:Object.fromEntries(['included'].map(key => [key,form.elements[key].checked]))})) : [];
    data = await api(base); render();
    for (const draft of drafts) {
      const form = [...dialog.querySelectorAll('[data-candidate-form]')].find(f => f.dataset.candidateForm === draft.id);
      if (!form) continue;
      Object.entries(draft.values).forEach(([key,value]) => { if (form.elements[key] && form.elements[key].type !== 'checkbox') form.elements[key].value = value; });
      Object.entries(draft.checks).forEach(([key,value]) => { form.elements[key].checked = value; });
      form.dataset.dirty = 'true'; form.closest('details').open = true;
    }
  }
  function collectConfig() {
    const values = Object.fromEntries(new FormData(configForm));
    const jury = [...configForm.querySelectorAll('[data-juror]')].map(el => {
      const member = {id:el.dataset.juror};
      el.querySelectorAll('input,select').forEach(input => { member[input.name] = input.value; });
      return member;
    });
    const config = {jury};
    Object.keys(data.config).filter(k => k !== 'jury').forEach(k => { config[k] = values[k] ?? ''; });
    return config;
  }
  async function saveConfig() {
    if (!configForm.reportValidity()) throw new Error('Vérifiez les champs du jury et de l’organisation.');
    await post(base, {action:'config', revision:data.revision, config:collectConfig()});
    await load({keepDrafts:true});
  }
  async function action(work) {
    if (busy) return;
    busy = true;
    try { await work(); } catch (error) { message(error.message, true); } finally { busy = false; }
  }
  document.getElementById('btnSsiapExam').addEventListener('click', () => {
    dialog.showModal();
    message('Chargement…');
    action(async () => { await load(); message(''); });
  });
  dialog.addEventListener('input', event => {
    if (event.target.closest('#ssiapExamConfig') && event.target.id !== 'ssiapExamDirectory') configDirty = true;
    if (event.target.name === 'email' && event.target.closest('[data-juror]')) renderMailOverview();
    const form = event.target.closest('[data-candidate-form]');
    if (form) form.dataset.dirty = 'true';
  });
  dialog.addEventListener('click', event => {
    const target = event.target.closest('button,a');
    if (!target) return;
    if (target.hasAttribute('data-exam-close')) dialog.close();
    if (target.dataset.examTab) tab(target.dataset.examTab);
    if (target.hasAttribute('data-refresh-exam')) action(async () => {
      if (configDirty) throw new Error('Enregistrez l’organisation et le jury avant d’actualiser.');
      await load({keepDrafts:true}); message('Pièces actualisées.');
    });
    if (target.hasAttribute('data-reuse-juror')) {
      const id = document.getElementById('ssiapExamDirectory').value;
      const member = data.directory.find(m => m.id === id);
      if (!member) { message('Choisissez un membre dans le répertoire.', true); return; }
      const current = collectConfig().jury;
      if (current.some(m => m.id === member.id || (member.email && m.email.toLowerCase() === member.email.toLowerCase()))) {
        message('Ce membre figure déjà dans le jury de cet examen.', true); return;
      }
      const role = member.role === 'president' && !current.some(m => m.role === 'president') ? 'president' : 'member';
      document.getElementById('ssiapExamJurors').insertAdjacentHTML('beforeend', juror({...member, role}));
      configDirty = true; message('Membre ajouté. Enregistrez le jury pour cet examen.');
    }
    if (target.hasAttribute('data-add-juror')) { document.getElementById('ssiapExamJurors').insertAdjacentHTML('beforeend', juror({id:crypto.randomUUID(), role:'member'})); configDirty = true; }
    if (target.hasAttribute('data-remove-juror')) { target.closest('[data-juror]').remove(); configDirty = true; }
    if ((target.hasAttribute('data-dossier-link') || target.closest('#ssiapExamCollective')) && (configDirty || dialog.querySelector('[data-candidate-form][data-dirty="true"]'))) {
      event.preventDefault(); message('Enregistrez vos modifications avant de télécharger ou prévisualiser le dossier.', true);
    }
    if (target.dataset.previewKind) {
      const id = target.closest('[data-juror]').dataset.juror;
      const kind = target.dataset.previewKind;
      action(async () => {
        if (configDirty) await saveConfig();
        preview = await api(`${base}/jury/${encodeURIComponent(id)}/${kind}/preview`);
        document.getElementById('ssiapExamMailTo').textContent = preview.to;
        document.getElementById('ssiapExamMailSubject').textContent = preview.subject;
        showMailPreview(preview, kind);
        const sent = data.mail_status?.[id]?.[kind];
        document.getElementById('ssiapExamMailStatus').textContent = sent?.last_sent_at ? 'Dernier envoi : ' + parisDate(sent.last_sent_at) + '. Un nouvel envoi sera effectué si vous cliquez sur Envoyer.' : 'Ce mail n’a pas encore été envoyé.';
        message('');
      });
    }
  });
  dialog.addEventListener('submit', event => {
    event.preventDefault();
    const form = event.target;
    if (form === configForm) action(async () => { await saveConfig(); message('Organisation enregistrée. Les membres du jury sont disponibles dans votre répertoire.'); });
    if (form.dataset.candidateForm) action(async () => {
      if (configDirty) throw new Error('Enregistrez d’abord l’organisation et le jury. Vos modifications du candidat seront conservées.');
      const raw = Object.fromEntries(new FormData(form));
      ['included'].forEach(key => { raw[key] = form.elements[key].checked; });
      await post(base, {action:'candidate', revision:data.revision, trainee_id:form.dataset.candidateForm, candidate:raw});
      await load({keepDrafts:true, savedCandidate:form.dataset.candidateForm}); message('Candidat enregistré. Le dossier PDF utilise ces informations.');
    });
  });
  function showMailPreview(content, kind) {
    // A fresh frame resets scrolling and avoids reusing a hidden srcdoc document.
    clearTimeout(previewTimer);
    mailSendLocked = false;
    const frame = document.createElement('iframe');
    frame.id = 'ssiapExamMailFrame';
    frame.title = 'Contenu du mail au jury';
    frame.setAttribute('sandbox', '');
    frame.setAttribute('referrerpolicy', 'no-referrer');
    mailLoading.textContent = 'Chargement de l’aperçu…';
    mailLoading.hidden = false;
    mailText.textContent = content.text;
    mailText.hidden = true;
    textButton.textContent = 'Version texte';
    textButton.setAttribute('aria-pressed', 'false');
    sendButton.disabled = true;
    sendButton.textContent = 'Envoyer ce mail';
    document.getElementById('ssiapExamMailTitle').textContent = kind === 'reminder' ? 'Prévisualiser le rappel' : 'Prévisualiser l’invitation';
    frame.addEventListener('load', () => {
      if (frame !== document.getElementById('ssiapExamMailFrame') || preview !== content) return;
      clearTimeout(previewTimer);
      mailLoading.hidden = true;
      sendButton.disabled = data.read_only || mailSendLocked;
    }, {once:true});
    frame.srcdoc = content.html;
    document.getElementById('ssiapExamMailFrame').replaceWith(frame);
    if (!mailDialog.open) mailDialog.showModal();
    mailDialog.scrollTop = 0;
    previewTimer = setTimeout(() => {
      mailLoading.textContent = 'L’aperçu prend du temps à charger. Vous pouvez consulter la version texte.';
    }, 12000);
  }
  textButton.addEventListener('click', () => {
    const showText = mailText.hidden;
    mailText.hidden = !showText;
    document.getElementById('ssiapExamMailFrame').hidden = showText;
    textButton.textContent = showText ? 'Version mise en page' : 'Version texte';
    textButton.setAttribute('aria-pressed', String(showText));
    if (showText) {
      clearTimeout(previewTimer);
      mailLoading.hidden = true;
      mailText.scrollTop = 0;
      sendButton.disabled = data.read_only || !preview || mailSendLocked;
    }
  });
  mailDialog.querySelectorAll('[data-mail-close]').forEach(button => button.addEventListener('click', () => mailDialog.close()));
  mailDialog.addEventListener('close', () => {
    clearTimeout(previewTimer);
    preview = null;
    sendButton.disabled = true;
  });
  sendButton.addEventListener('click', async () => {
    if (!preview || sendButton.disabled) return;
    const prepared = preview;
    mailSendLocked = true;
    sendButton.disabled = true; sendButton.textContent = 'Envoi en cours…';
    const mailStatus = document.getElementById('ssiapExamMailStatus');
    try {
      await post(`${base}/mail/send`, {preview_token:prepared.preview_token});
      if (preview === prepared) {
        mailStatus.textContent = 'Mail envoyé à ' + prepared.to;
        sendButton.textContent = 'Mail envoyé';
      }
    } catch (error) {
      if (preview === prepared) {
        mailStatus.textContent = error.message; sendButton.textContent = 'Fermez puis prévisualisez à nouveau';
      }
    }
    try { data = await api(base); renderHistory(); renderMailOverview(); } catch { /* Preserve the confirmed delivery result. */ }
  });
})();
