(() => {
  'use strict';
  const form = document.getElementById('application-form');
  if (!form) return;
  const questions = [...form.querySelectorAll('.question')];
  const next = document.getElementById('next');
  const previous = document.getElementById('previous');
  const error = document.getElementById('form-error');
  const progress = document.getElementById('progress');
  const progressLabel = document.getElementById('progress-label');
  const blocked = document.getElementById('blocked');
  let index = 0, busy = false, completed = false;
  const yesNo = ['available_year','judicial_clear','license_b','mobile_departments','privacy_consent'];
  const labels = {last_name:'Nom', first_name:'Prénom', birth_date:'Date de naissance', email:'E-mail', phone:'Téléphone', city:'Ville', postcode:'Code postal', situation:'Situation actuelle', vehicle:'Véhicule', motivation:'Ta motivation', contact_slot:'Créneau de contact'};
  const messages = {
    age:'Malheureusement, tu ne peux pas candidater au parcours sécurité en alternance : ce parcours est réservé aux personnes de moins de 26 ans au moment de leur candidature.',
    availability:'Malheureusement, tu ne peux pas candidater à ce parcours sans être disponible sur toute l’année 2027, de janvier à décembre, pour les cours, les examens et l’entreprise.',
    judicial_clear:'Malheureusement, tu ne peux pas poursuivre cette candidature en ligne. Il faut d’abord faire le point sur ta situation et les démarches CNAPS avec notre équipe. Seul le CNAPS décide de la délivrance de ses autorisations.',
    license_b:'Le permis B en cours de validité est nécessaire pour ce parcours. Tu ne peux pas poursuivre cette candidature tant que cette condition n’est pas remplie.',
    mobile_departments:'Les déplacements en entreprise dans le Var et les Alpes-Maritimes sont nécessaires. Tu ne peux pas poursuivre cette candidature si tu ne peux pas organiser ces trajets.'
  };
  function value(field) { const data = new FormData(form); return data.get(field) || ''; }
  function show(i) {
    index = i;
    form.hidden = false; blocked.hidden = true;
    document.getElementById('progress-wrap').hidden = false;
    questions.forEach((q,j) => { q.hidden = j !== i; });
    error.textContent = '';
    previous.hidden = i === 0;
    next.innerHTML = i === questions.length - 1 ? 'Envoyer ma candidature <span aria-hidden="true">↗</span>' : 'Continuer <span aria-hidden="true">→</span>';
    progress.value = i + 1;
    progressLabel.textContent = `QUESTION ${i + 1} / ${questions.length}`;
    if (questions[i].dataset.field === 'review') renderReview();
    questions[i].querySelector('h1').focus({preventScroll:true});
    window.scrollTo({top:0,behavior:'instant'});
  }
  function block(reason) {
    form.hidden = true; blocked.hidden = false;
    document.getElementById('progress-wrap').hidden = true;
    document.getElementById('blocked-message').textContent = messages[reason];
    blocked.querySelector('h1').focus({preventScroll:true});
    window.scrollTo({top:0,behavior:'instant'});
  }
  function validateStep(i, allowBlock=true) {
    const q = questions[i], field = q.dataset.field;
    if (field === 'review') return true;
    const v = value(field).trim();
    if (!v) { error.textContent = field === 'available_year' ? 'Confirme ta disponibilité pour toute l’année 2027 pour continuer.' : field === 'privacy_consent' ? 'Ton accord est nécessaire pour transmettre ta candidature.' : 'Ajoute ta réponse pour continuer.'; return false; }
    const input = q.querySelector('input:not([type=radio]):not([type=checkbox]),textarea');
    if (input && !input.checkValidity()) { error.textContent = 'Vérifie ta réponse avant de continuer.'; input.focus(); return false; }
    if (field === 'birth_date') {
      const parts = v.split('-').map(Number), now = form.dataset.serverDate.split('-').map(Number);
      if (parts.length !== 3 || v >= form.dataset.serverDate || parts[0] < now[0]-120) { error.textContent = 'Indique une date de naissance valide.'; return false; }
      const age = now[0]-parts[0]-((now[1]<parts[1] || (now[1]===parts[1] && now[2]<parts[2])) ? 1 : 0);
      if (age >= 26) { if (allowBlock) block('age'); return false; }
    }
    if (['judicial_clear','license_b','mobile_departments'].includes(field) && v !== 'yes') { if (allowBlock) block(field); return false; }
    if (field === 'phone' && !/^(?:0[1-9]\d{8}|\+[1-9]\d{7,14})$/.test(v.replace(/[ .()\-]/g,''))) { error.textContent = 'Indique un téléphone valide, par exemple 06 12 34 56 78.'; return false; }
    if (field === 'motivation' && v.length < 30) { error.textContent = 'Ajoute quelques mots : 30 caractères minimum pour nous parler de ton projet.'; return false; }
    if (['last_name','first_name','city'].includes(field) && v.length < (field === 'city' ? 2 : 1)) { error.textContent = 'Complète ta réponse.'; return false; }
    return true;
  }
  function renderReview() {
    const container = document.getElementById('review'); container.replaceChildren();
    Object.entries(labels).forEach(([field,label]) => {
      const item = document.createElement('div'); item.className = 'review-item' + (field === 'motivation' ? ' wide' : '');
      const key = document.createElement('span'); key.textContent = label;
      const val = document.createElement('strong');
      let text = value(field);
      if (field === 'birth_date') text = text.split('-').reverse().join('/');
      if (field === 'vehicle') text = {yes:'Oui',no:'Autre organisation',planned:'Prévu pour la rentrée'}[text];
      val.textContent = text;
      const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Modifier'; edit.setAttribute('aria-label','Modifier : '+label);
      edit.addEventListener('click', () => show(questions.findIndex(q => q.dataset.field === field)));
      item.append(key,val,edit); container.append(item);
    });
  }
  async function submit() {
    if (busy || completed) return;
    for (let i = 0; i < questions.length - 1; i++) {
      if (!validateStep(i, false)) { show(i); validateStep(i); return; }
    }
    busy = true; next.disabled = true; previous.disabled = true; next.textContent = 'Enregistrement en cours…';
    error.textContent = '';
    const payload = Object.fromEntries(new FormData(form));
    yesNo.forEach(k => { payload[k] = payload[k] === 'yes'; });
    payload.csrf = form.dataset.csrf; payload.submission_token = form.dataset.token;
    try {
      const res = await fetch(form.dataset.endpoint, {method:'POST',headers:{'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(payload),credentials:'same-origin'});
      const data = await res.json().catch(() => null);
      if (!res.ok || !data?.ok) throw new Error(data?.error || 'L’envoi n’a pas pu être confirmé. Vérifie ta connexion puis réessaie. Tes réponses sont conservées sur cette page.');
      completed = true; form.hidden = true; document.getElementById('progress-wrap').hidden = true;
      const success = document.getElementById('success'); success.hidden = false;
      document.getElementById('success-message').textContent = data.already_received ? 'Une candidature a déjà été enregistrée avec ces coordonnées. Notre équipe reviendra vers toi. Tu peux nous contacter pour la mettre à jour.' : data.email_sent === false ? 'Ton dossier est enregistré. Le mail de confirmation n’a pas encore pu partir : tu n’as pas besoin de recommencer ta candidature.' : `Merci ${payload.first_name.trim()} ! Un e-mail de confirmation a été envoyé à ${payload.email.trim()}. Pense à vérifier tes courriers indésirables.`;
      document.getElementById('application-reference').textContent = data.reference ? `Ta référence : ${data.reference}` : '';
      success.querySelector('h1').focus({preventScroll:true}); window.scrollTo({top:0,behavior:'instant'});
      form.reset();
    } catch (err) { error.textContent = err.message; }
    finally { busy = false; next.disabled = false; previous.disabled = false; next.innerHTML = 'Envoyer ma candidature <span aria-hidden="true">↗</span>'; }
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (busy) return;
    if (index === questions.length - 1) { submit(); return; }
    if (validateStep(index)) show(index + 1);
  });
  form.addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.tagName !== 'TEXTAREA' && event.target.tagName !== 'BUTTON') { event.preventDefault(); form.requestSubmit(); } });
  previous.addEventListener('click', () => { if (!busy) show(Math.max(0,index-1)); });
  document.getElementById('correct-answer').addEventListener('click', () => show(index));
  document.querySelectorAll('[data-block]').forEach(button => button.addEventListener('click', () => block(button.dataset.block)));
  show(0);
})();
