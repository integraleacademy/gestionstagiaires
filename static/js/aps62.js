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
  root.querySelector('[data-aps-check-sort]')?.addEventListener('click', () => {
    const cards = [...root.querySelectorAll('[data-aps-sort] .aps-sort-card')];
    const labels = {fait:'Ce qui se passe', adapte:'L’action adaptée', ecarter:'L’erreur à éviter'};
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
})();
