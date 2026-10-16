const dialog = document.getElementById('traineeDocumentCheck');
const states = new WeakMap();
let activeForm = null;
const title = document.getElementById('tdcTitle');
const message = document.getElementById('tdcMessage');
const primary = document.getElementById('tdcPrimary');
const secondary = document.getElementById('tdcSecondary');
const replacement = document.getElementById('tdcReplace');
const unavailable = () => ({status: 'unknown', title: 'Vérification automatique indisponible', message: 'Le service de vérification est momentanément inaccessible ou n’a pas renvoyé de résultat exploitable. Cela ne signifie pas que votre document est illisible. Vous pouvez réessayer, choisir un autre fichier ou le déposer pour vérification par notre équipe.'});
const fileKey = file => `${file.name}:${file.size}:${file.lastModified}`;

export function selectionError(files, accept, maxBytes, maxFiles) {
  if (maxFiles && files.length > maxFiles) return `Vous pouvez sélectionner ${maxFiles} fichier${maxFiles > 1 ? 's' : ''}. Retirez le fichier en trop.`;
  if (files.reduce((sum, file) => sum + file.size, 0) > maxBytes - 65536) return `L’ensemble des fichiers doit rester inférieur à ${Math.floor(maxBytes / 1048576)} Mo. Réduisez leur taille, puis réessayez.`;
  const formats = {'application/pdf': ['pdf'], 'image/jpeg': ['jpg', 'jpeg'], 'image/png': ['png'], 'image/webp': ['webp'], 'image/*': ['jpg', 'jpeg', 'png', 'webp']};
  const allowed = accept.toLowerCase().split(',').flatMap(value => formats[value.trim()] || (value.trim().startsWith('.') ? [value.trim().slice(1)] : []));
  for (const file of files) {
    if (!file.size) return `Le fichier « ${file.name} » est vide. Sélectionnez une nouvelle copie.`;
    const ext = file.name.toLowerCase().split('.').pop();
    if (allowed.length && !allowed.includes(ext)) return `Le fichier « ${file.name} » n’est pas au bon format. Format attendu : ${[...new Set(allowed)].join(', ').toUpperCase()}. Ne renommez pas simplement l’extension : exportez une nouvelle copie.`;
  }
  return '';
}

function invalidate(form) {
  const state = states.get(form);
  state.replacementPicker?.remove();
  state.replacementPicker = null;
  state.sequence++;
  state.controller?.abort();
  state.pending = false;
  state.result = null;
  state.approved = false;
  form.elements.document_check_receipt.value = '';
}

function close() {
  if (dialog?.open) dialog.close();
  activeForm?.querySelector('input[type=file]')?.focus();
}

function modify(form) {
  if (form) invalidate(form);
  close();
  if (form) updateFeedback(form, 'Vous pouvez retirer un fichier ci-dessous, puis en sélectionner un autre.');
}

function chooseReplacement(form) {
  if (!form) return;
  const state = states.get(form);
  const input = form.querySelector('input[type=file]');
  invalidate(form);
  close();
  updateFeedback(form, 'Choisissez un autre document. Votre sélection actuelle sera conservée si vous annulez.');
  // A separate picker keeps the original FileList intact on cancellation and
  // lets identity replacements differ from the usual "add the other side" flow.
  const picker = document.createElement('input');
  picker.type = 'file';
  picker.accept = input.accept;
  picker.multiple = input.multiple;
  picker.hidden = true;
  picker.dataset.tdcReplacementPicker = '';
  state.replacementPicker = picker;
  const sequence = state.sequence;
  const cleanup = () => {
    picker.remove();
    if (state.replacementPicker === picker) state.replacementPicker = null;
  };
  const cancel = () => {
    cleanup();
    if (sequence !== state.sequence) return;
    renderFiles(form);
    updateFeedback(form, 'Sélection conservée. Vous pouvez vérifier les fichiers ou en choisir d’autres.');
  };
  picker.addEventListener('cancel', cancel, {once: true});
  picker.addEventListener('change', () => {
    const picked = Array.from(picker.files || []);
    if (!picked.length) { cancel(); return; }
    cleanup();
    if (sequence !== state.sequence) return;
    invalidate(form);
    state.files = picked;
    renderFiles(form);
    check(form);
  }, {once: true});
  document.body.append(picker);
  picker.click();
}

function send(form) {
  const state = states.get(form);
  if (!state?.files.length || state.pending || state.result?.summary.status === 'invalid') return;
  state.approved = true;
  close();
  form.requestSubmit();
}

