(() => {
  'use strict';
  const root = document.querySelector('[data-aps-work]');
  if (!root) return;
  const dialog = document.getElementById('apsImageDialog');
  root.querySelectorAll('[data-aps-image]').forEach(button => button.addEventListener('click', () => {
    dialog.querySelector('img').src = button.dataset.apsImage;
    dialog.querySelector('img').alt = button.querySelector('img').alt;
    dialog.showModal();
  }));
  dialog?.querySelector('[data-aps-close]')?.addEventListener('click', () => dialog.close());
  dialog?.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  root.querySelectorAll('[data-aps-choice]').forEach(button => button.addEventListener('click', () => {
    root.querySelectorAll('[data-aps-choice]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
    const feedback = root.querySelector('.aps-decision-feedback');
    feedback.hidden = false;
    feedback.dataset.correct = button.dataset.correct;
    feedback.textContent = (button.dataset.correct === 'true' ? 'Décision adaptée. ' : 'Décision à réexaminer. ') + button.dataset.feedback;
  }));
  const field = document.getElementById('apsReflection');
  root.querySelector('[data-aps-check-sort]')?.addEventListener('click', () => {
    const cards = [...root.querySelectorAll('[data-aps-sort] .aps-sort-card')];
    const labels = {fait:'Fait de la situation', adapte:'Action adaptée', ecarter:'Décision à écarter'};
    let correct = 0;
    cards.forEach(card => {
      const value = card.querySelector('select').value;
      const valid = value === card.dataset.category;
      correct += Number(valid); card.dataset.correct = String(valid);
      const feedback = card.querySelector('.aps-sort-feedback'); feedback.hidden = false;
      feedback.textContent = valid ? '✓ Classement juste.' : `À revoir : ${labels[card.dataset.category]}. Relisez le raisonnement du dossier.`;
    });
    root.querySelector('[data-aps-sort-result]').textContent = `${correct} carte${correct > 1 ? 's' : ''} bien classée${correct > 1 ? 's' : ''} sur ${cards.length}. Vous pouvez modifier vos choix et recommencer.`;
  });
  if (!field) return;
  const preview = Boolean(document.getElementById('nativePreviewConfig'));
  const key = `aps62-work:${location.pathname}:${document.querySelector('[data-activity-id]').dataset.activityId}`;
  const draftStatus = root.querySelector('[data-aps-draft-status]');
  if (!preview && !field.value && !field.readOnly) {
    try { field.value = sessionStorage.getItem(key) || ''; } catch (_) { /* storage may be disabled */ }
  }
  const count = () => {
    const length = field.value.trim().length;
    root.querySelector('[data-aps-char-count]').textContent = `${length} caractères rédigés`;
  };
  field.addEventListener('input', () => {
    count();
    if (preview) return;
    try { sessionStorage.setItem(key, field.value); draftStatus.textContent = 'Brouillon conservé dans cet onglet.'; }
    catch (_) { draftStatus.textContent = 'Brouillon non sauvegardé : terminez l’activité pour l’enregistrer.'; }
  });
  if (field.readOnly) { try { sessionStorage.removeItem(key); } catch (_) {} }
  count();
  root.querySelector('[data-aps-download]')?.addEventListener('click', () => {
    const title = document.querySelector('.native-activity__header h1').textContent;
    const blob = new Blob([`${title}\n\n${field.value}`], {type:'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'APS-mon-travail.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
})();
