(() => {
  const container = document.querySelector('.vae-container[data-vae-id]');
  if (!container) return;
  const dossierId = container.dataset.vaeId;
  const form = document.getElementById('vaeForm');
  const steps = [...document.querySelectorAll('.step')];
  const progress = document.getElementById('vaeProgress');
  const saveStatus = document.getElementById('saveStatus');
  const errorsEl = document.getElementById('submitErrors');
  const initial = window.__VAE_INITIAL__ || {};
  let current = 0;

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

    const experiences = [...document.querySelectorAll('.experience-item')].map((item) => ({
      date_debut: item.querySelector('[name="exp_date_debut"]').value,
      duree: item.querySelector('[name="exp_duree"]').value,
      description: item.querySelector('[name="exp_description"]').value,
    }));
    payload.experiences = experiences;

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

  function addExperienceRow(exp = { date_debut: '', duree: '', description: '' }) {
    const wrap = document.getElementById('experiencesContainer');
    const div = document.createElement('div');
    div.className = 'experience-item card';
    div.innerHTML = `
      <input type="date" name="exp_date_debut" value="${exp.date_debut || ''}">
      <input name="exp_duree" placeholder="Durée" value="${exp.duree || ''}">
      <textarea name="exp_description" placeholder="Description">${exp.description || ''}</textarea>
      <button type="button" class="btn danger remove-exp">Supprimer</button>`;
    div.querySelector('.remove-exp').addEventListener('click', () => {
      div.remove();
      autosaveDebounced();
    });
    div.querySelectorAll('input, textarea').forEach((el) => el.addEventListener('input', autosaveDebounced));
    wrap.appendChild(div);
  }

  function frontValidate() {
    const payload = getPayload();
    const e = [];
    ['nom_naissance', 'prenoms', 'date_naissance', 'email'].forEach((k) => {
      if (!payload.candidat?.[k]) e.push(`candidat.${k} requis`);
    });
    for (let i = 1; i <= 5; i++) {
      const act = payload.blocs_competences?.[`activite${i}`] || {};
      if (['oui', 'partiellement'].includes(act.statut) && !act.commentaires) e.push(`commentaires activité ${i} requis`);
    }
    if (!payload.engagement?.accord_analyse) e.push('accord_analyse obligatoire');
    return e;
  }

  async function submitDossier() {
    const localErrors = frontValidate();
    if (localErrors.length) {
      errorsEl.innerHTML = localErrors.map((e) => `<div>${e}</div>`).join('');
      return;
    }
    await autosave();
    const res = await fetch(`/api/vae/${dossierId}/submit`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      errorsEl.innerHTML = (data.errors || ['Erreur soumission']).map((e) => `<div>${e}</div>`).join('');
      return;
    }
    window.location.href = data.redirect_url;
  }

  document.getElementById('addExperience').addEventListener('click', () => {
    addExperienceRow();
    autosaveDebounced();
  });
  document.getElementById('prevStep').addEventListener('click', () => { current = Math.max(0, current - 1); renderStep(); });
  document.getElementById('nextStep').addEventListener('click', () => { current = Math.min(steps.length - 1, current + 1); renderStep(); });
  document.getElementById('submitDossier').addEventListener('click', () => submitDossier().catch(() => {}));

  form.querySelectorAll('input, select, textarea').forEach((el) => el.addEventListener('input', autosaveDebounced));
  const exp = Array.isArray(initial.experiences) && initial.experiences.length ? initial.experiences : [{}];
  exp.forEach(addExperienceRow);
  renderStep();
})();
