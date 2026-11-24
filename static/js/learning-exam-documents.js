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
      .finally(() => { pending = null; });
    return pending;
  }
  panels.forEach(panel => {
    const form = panel.querySelector('form');
    const status = panel.querySelector('[data-learning-status]');
    const list = panel.querySelector('[data-learning-people]');
    const toggle = panel.querySelector('[data-learning-toggle]');
    const print = panel.querySelector('[data-learning-print]');
    const units = panel.querySelector('[data-learning-units]');
    const reportUnit = panel.querySelector('[data-report-unit]');
    const reportLink = panel.querySelector('[data-report-download]');
    const reportStatus = panel.querySelector('[data-report-status]');
    const refresh = panel.querySelector('[data-report-refresh]');
    let requireAll = false, unitCount = 0;
    let people = [], loaded = false, busy = false;
    const checks = () => [...list.querySelectorAll('input[name="trainee_id"]')];
    function updateReportLink() {
      const option = reportUnit.selectedOptions[0];
      reportLink.hidden = !option?.value;
      if (!option?.value) {
        reportLink.removeAttribute('href');
        reportStatus.textContent = 'Le rapport sera disponible dès qu’un stagiaire aura terminé une UV.';
        return;
      }
      reportLink.href = option.value;
      const count = Number(option.dataset.completed);
      reportStatus.textContent = count === 1 ? '1 copie remise pour cette UV.' : `${count} copies remises pour cette UV.`;
    }

    function showReports(allUnits) {
      const previous = reportUnit.value;
      const options = allUnits.filter(unit => unit.report_url).map(unit => {
        const option = new Option(`UV ${String(unit.number).padStart(2, '0')} · ${unit.title}`, unit.report_url);
        option.dataset.completed = unit.completed;
        return option;
      });
      reportUnit.replaceChildren(...(options.length ? options : [new Option('Aucune copie remise', '')]));
      reportUnit.disabled = !options.length;
      if (options.some(option => option.value === previous)) reportUnit.value = previous;
      updateReportLink();
    }
    function update() {
      const number = units?.value || '';
      let printable = 0, blocked = 0;
      checks().forEach(check => {
        const person = people.find(p => String(p.id) === check.value);
        const complete = !requireAll || person.submitted.length === unitCount;
        const available = complete && (!units || person.submitted.some(n => !number || String(n) === number));
        if (check.checked && !complete) blocked++;
        check.disabled = !requireAll && !available;
        if (check.checked && available) printable++;
        const link = check.closest('article').querySelector('[data-learning-individual]');
        const url = new URL(form.action, window.location.origin);
        url.searchParams.set('trainee_id', check.value);
        if (number) url.searchParams.set('uv', number);
        link.href = panel.dataset.learningDocuments === 'attestations' ? person.certificate_url : url.href;
        link.hidden = !available;
        check.closest('article').querySelector('[data-learning-empty]').hidden = available;
      });
      panel.querySelector('[data-learning-count]').textContent = `${checks().filter(c => c.checked && !c.disabled).length} stagiaire(s) sélectionné(s)`;
      toggle.textContent = checks().some(c => c.checked && !c.disabled) ? 'Tout désélectionner' : 'Tout sélectionner';
      print.disabled = !printable || blocked > 0;
      toggle.disabled = !people.length;
      status.textContent = blocked ? `Impression bloquée : ${blocked} stagiaire(s) sélectionné(s) doivent encore terminer des questionnaires.` : people.length ? (requireAll ? 'Tous les questionnaires de chaque stagiaire sélectionné doivent être terminés avant impression.' : units ? 'Seules les réponses aux questionnaires terminés sont imprimées.' : 'Chaque PDF s’ouvre dans un nouvel onglet : utilisez ensuite le bouton Imprimer du lecteur PDF.') : 'Aucun stagiaire actif dans cette session.';
    }
    async function load() {
      if (busy || (loaded && !reportUnit)) return;
      busy = true;
      if (refresh) refresh.disabled = true;
      try {
        const payload = await data();
        const previousChecks = new Map(checks().map(check => [check.value, check.checked]));
        people = payload.people;
        requireAll = Boolean(units && payload.require_all_uv);
        unitCount = payload.units.length;
        if (units && !loaded) units.insertAdjacentHTML('beforeend', payload.units.map(u => `<option value="${u.number}">UV ${String(u.number).padStart(2,'0')} · ${esc(u.title)}</option>`).join(''));
        if (reportUnit) showReports(payload.units);
        list.innerHTML = people.map(p => `<article class="exam-card" style="padding:12px 16px;margin-bottom:8px;"><div class="exam-candidate-top"><label class="exam-check"><input type="checkbox" name="trainee_id" value="${esc(p.id)}" checked><strong>${esc(p.name)}</strong></label><div class="exam-actions">${units ? `<span class="exam-muted">Questionnaires terminés : ${p.submitted.length} / ${payload.units.length}</span>` : ''}<a class="btn btn-outline" target="_blank" rel="noopener" data-learning-individual>Imprimer individuellement ↗</a><span class="exam-muted" data-learning-empty hidden>${requireAll ? 'Questionnaires incomplets' : 'Aucun questionnaire terminé'}</span></div></div></article>`).join('');
        checks().forEach(check => {
          if (previousChecks.has(check.value)) check.checked = previousChecks.get(check.value);
        });
        loaded = true;
        update();
      } catch (error) {
        status.textContent = error.message;
        if (reportStatus) reportStatus.textContent = 'Impossible de charger les résultats. Cliquez sur Actualiser pour réessayer.';
      } finally {
        busy = false;
        if (refresh) refresh.disabled = false;
      }
    }
    dialog.querySelector(`[data-security-tab="${panel.dataset.securityPanel}"]`).addEventListener('click', load);
    refresh?.addEventListener('click', load);
    reportUnit?.addEventListener('change', updateReportLink);
    form.addEventListener('change', update);
    toggle.addEventListener('click', () => { const enabled = checks().filter(c => !c.disabled); const selected = enabled.some(c => c.checked); enabled.forEach(c => { c.checked = !selected; }); update(); });
    form.addEventListener('submit', event => {
      if (print.disabled || !checks().some(c => c.checked && !c.disabled)) { event.preventDefault(); return; }
    });
  });
})();
