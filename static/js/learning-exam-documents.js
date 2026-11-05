(() => {
  'use strict';
  const dialog = document.getElementById('securityExamDialog');
  if (!dialog) return;
  const panels = [...dialog.querySelectorAll('[data-learning-documents]')];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let pending;
  function data() {
    if (!pending) pending = fetch(panels[0].dataset.source, {headers:{Accept:'application/json'}, cache:'no-store'})
      .then(async response => { if (!response.ok) throw new Error('Les documents sont indisponibles. Fermez puis rouvrez le dossier pour réessayer.'); return response.json(); })
      .catch(error => { pending = null; throw error; });
    return pending;
  }
  panels.forEach(panel => {
    const form = panel.querySelector('form');
    const status = panel.querySelector('[data-learning-status]');
    const list = panel.querySelector('[data-learning-people]');
    const toggle = panel.querySelector('[data-learning-toggle]');
    const print = panel.querySelector('[data-learning-print]');
    const units = panel.querySelector('[data-learning-units]');
    let requireAll = false, unitCount = 0;
    let people = [], loaded = false, busy = false;
    const checks = () => [...list.querySelectorAll('input[name="trainee_id"]')];
    function update() {
      const mode = form.elements.mode?.value || '';
      const number = units?.value || '';
      let printable = 0, blocked = 0;
      checks().forEach(check => {
        const person = people.find(p => String(p.id) === check.value);
        const complete = !requireAll || person.submitted.length === unitCount;
        const available = complete && (mode !== 'answers' || person.submitted.some(n => !number || String(n) === number));
        if (check.checked && !complete) blocked++;
        check.disabled = !requireAll && !available;
        if (check.checked && available) printable++;
        const link = check.closest('article').querySelector('[data-learning-individual]');
        const url = new URL(form.action, window.location.origin);
        url.searchParams.set('trainee_id', check.value);
        if (mode) url.searchParams.set('mode', mode);
        if (number) url.searchParams.set('uv', number);
        link.href = panel.dataset.learningDocuments === 'attestations' ? person.certificate_url : url.href;
        link.hidden = !available;
        check.closest('article').querySelector('[data-learning-empty]').hidden = available;
      });
      panel.querySelector('[data-learning-count]').textContent = `${checks().filter(c => c.checked && !c.disabled).length} stagiaire(s) sélectionné(s)`;
      toggle.textContent = checks().some(c => c.checked && !c.disabled) ? 'Tout désélectionner' : 'Tout sélectionner';
      print.disabled = !printable || blocked > 0;
      toggle.disabled = !people.length;
      status.textContent = blocked ? `Impression bloquée : ${blocked} stagiaire(s) sélectionné(s) doivent encore remettre des questionnaires.` : people.length ? (requireAll ? 'Tous les questionnaires de chaque stagiaire sélectionné doivent être remis avant impression.' : mode === 'answers' ? 'Seules les copies déjà remises sont imprimées. Les questionnaires non réalisés sont exclus.' : 'Chaque PDF s’ouvre dans un nouvel onglet : utilisez ensuite le bouton Imprimer du lecteur PDF.') : 'Aucun stagiaire actif dans cette session.';
    }
    async function load() {
      if (loaded || busy) return;
      busy = true;
      try {
        const payload = await data();
        people = payload.people;
        requireAll = Boolean(units && payload.require_all_uv);
        unitCount = payload.units.length;
        if (units) units.insertAdjacentHTML('beforeend', payload.units.map(u => `<option value="${u.number}">UV ${String(u.number).padStart(2,'0')} · ${esc(u.title)}</option>`).join(''));
        list.innerHTML = people.map(p => `<article class="exam-card" style="padding:12px 16px;margin-bottom:8px;"><div class="exam-candidate-top"><label class="exam-check"><input type="checkbox" name="trainee_id" value="${esc(p.id)}" checked><strong>${esc(p.name)}</strong></label><div class="exam-actions">${units ? `<span class="exam-muted">${p.submitted.length} / ${payload.units.length} UV remises</span>` : ''}<a class="btn btn-outline" target="_blank" rel="noopener" data-learning-individual>Imprimer individuellement ↗</a><span class="exam-muted" data-learning-empty hidden>${requireAll ? 'Questionnaires incomplets' : 'Aucune copie remise'}</span></div></div></article>`).join('');
        loaded = true;
        update();
      } catch (error) { status.textContent = error.message; }
      finally { busy = false; }
    }
    dialog.querySelector(`[data-security-tab="${panel.dataset.securityPanel}"]`).addEventListener('click', load);
    form.addEventListener('change', update);
    toggle.addEventListener('click', () => { const enabled = checks().filter(c => !c.disabled); const selected = enabled.some(c => c.checked); enabled.forEach(c => { c.checked = !selected; }); update(); });
    form.addEventListener('submit', event => {
      if (print.disabled || !checks().some(c => c.checked && !c.disabled)) { event.preventDefault(); return; }
    });
  });
})();
