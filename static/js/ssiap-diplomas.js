(() => {
  'use strict';
  const panel = document.getElementById('ssiapExamDiplomas');
  if (!panel) return;
  const dialog = document.getElementById('ssiapExamDialog');
  const candidates = document.getElementById('ssiapDiplomaCandidates');
  const status = document.getElementById('ssiapDiplomaStatus');
  const preview = document.getElementById('ssiapDiplomaPreview');
  const viewer = new window.SsiapPdfPreview(preview);
  const search = document.getElementById('ssiapDiplomaSearch');
  const filter = document.getElementById('ssiapDiplomaFilter');
  const keys = ['civility','first_name','last_name','birth_date','birth_city','birth_department','birth_country','exam_date','result'];
  const labels = {first_name:'prénom',last_name:'nom',birth_date:'date de naissance',birth_city:'ville de naissance',birth_department:'département',birth_country:'pays de naissance',exam_date:'date d’examen'};
  let data, busy = false, dirty = false;
  const lookups = new WeakMap();
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().trim();
  const french = country => ['', 'FRANCE', 'FR', 'FRA'].includes(normalize(country));
  const forms = () => [...candidates.querySelectorAll('[data-diploma-id]')];
  const info = form => Object.fromEntries(keys.map(key => [key, form.elements[key].value]));
  const rowFor = form => data.candidates.find(row => row.id === form.dataset.diplomaId);
  const date = value => /^\d{4}-\d\d-\d\d$/.test(value) ? value.split('-').reverse().join('/') : '…';
  const incomplete = value => Object.keys(labels).filter(key => (key !== 'birth_department' || (french(value.birth_country) && !/\((?:\d{2,3}|2A|2B)\)$/.test(value.birth_city))) && !value[key].trim());
  function message(text, error = false) { status.textContent = text; status.className = error ? 'error' : ''; }
  const input = (label, key, value, type = 'text') => `<label class="exam-field">${label}<input name="${key}" type="${type}" value="${esc(value)}" maxlength="120"></label>`;
  const select = (label, key, value, options, cls = '') => `<label class="exam-field ${cls}">${label}<select name="${key}" data-result="${esc(value)}">${options.map(([v,t]) => `<option value="${v}"${v === value ? ' selected' : ''}>${t}</option>`).join('')}</select></label>`;
  function card(row) {
    const v = row.values;
    return `<form class="exam-card diploma-form" data-diploma-id="${esc(row.id)}" data-birth-department-url="${esc(data.department_url)}"><fieldset ${data.read_only ? 'disabled' : ''}>
      <div class="exam-candidate-top"><div><h4 class="exam-candidate-name">${esc(v.first_name)} ${esc(v.last_name)}</h4>${!row.included ? '<span class="exam-chip warn">Non présenté à l’examen</span>' : ''}</div>${select('Résultat de l’examen','result',v.result,[['pending_results','En attente de résultat'],['certified','Certifié'],['failed','Ajourné']],'diploma-result')}</div>
      <p class="diploma-identity" data-diploma-identity></p><div class="diploma-meta"><span class="diploma-number">${row.number ? 'N° ' + esc(row.number) : 'Numéro attribué à la génération'}</span><span class="exam-muted" data-diploma-date></span><span class="exam-chip ${row.photo_available ? 'ok' : 'warn'}">${row.photo_available ? 'Photo disponible' : 'Photo absente'}</span></div>
      <p class="diploma-missing" data-diploma-missing hidden></p>
      <details class="exam-details"><summary>Vérifier / modifier les informations du diplôme</summary><div class="exam-grid three">
      ${select('Civilité','civility',v.civility,[['Monsieur','Monsieur'],['Madame','Madame']])}${input('Prénom','first_name',v.first_name)}${input('Nom','last_name',v.last_name)}
      ${input('Date de naissance','birth_date',v.birth_date,'date')}${input('Ville de naissance','birth_city',v.birth_city)}<label class="exam-field">Département de naissance<input name="birth_department" value="${esc(v.birth_department)}" maxlength="3" placeholder="Ex. : 74"><span class="diploma-hint" data-department-hint role="status" aria-live="polite"></span></label>
      ${input('Pays de naissance','birth_country',v.birth_country)}${input('Date d’examen','exam_date',v.exam_date,'date')}
      </div></details></fieldset><div class="exam-actions exam-save"><button type="button" class="btn btn-outline" data-diploma-preview>Prévisualiser le diplôme</button><button type="button" class="btn btn-primary" data-diploma-generate>Générer le diplôme</button></div></form>`;
  }
  function refresh() {
    if (!data) return;
    let changed = false, certified = 0, failed = 0, pending = 0, visible = 0;
    for (const form of forms()) {
      const row = rowFor(form), v = info(form);
      const isDirty = keys.some(key => v[key] !== row.values[key]);
      form.dataset.dirty = String(isDirty);
      changed ||= isDirty;
      if (v.result === 'certified' && row.included) certified++;
      else if (v.result === 'failed') failed++;
      else if (v.result === 'pending_results') pending++;
      form.querySelector('h4').textContent = `${v.first_name} ${v.last_name}`;
      const place = french(v.birth_country) ? `${v.birth_city}${v.birth_department && !/\([^)]+\)$/.test(v.birth_city) ? ' (' + v.birth_department + ')' : ''}` : `${v.birth_city.replace(/\s*\([^()]*\)\s*$/, '')}${v.birth_country ? ' (' + v.birth_country + ')' : ''}`;
      form.querySelector('[data-diploma-identity]').textContent = `${v.first_name} ${v.last_name}, ${v.civility === 'Madame' ? 'née' : 'né'} le ${date(v.birth_date)} à ${place || '…'}`;
      form.querySelector('[data-diploma-date]').textContent = `Examen du ${date(v.exam_date)}`;
      const missing = incomplete(v);
      const warning = form.querySelector('[data-diploma-missing]');
      warning.hidden = !missing.length;
      warning.textContent = 'À compléter : ' + missing.map(key => labels[key]).join(', ') + '.';
      form.elements.result.dataset.result = v.result;
      form.elements.birth_department.disabled = !french(v.birth_country);
      form.querySelector('fieldset').disabled = busy || data.read_only;
      form.querySelector('[data-diploma-preview]').disabled = busy;
      form.querySelector('[data-diploma-generate]').disabled = busy || data.read_only || v.result !== 'certified' || !row.included;
      const match = normalize(`${v.first_name} ${v.last_name}`).includes(normalize(search.value));
      form.hidden = !match || (filter.value === 'incomplete' ? !missing.length : filter.value !== 'all' && v.result !== filter.value);
      if (!form.hidden) visible++;
    }
    dirty = changed;
    document.getElementById('ssiapDiplomaCounts').innerHTML = [[data.candidates.length,'Candidats',''],[certified,'Certifiés présentés','certified'],[failed,'Ajournés','failed'],[pending,'En attente','']].map(([n,t,c]) => `<div class="diploma-count ${c}"><strong>${n}</strong><span>${t}</span></div>`).join('');
    panel.querySelector('[data-diploma-save]').disabled = busy || data.read_only || !dirty;
    panel.querySelector('[data-diploma-preview-all]').disabled = busy || !certified;
    panel.querySelector('[data-diploma-generate-all]').disabled = busy || data.read_only || !certified;
    panel.querySelector('[data-diploma-letter-preview]').disabled = busy || !certified;
    panel.querySelector('[data-diploma-letter]').disabled = busy || data.read_only || !certified;
    panel.querySelector('[data-diploma-exam-reference]').textContent = `Examen du ${date(data.exam_date)} · ${data.exam_number ? 'N° ' + data.exam_number : 'Numéro à renseigner dans Organisation et jury'}`;
    panel.querySelector('[data-diploma-refresh]').disabled = busy;
    let empty = candidates.querySelector('.diploma-empty');
    if (!empty) { empty = document.createElement('p'); empty.className = 'diploma-empty'; candidates.append(empty); }
    empty.textContent = data.candidates.length ? 'Aucun candidat ne correspond à ce filtre.' : 'Aucun candidat actif dans cette session.';
    empty.hidden = visible > 0;
  }
  function render() {
    const opened = new Set(forms().filter(form => form.querySelector('details').open).map(form => form.dataset.diplomaId));
    forms().forEach(form => lookups.get(form)?.cancel());
    candidates.innerHTML = data.candidates.map(card).join('');
    for (const form of forms()) {
      form.querySelector('details').open = opened.has(form.dataset.diplomaId);
      if (!data.read_only) lookups.set(form, window.initSsiapBirthDepartment(form, form.querySelector('[data-department-hint]')));
    }
    refresh();
  }
  async function response(options = {}, url = panel.dataset.url) {
    const result = await fetch(url, {credentials:'same-origin', ...options, headers:{Accept:'application/json', ...options.headers}});
    if (!result.ok || (result.headers.get('Content-Type') || '').includes('text/html')) {
      let error;
      try { error = (await result.json()).error; } catch {}
      throw new Error(error || 'Action indisponible. Vérifiez votre connexion ou reconnectez-vous.');
    }
    return result;
  }
  const post = payload => response({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:data.csrf,...payload})});
  function drafts(onlyDirty = false) {
    return forms().filter(form => !onlyDirty || form.dataset.dirty === 'true').map(form => ({id:form.dataset.diplomaId, revision:rowFor(form).revision, values:info(form)}));
  }
  async function load() {
    data = await (await response()).json();
    render();
    message('');
    // Limit simultaneous requests while automatically checking every missing department.
    const queue = forms();
    async function resolveNext() {
      while (queue.length) {
        const form = queue.shift();
        if (form.isConnected) await lookups.get(form)?.lookup();
      }
    }
    void Promise.all([resolveNext(), resolveNext(), resolveNext()]);
  }
  async function save() {
    const changes = drafts(true);
    if (!changes.length) return;
    const result = await (await post({action:'save',candidates:changes})).json();
    data.candidates = result.candidates;
    render();
    // Keep the pre-existing trainee table in sync without a reload that loses other drafts.
    for (const row of result.candidates) {
      const button = [...document.querySelectorAll('.ssiap-edit-info-btn')].find(el => (el.dataset.ssiapInfoAction || '').includes('/trainees/' + encodeURIComponent(row.id) + '/'));
      if (button) for (const key of keys.filter(k => k !== 'result')) button.dataset[key.replace(/_([a-z])/g, (_,c) => c.toUpperCase())] = row.values[key];
      const select = [...document.querySelectorAll('#traineesTable tr[data-trainee-id]')].find(el => el.dataset.traineeId === row.id)?.querySelector('.ssiap-exam-select');
      if (select) { select.value = row.values.result; select.classList.remove('ssiap-exam-certified','ssiap-exam-failed','ssiap-exam-pending_results'); select.classList.add('ssiap-exam-' + row.values.result); }
    }
  }
  async function act(work) {
    if (busy) return;
    busy = true; refresh();
    try { await work(); } catch (error) { message(error.message, true); }
    finally { busy = false; refresh(); }
  }
  async function pdf(action, id) {
    const isPreview = action === 'preview' || action === 'letter_preview';
    const isLetter = action === 'letter' || action === 'letter_preview';
    if (!isPreview) { message(isLetter ? 'Préparation du courrier SDIS…' : 'Enregistrement et génération des diplômes…'); await save(); }
    else message('Préparation de l’aperçu…');
    const query = new URLSearchParams();
    if (id) query.set('trainee_id', id);
    if (isLetter) query.set('document', 'letter');
    const result = data.read_only && isPreview
      ? await response({}, panel.dataset.url + '/preview' + (query.size ? '?' + query : ''))
      : await post({action, ...(id ? {trainee_id:id} : {}), candidates:isPreview ? drafts() : []});
    const blob = await result.blob();
    const filename = (isPreview ? 'apercu-' : '') + (isLetter ? 'courrier-SDIS.pdf' : 'diplomes-SSIAP.pdf');
    const options = isLetter ? {filename, title:isPreview ? 'Prévisualisation du courrier SDIS' : 'Courrier SDIS prêt à imprimer', description:isPreview ? 'Aperçu de vérification · Aucun numéro n’est attribué.' : 'Les numéros de diplôme sont enregistrés. Joignez les diplômes correspondants à votre envoi postal.'} : {filename};
    if (isPreview) { await viewer.open(blob, options); message('Aperçu prêt. Aucun numéro attribué.'); return; }
    window.dispatchEvent(new CustomEvent('ssiap-diplomas-generated', {detail:JSON.parse(result.headers.get('X-SSIAP-Diploma-Numbers') || '{}')}));
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    await load();
    if (isLetter) await viewer.open(blob, options);
    message(isLetter ? 'Courrier SDIS généré et téléchargé. Les numéros de diplôme sont enregistrés.' : 'Diplômes générés et téléchargés. Les numéros sont enregistrés.');
  }
  panel.addEventListener('input', event => { if (event.target.closest('[data-diploma-id]')) {refresh(); message(dirty ? 'Modifications à enregistrer.' : '');} });
  panel.addEventListener('change', event => { if (event.target.closest('[data-diploma-id]')) {refresh(); message(dirty ? 'Modifications à enregistrer.' : '');} });
  panel.addEventListener('ssiap-birth-department-found', () => { refresh(); if (dirty) message('Département complété. Modifications à enregistrer.'); });
  panel.addEventListener('toggle', event => { if (event.target.matches('details') && event.target.open && !busy) event.target.closest('form').dispatchEvent(new Event('ssiap-diploma-info-opened')); }, true);
  panel.addEventListener('submit', event => {event.preventDefault(); act(async () => {await save(); message('Informations et résultats enregistrés.');});});
  panel.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const id = button.closest('[data-diploma-id]')?.dataset.diplomaId;
    if (button.hasAttribute('data-diploma-save')) act(async () => {await save(); message('Informations et résultats enregistrés.');});
    if (button.hasAttribute('data-diploma-refresh')) {
      if (dirty && !window.confirm('Actualiser et abandonner les modifications non enregistrées ?')) return;
      act(load);
    }
    if (button.hasAttribute('data-diploma-preview') || button.hasAttribute('data-diploma-preview-all')) act(() => pdf('preview', id));
    if (button.hasAttribute('data-diploma-generate') || button.hasAttribute('data-diploma-generate-all')) act(() => pdf('generate', id));
    if (button.hasAttribute('data-diploma-letter-preview')) act(() => pdf('letter_preview'));
    if (button.hasAttribute('data-diploma-letter')) act(() => pdf('letter'));
    if (button.hasAttribute('data-diploma-organization')) dialog.querySelector('[data-exam-tab="organization"]').click();
  });
  search.addEventListener('input', refresh); filter.addEventListener('change', refresh);
  dialog.addEventListener('click', event => { if (event.target.closest('[data-exam-tab="diplomas"]') && !data) act(load); });
  dialog.addEventListener('ssiap-exam-loaded', event => {
    if (data && event.examConfig) {
      data.exam_number = event.examConfig.exam_number;
      data.exam_date = event.examConfig.date;
      refresh();
    }
    if (!dirty && !busy) { data = undefined; if (!panel.hidden) act(load); }
  });
  // Closing the exam retains the draft. Clicking its backdrop never closes it.
  window.addEventListener('beforeunload', event => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
})();
