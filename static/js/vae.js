(() => {
  const container = document.querySelector('.vae-container[data-vae-id]');
  if (!container) return;
  const dossierId = container.dataset.vaeId;
  const adminEditMode = container.dataset.adminEdit === '1';
  const form = document.getElementById('vaeForm');
  const steps = [...document.querySelectorAll('.step')];
  const progress = document.getElementById('vaeProgress');
  const saveStatus = document.getElementById('saveStatus');
  const errorsEl = document.getElementById('submitErrors');
  const experienceDocsInput = document.getElementById('experienceDocsInput');
  const experienceDocsList = document.getElementById('experienceDocsList');
  const experienceDocsStatus = document.getElementById('experienceDocsStatus');
  const initial = window.__VAE_INITIAL__ || {};
  let current = 0;
  let experienceDocs = Array.isArray(initial.justificatifs_experience) ? [...initial.justificatifs_experience] : [];

  const STEP_LABELS = {
    1: 'Nature de la demande',
    2: '1ère étape : Informations générales sur le candidat',
    3: '2ème étape : Certification professionnelle visée',
    4: '3ème étape : Expériences du candidat',
    5: '4ème étape : Analyse des compétences du candidat',
    6: '5ème étape : Parcours prévisionnel du candidat',
    7: '6ème étape : Formulaire d’avis de faisabilité',
    8: '7ème étape : Accord pour l\'analyse de la faisabilité',
  };

  const REQUIRED_CANDIDAT_FIELDS = {
    nom_naissance: 'Nom de naissance',
    prenoms: 'Prénom(s)',
    date_naissance: 'Date de naissance',
    nationalite: 'Nationalité',
    genre: 'Genre',
    niveau_formation: 'Niveau de formation le plus élevé',
    niveau_certification: 'Niveau de certification la plus élevée',
    certifications_obtenues: 'Intitulé des certifications obtenues',
    adresse: 'Adresse',
    code_postal: 'Code postal',
    ville: 'Ville',
    telephone: 'Téléphone',
    email: 'Adresse email',
    statut: 'Statut du candidat',
  };

  const STEP_REQUIRED_FIELDS = {
    2: [
      ...Object.keys(REQUIRED_CANDIDAT_FIELDS).map((field) => `candidat.${field}`),
      'candidat.objectifs',
    ],
    5: [
      ...Array.from({ length: 5 }, (_, actIdx) =>
        Array.from({ length: 4 }, (_, compIdx) => [
          `blocs_competences.activite${actIdx + 1}.competence${compIdx + 1}.intitule`,
          `blocs_competences.activite${actIdx + 1}.competence${compIdx + 1}.statut`,
        ]),
      ).flat(2),
      ...Array.from({ length: 5 }, (_, actIdx) => `blocs_competences.activite${actIdx + 1}.commentaires`),
    ],
    8: [
      'engagement.accord_analyse',
      'engagement.lieu_signature',
      'engagement.date_signature',
      'engagement.nom_signature',
      'engagement.signature_trace',
      'engagement.signature_signed_at',
    ],
  };

  function setPath(obj, path, value) {
    const keys = path.split('.');
    let ref = obj;
    keys.slice(0, -1).forEach((k) => {
      if (!ref[k] || typeof ref[k] !== 'object') ref[k] = {};
      ref = ref[k];
    });
    ref[keys[keys.length - 1]] = value;
  }

  function getPayload() {
    const payload = structuredClone(initial);
    const fd = new FormData(form);

    for (const [k, v] of fd.entries()) {
      if (k === 'certification.blocs_vises') {
        setPath(payload, k, String(v).split(',').map((s) => s.trim()).filter(Boolean));
      } else if (k === 'candidat.objectifs') {
        // handled separately to preserve all checked values
      } else {
        setPath(payload, k, v);
      }
    }

    const objectifs = [...form.querySelectorAll('[name="candidat.objectifs"]:checked')].map((el) => el.value);
    setPath(payload, 'candidat.objectifs', objectifs);

    ['engagement.souhaite_accompagnement', 'engagement.accord_analyse'].forEach((name) => {
      const el = form.querySelector(`[name="${name}"]`);
      setPath(payload, name, !!(el && el.checked));
    });

    setPath(payload, 'certification.vise', 'complete');

    const experiences = [...document.querySelectorAll('.experience-item')].map((item) => ({
      date_debut: item.querySelector('[name="exp_date_debut"]').value,
      duree: item.querySelector('[name="exp_duree"]').value,
      description: item.querySelector('[name="exp_description"]').value,
    }));
    payload.experiences = experiences;

    const signName = String(payload.engagement?.nom_signature || '').trim();
    const signDate = String(payload.engagement?.signature_signed_at || '').trim();
    if (!signName || !signDate) {
      setPath(payload, 'engagement.signature_trace', '');
      setPath(payload, 'engagement.signature_signed_at', '');
    }

    return payload;
  }

  async function autosave() {
    saveStatus.textContent = 'Sauvegarde…';
    const payload = getPayload();
    const res = await fetch(`/api/vae/${dossierId}/save`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    saveStatus.textContent = res.ok ? 'Sauvegardé' : 'Erreur de sauvegarde';
    if (res.ok) setTimeout(() => (saveStatus.textContent = ''), 1200);
  }

  let t;
  function autosaveDebounced() {
    clearTimeout(t);
    t = setTimeout(() => autosave().catch(() => (saveStatus.textContent = 'Erreur de sauvegarde')), 450);
  }

  function renderStep() {
    steps.forEach((s, i) => s.classList.toggle('active', i === current));
    progress.style.width = `${((current + 1) / steps.length) * 100}%`;
    document.getElementById('prevStep').style.visibility = current === 0 ? 'hidden' : 'visible';
    document.getElementById('nextStep').style.visibility = current === steps.length - 1 ? 'hidden' : 'visible';
  }

  function updateConventionCollectiveState() {
    const statut = form.querySelector('[name="candidat.statut"]:checked')?.value || '';
    const convention = form.querySelector('#conventionCollective');
    if (!convention) return;
    const enabled = statut === 'salarie_prive';
    convention.disabled = !enabled;
    if (!enabled) {
      convention.value = '';
    }
  }

  function hasValueForField(payload, fieldName) {
    if (typeof fieldName !== 'string') return false;
    if (fieldName === 'engagement.accord_analyse') {
      return !!payload.engagement?.accord_analyse;
    }
    const keys = fieldName.split('.');
    let ref = payload;
    for (const key of keys) {
      ref = ref?.[key];
    }
    return typeof ref === 'boolean' ? ref : String(ref || '').trim().length > 0;
  }

  function humanizeFieldName(fieldName) {
    if (typeof fieldName !== 'string') return 'Champ obligatoire';
    const el = form.querySelector(`[name="${fieldName}"]`);
    if (el) {
      const labelEl = el.closest('.field-with-label')?.querySelector('label');
      if (labelEl?.textContent?.trim()) return labelEl.textContent.trim();
      if (el.placeholder?.trim()) return el.placeholder.trim();
    }

    const competenceMatch = fieldName.match(/^blocs_competences\.activite(\d+)\.competence(\d+)\.(intitule|statut)$/);
    if (competenceMatch) {
      const activite = competenceMatch[1];
      const competence = competenceMatch[2];
      const type = competenceMatch[3] === 'intitule' ? 'Intitulé de la compétence' : 'Niveau de réalisation';
      return `Activité ${activite} – Compétence ${competence} : ${type}`;
    }

    const commentaireMatch = fieldName.match(/^blocs_competences\.activite(\d+)\.commentaires$/);
    if (commentaireMatch) {
      return `Activité ${commentaireMatch[1]} : Commentaires`;
    }

    if (fieldName === 'engagement.accord_analyse') return 'Accord pour l’analyse de la faisabilité';
    if (fieldName === 'engagement.lieu_signature') return 'Lieu de signature';
    if (fieldName === 'engagement.date_signature') return 'Date de signature';
    if (fieldName === 'engagement.nom_signature') return 'Nom et prénom';
    if (fieldName === 'engagement.signature_trace') return 'Signature électronique';
    if (fieldName === 'engagement.signature_signed_at') return 'Date de signature électronique';

    return fieldName;
  }

  function validateCurrentStep() {
    const step = current + 1;
    const payload = getPayload();
    const required = STEP_REQUIRED_FIELDS[step] || [];
    const currentStepEl = steps[current];
    currentStepEl?.querySelectorAll('.field-error').forEach((el) => el.classList.remove('field-error'));
    const missing = required.filter((field) => !hasValueForField(payload, field));
    if (step === 4 && experienceDocs.length === 0) {
      missing.push('justificatifs_experience');
    }
    if (!missing.length) {
      errorsEl.innerHTML = '';
      return true;
    }
    missing.forEach((field) => {
      const fieldElements = currentStepEl?.querySelectorAll(`[name="${field}"]`) || [];
      fieldElements.forEach((el) => el.classList.add('field-error'));
    });
    errorsEl.innerHTML = '<div>Vous n\'avez pas rempli tous les champs</div>';
    return false;
  }

  function buildAdminUploadUrl(token) {
    if (!token) return '';
    return `/admin/uploads/${encodeURIComponent(String(token)).replace(/%2F/g, '/')}`;
  }

  function renderExperienceDocs() {
    if (!experienceDocsList) return;
    if (!experienceDocs.length) {
      experienceDocsList.innerHTML = '<div class="muted">Aucun justificatif déposé pour le moment.</div>';
      return;
    }

    const canDelete = adminEditMode || String(initial?.statut_dossier || '').toLowerCase() !== 'soumis';
    experienceDocsList.innerHTML = experienceDocs.map((doc) => {
      const id = String(doc?.id || '');
      const name = String(doc?.name || 'justificatif');
      const token = String(doc?.token || '');
      const viewBtn = adminEditMode && token
        ? `<a class="btn secondary" href="${buildAdminUploadUrl(token)}" target="_blank" rel="noopener">Voir</a>`
        : '';
      const deleteBtn = canDelete && id
        ? `<button type="button" class="btn danger" data-delete-doc="${id}">Supprimer</button>`
        : '';
      return `<div class="experience-doc-item"><div class="experience-doc-item-name">${name}</div><div class="experience-doc-item-actions">${viewBtn}${deleteBtn}</div></div>`;
    }).join('');

    experienceDocsList.querySelectorAll('[data-delete-doc]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const docId = btn.getAttribute('data-delete-doc');
        deleteExperienceDoc(docId).catch(() => {
          if (experienceDocsStatus) experienceDocsStatus.textContent = 'Erreur lors de la suppression';
        });
      });
    });
  }

  async function deleteExperienceDoc(docId) {
    if (!docId) return;
    if (experienceDocsStatus) experienceDocsStatus.textContent = 'Suppression…';
    const res = await fetch(`/api/vae/${dossierId}/experience-docs/${docId}/delete`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (experienceDocsStatus) experienceDocsStatus.textContent = 'Erreur lors de la suppression';
      return;
    }
    experienceDocs = Array.isArray(data.files) ? data.files : [];
    initial.justificatifs_experience = experienceDocs;
    if (experienceDocsStatus) experienceDocsStatus.textContent = 'Justificatif supprimé';
    renderExperienceDocs();
  }

  async function uploadExperienceDocs(files) {
    if (!files?.length) return;
    const fd = new FormData();
    [...files].forEach((file) => fd.append('files', file));
    if (experienceDocsStatus) experienceDocsStatus.textContent = 'Téléversement en cours…';
    const res = await fetch(`/api/vae/${dossierId}/experience-docs/upload`, {
      method: 'POST',
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (experienceDocsStatus) experienceDocsStatus.textContent = 'Erreur lors du téléversement';
      return;
    }
    experienceDocs = Array.isArray(data.files) ? data.files : [];
    initial.justificatifs_experience = experienceDocs;
    if (experienceDocsStatus) experienceDocsStatus.textContent = `${(data.added || []).length} justificatif(s) ajouté(s)`;
    renderExperienceDocs();
  }


  function formatIsoDate(date = new Date()) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
  }

  function getCandidateFullName() {
    const prenoms = String(form.querySelector('[name="candidat.prenoms"]')?.value || '').trim();
    const nomUsage = String(form.querySelector('[name="candidat.nom_usage"]')?.value || '').trim();
    const nomNaissance = String(form.querySelector('[name="candidat.nom_naissance"]')?.value || '').trim();
    return [prenoms, nomUsage || nomNaissance].filter(Boolean).join(' ').trim();
  }

  function syncEngagementIdentityAndDate() {
    const dateInput = form.querySelector('[name="engagement.date_signature"]');
    const nameInput = form.querySelector('[name="engagement.nom_signature"]');
    if (dateInput && !String(dateInput.value || '').trim()) {
      dateInput.value = formatIsoDate(new Date());
    }
    if (nameInput) {
      const fullName = getCandidateFullName();
      nameInput.value = fullName;
    }
    renderSignaturePreview();
  }

  function addExperienceRow(exp = { date_debut: '', duree: '', description: '' }) {
    const wrap = document.getElementById('experiencesContainer');
    const div = document.createElement('div');
    div.className = 'experience-item card';
    div.innerHTML = `
      <div class="experience-item-header">
        <button type="button" class="btn experience-add-btn add-exp-inline">Ajouter une expérience</button>
      </div>
      <div class="field-with-label">
        <label>Date de début</label>
        <input type="date" name="exp_date_debut" value="${exp.date_debut || ''}">
      </div>
      <input name="exp_duree" placeholder="Durée" value="${exp.duree || ''}">
      <textarea name="exp_description" placeholder="Description de l'expérience/ de la mission professionnelle et, le cas échéant, intitulé de la fonction occupée">${exp.description || ''}</textarea>
      <button type="button" class="btn danger remove-exp">Supprimer</button>`;
    div.querySelector('.add-exp-inline').addEventListener('click', () => {
      addExperienceRow();
      autosaveDebounced();
    });
    div.querySelector('.remove-exp').addEventListener('click', () => {
      div.remove();
      autosaveDebounced();
    });
    div.querySelectorAll('input, textarea').forEach((el) => el.addEventListener('input', autosaveDebounced));
    wrap.appendChild(div);
  }


  function formatFrDate(date = new Date()) {
    const d = String(date.getDate()).padStart(2, '0');
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const y = date.getFullYear();
    return `${d}/${m}/${y}`;
  }

  function toHandwritten(name) {
    return String(name || '').toLowerCase().split('').join(' ');
  }

  function renderSignaturePreview() {
    const nameInput = form.querySelector('[name="engagement.nom_signature"]');
    const traceInput = form.querySelector('[name="engagement.signature_trace"]');
    const dateInput = form.querySelector('[name="engagement.signature_signed_at"]');
    const preview = document.getElementById('signaturePreview');
    const hand = document.getElementById('signatureHandwritten');
    const meta = document.getElementById('signatureMeta');
    const signer = String(nameInput?.value || '').trim();
    const trace = String(traceInput?.value || '').trim();
    const signedAt = String(dateInput?.value || '').trim();

    hand.textContent = trace;
    meta.textContent = trace && signedAt ? `Document signé le ${signedAt} par ${signer}` : '';
    preview.classList.toggle('signed', Boolean(trace && signedAt));
  }

  function signDocument() {
    const nameInput = form.querySelector('[name="engagement.nom_signature"]');
    const traceInput = form.querySelector('[name="engagement.signature_trace"]');
    const dateInput = form.querySelector('[name="engagement.signature_signed_at"]');
    const signer = String(nameInput?.value || '').trim();
    if (!signer) {
      errorsEl.innerHTML = '<div>Veuillez renseigner le nom et prénom avant de signer.</div>';
      return;
    }
    errorsEl.innerHTML = '';
    traceInput.value = toHandwritten(signer);
    dateInput.value = formatFrDate(new Date());
    renderSignaturePreview();
    autosaveDebounced();
  }

  function frontValidate() {
    const payload = getPayload();
    const e = [];
    Object.entries(REQUIRED_CANDIDAT_FIELDS).forEach(([key, label]) => {
      if (!payload.candidat?.[key]) {
        e.push({
          step: 2,
          message: `${label} manquant`,
        });
      }
    });
    if (payload.certification?.vise !== 'complete') e.push('La certification complète est obligatoire');
    if (!experienceDocs.length) {
      e.push({
        step: 4,
        message: 'Au moins un justificatif d’expérience professionnelle doit être déposé',
      });
    }
    const activites = payload.blocs_competences || {};
    for (let idx = 1; idx <= 5; idx += 1) {
      const activite = activites[`activite${idx}`] || {};
      for (let competenceIdx = 1; competenceIdx <= 4; competenceIdx += 1) {
        const competence = activite[`competence${competenceIdx}`] || {};
        if (!String(competence.intitule || '').trim() || !String(competence.statut || '').trim()) {
          e.push({
            step: 5,
            message: `Tous les champs sont obligatoires en 4ème étape (Activité ${idx}, compétence ${competenceIdx})`,
          });
        }
      }
      if (!String(activite.commentaires || '').trim()) {
        e.push({
          step: 5,
          message: `Le commentaire est obligatoire pour l'Activité ${idx}`,
        });
      }
    }
    if (!payload.engagement?.accord_analyse) e.push('accord_analyse obligatoire');
    if (!String(payload.engagement?.lieu_signature || '').trim()) e.push('Lieu de signature obligatoire');
    if (!String(payload.engagement?.date_signature || '').trim()) e.push('Date de signature obligatoire');
    if (!String(payload.engagement?.nom_signature || '').trim()) e.push('Nom et prénom obligatoires');
    if (!String(payload.engagement?.signature_trace || '').trim() || !String(payload.engagement?.signature_signed_at || '').trim()) {
      e.push('Signature électronique obligatoire');
    }
    return e;
  }

  function renderErrors(errors = []) {
    if (!errors.length) {
      errorsEl.innerHTML = '';
      return;
    }
    errorsEl.innerHTML = errors
      .map((error) => {
        if (typeof error === 'string') return `<div>${error}</div>`;
        const stepLabel = STEP_LABELS[error.step] || `Étape ${error.step}`;
        return `<div><strong>${stepLabel}</strong> : ${error.message}</div>`;
      })
      .join('');
  }

  async function submitDossier() {
    if (adminEditMode) {
      errorsEl.innerHTML = '';
      await autosave();
      saveStatus.textContent = 'Dossier mis à jour';
      setTimeout(() => (saveStatus.textContent = ''), 1800);
      return;
    }

    const localErrors = frontValidate();
    if (localErrors.length) {
      renderErrors(localErrors);
      return;
    }
    await autosave();
    const res = await fetch(`/api/vae/${dossierId}/submit`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      renderErrors(data.errors || ['Erreur soumission']);
      return;
    }
    window.location.href = data.redirect_url;
  }

  document.getElementById('addExperience').addEventListener('click', () => {
    addExperienceRow();
    autosaveDebounced();
  });
  document.getElementById('prevStep').addEventListener('click', () => { current = Math.max(0, current - 1); renderStep(); });
  document.getElementById('nextStep').addEventListener('click', () => {
    if (!validateCurrentStep()) return;
    current = Math.min(steps.length - 1, current + 1);
    renderStep();
  });
  document.getElementById('submitDossier').addEventListener('click', () => submitDossier().catch(() => {}));
  document.getElementById('signDocument').addEventListener('click', signDocument);

  form.querySelectorAll('input, select, textarea').forEach((el) => el.addEventListener('input', autosaveDebounced));
  if (experienceDocsInput) {
    experienceDocsInput.addEventListener('change', () => {
      uploadExperienceDocs(experienceDocsInput.files).catch(() => {
        if (experienceDocsStatus) experienceDocsStatus.textContent = 'Erreur lors du téléversement';
      });
      experienceDocsInput.value = '';
    });
  }
  form.querySelectorAll('[name="candidat.statut"]').forEach((el) => {
    el.addEventListener('change', () => {
      updateConventionCollectiveState();
      autosaveDebounced();
    });
  });
  form.querySelector('[name="candidat.prenoms"]').addEventListener('input', () => {
    syncEngagementIdentityAndDate();
    autosaveDebounced();
  });
  form.querySelector('[name="candidat.nom_usage"]').addEventListener('input', () => {
    syncEngagementIdentityAndDate();
    autosaveDebounced();
  });
  form.querySelector('[name="candidat.nom_naissance"]').addEventListener('input', () => {
    syncEngagementIdentityAndDate();
    autosaveDebounced();
  });

  const exp = Array.isArray(initial.experiences) && initial.experiences.length ? initial.experiences : [{}];
  exp.forEach(addExperienceRow);
  renderExperienceDocs();
  syncEngagementIdentityAndDate();
  updateConventionCollectiveState();
  renderStep();
})();