function show(form, result, pending = false) {
  if (!dialog) return;
  activeForm = form;
  const status = pending ? 'pending' : result?.summary?.status || 'unknown';
  const summary = result?.summary || unavailable();
  dialog.dataset.status = status;
  document.getElementById('tdcSymbol').textContent = {success: '✓', warning: '!', invalid: '!', unknown: '?'}[status] || '';
  const isPhoto = form?.dataset.documentKey === 'photo';
  title.textContent = pending ? (isPhoto ? 'Un instant, nous vérifions votre photo…' : 'Un instant, nous préparons votre document…') : summary.title || (status === 'unknown' ? unavailable().title : 'Votre document');
  message.textContent = pending ? (isPhoto ? 'Cela peut prendre quelques secondes. Votre photo restera une image.' : 'Nous convertissons votre fichier en PDF si nécessaire, puis nous vérifions le document. Cela peut prendre quelques instants.') + ' Vous pouvez revenir à votre sélection à tout moment.' : summary.message || (status === 'unknown' ? unavailable().message : 'Notre équipe confirmera la conformité du document.');
  document.getElementById('tdcDocument').textContent = form?.dataset.documentLabel || '';
  const steps = document.getElementById('tdcSteps');
  steps.replaceChildren();
  steps.hidden = !pending;
  if (pending) {
    const items = isPhoto ? ['Une seule photo, sans planche ni montage', 'Netteté, fond et éclairage', 'Visage de face, cadrage et expression'] : form.dataset.documentKey === 'id' ? ['Ouverture et conversion en PDF si nécessaire', 'Lisibilité, reflets et cadrage', 'Recto-verso ou page d’identité du passeport'] : ['Ouverture et conversion en PDF si nécessaire', 'Type du document demandé', 'Lisibilité et cadrage'];
    items.forEach(text => { const li = document.createElement('li'); li.textContent = text; steps.append(li); });
  }
  const details = document.getElementById('tdcFileResults');
  details.replaceChildren();
  if (!pending && result?.results?.length > 1) result.results.forEach((item, index) => {
    const line = document.createElement('p');
    line.textContent = `Fichier ${index + 1} : ${item.title || {success: 'critères vérifiés', warning: 'point à vérifier', unknown: 'contrôle non concluant'}[item.status] || 'à vérifier'}`;
    details.append(line);
  });
  document.getElementById('tdcNote').textContent = status === 'invalid' ? 'Le fichier n’a pas été déposé. Corrigez-le pour poursuivre.' : 'Votre fichier n’est pas encore déposé. Ce contrôle est indicatif ; notre équipe confirme la conformité.';
  const replaceLabel = isPhoto ? 'Choisir une autre photo' : 'Choisir un autre document';
  replacement.hidden = status !== 'unknown' || !form;
  replacement.textContent = replaceLabel;
  replacement.onclick = () => chooseReplacement(form);
  secondary.hidden = pending || status === 'invalid' || !form;
  if (pending || status === 'invalid') {
    primary.textContent = replaceLabel; primary.onclick = () => chooseReplacement(form);
  } else if (status === 'success') {
    primary.textContent = 'Déposer le document'; primary.onclick = () => send(form);
    secondary.textContent = replaceLabel; secondary.onclick = () => chooseReplacement(form);
  } else if (status === 'unknown') {
    primary.textContent = 'Réessayer la vérification'; primary.onclick = () => check(form);
    secondary.textContent = 'Déposer pour vérification par l’équipe'; secondary.onclick = () => send(form);
  } else {
    primary.textContent = replaceLabel; primary.onclick = () => chooseReplacement(form);
    secondary.textContent = 'Conserver et déposer quand même'; secondary.onclick = () => send(form);
  }
  if (!form) { primary.textContent = 'J’ai compris'; primary.onclick = close; }
  if (!dialog.open) dialog.showModal();
  title.focus();
}

function updateFeedback(form, text = '') {
  const feedback = form.querySelector('.tdc-feedback');
  const state = states.get(form);
  feedback.replaceChildren();
  const label = document.createElement('span');
  label.textContent = text || state.result?.summary.title || '';
  feedback.append(label);
  if (state.files.length) {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = state.result ? 'Voir le résultat de la vérification' : 'Vérifier les fichiers';
    button.addEventListener('click', () => state.result ? show(form, state.result) : check(form));
    feedback.append(button);
  }
}

function renderFiles(form) {
  const state = states.get(form);
  const input = form.querySelector('input[type=file]');
  const transfer = new DataTransfer();
  state.files.forEach(file => transfer.items.add(file));
  input.files = transfer.files;
  const list = form.querySelector('.tdc-files');
  list.replaceChildren();
  state.files.forEach((file, index) => {
    const li = document.createElement('li'); const name = document.createElement('span');
    name.textContent = `${file.name} · ${(file.size / 1048576).toFixed(2)} Mo`;
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Retirer';
    remove.setAttribute('aria-label', `Retirer ${file.name}`);
    remove.addEventListener('click', () => { invalidate(form); state.files.splice(index, 1); renderFiles(form); updateFeedback(form); });
    li.append(name, remove); list.append(li);
  });
  // Keep the existing summary, with the removable list as the single source of filenames.
  const summary = form.querySelector('#id_files_summary');
  if (summary) summary.textContent = state.files.length ? `${state.files.length} fichier(s) sélectionné(s).` : 'Aucun fichier sélectionné.';
  form.querySelector('#id_files_list')?.replaceChildren();
}

async function check(form) {
  const state = states.get(form);
  if (state.pending) { show(form, null, true); return; }
  invalidate(form);
  if (!state.files.length) return;
  const error = selectionError(state.files, form.querySelector('input[type=file]').accept, Number(form.dataset.maxBytes), Number(form.dataset.maxFiles));
  if (error) {
    state.result = {summary: {status: 'invalid', title: 'Le fichier doit être corrigé', message: error}};
    updateFeedback(form); show(form, state.result); return;
  }
  state.pending = true;
  state.controller = new AbortController();
  const controller = state.controller;
  const sequence = state.sequence;
  const timer = setTimeout(() => controller.abort(), 180000);
  updateFeedback(form, 'Vérification en cours…'); show(form, null, true);
  const data = new FormData();
  state.files.forEach(file => data.append('files', file));
  try {
    const response = await fetch(form.dataset.documentCheckUrl, {method: 'POST', credentials: 'same-origin',
      headers: {'X-Document-Check-Token': form.elements.document_check_token.value, 'Accept': 'application/json'},
      body: data, signal: controller.signal});
    let result;
    if ([401, 403].includes(response.status)) {
      result = {summary: {status: 'invalid', title: 'Reconnectez-vous à votre espace', message: 'Votre session a expiré. Rechargez cette page, reconnectez-vous, puis sélectionnez vos fichiers à nouveau.'}};
    } else if (response.status === 413) {
      result = {summary: {status: 'invalid', title: 'Fichiers trop volumineux', message: 'Réduisez la taille des fichiers puis réessayez.'}};
    } else {
      result = await response.json();
      if (!['success', 'warning', 'unknown', 'invalid'].includes(result?.summary?.status)) throw new Error('invalid_response');
    }
    if (sequence !== state.sequence) return;
    state.result = result;
    form.elements.document_check_receipt.value = result.receipt || '';
  } catch (_error) {
    if (sequence !== state.sequence) return;
    state.result = {summary: unavailable()};
  } finally {
    clearTimeout(timer);
    if (sequence === state.sequence) {
      state.pending = false;
      updateFeedback(form);
      if (activeForm === form && dialog.open) show(form, state.result);
    }
  }
}

if (dialog) {
  dialog.querySelector('[data-tdc-close]').addEventListener('click', () => modify(activeForm));
  dialog.addEventListener('cancel', event => { event.preventDefault(); modify(activeForm); });
  document.querySelectorAll('form[data-document-check-url]').forEach(form => {
    const input = form.querySelector('input[type=file]');
    states.set(form, {files: [], sequence: 0, pending: false, approved: false, result: null, replacementPicker: null});
    input.addEventListener('change', () => {
      const state = states.get(form);
      const picked = Array.from(input.files || []);
      if (!picked.length) { renderFiles(form); return; } // Cancelling the chooser keeps the current selection.
      invalidate(form);
      state.files = form.dataset.documentKey === 'id' ? [...state.files, ...picked.filter(file => !state.files.some(existing => fileKey(existing) === fileKey(file)))] : picked;
      renderFiles(form);
      check(form);
    });
    form.addEventListener('submit', event => {
      const state = states.get(form);
      if (state.approved) {
        form.querySelector('button[type=submit]').disabled = true;
        form.querySelector('.uploading-msg').style.display = 'block';
        window.openModal?.('uploadLoadingModal');
        return;
      }
      event.preventDefault();
      if (state.result) show(form, state.result); else check(form);
    });
  });
  const errorNode = document.getElementById('documentUploadError');
  const error = errorNode ? JSON.parse(errorNode.textContent || 'null') : null;
  if (error) show(null, {summary: error});
}
