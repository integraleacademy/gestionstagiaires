(() => {
  'use strict';
  const panel = document.querySelector('[data-desp-scotia-url]');
  if (!panel) return;
  const area = panel.querySelector('[data-scotia-candidates]');
  const status = panel.querySelector('[data-scotia-status]');
  const refresh = panel.querySelector('[data-scotia-refresh]');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    refresh.disabled = true;
    area.replaceChildren();
    status.textContent = 'Vérification des pièces en cours…';
    panel.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(panel.dataset.despScotiaUrl, {credentials:'same-origin', cache:'no-store'});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Les dossiers ne sont pas disponibles. Actualisez la page ou reconnectez-vous.');
      const data = await response.json();
      if (!data.ok) throw new Error(data.error);
      const count = data.candidates.filter(row => row.ready).length;
      status.textContent = `${count} dossier${count > 1 ? 's' : ''} complet${count > 1 ? 's' : ''} sur ${data.candidates.length}`;
      area.innerHTML = data.candidates.map(row => `<article class="exam-card">
        <div class="exam-candidate-top"><div><h4 class="exam-candidate-name">${esc(row.name)}</h4><span class="exam-muted">${row.ready ? 'Dossier complet' : 'Dossier à compléter'}</span></div>
        ${row.ready && row.download_url
          ? `<a class="btn btn-primary" href="${esc(row.download_url)}" target="_blank" rel="noopener" aria-label="Ouvrir le dossier SCOTIA de ${esc(row.name)} dans un nouvel onglet">Ouvrir le dossier SCOTIA</a>`
          : '<button type="button" class="btn btn-primary" disabled>Ouvrir le dossier SCOTIA</button>'}</div>
        <div class="exam-chips">${row.documents.map(doc => `<span class="exam-chip ${doc.available ? 'ok' : 'warn'}">${doc.available ? '✓' : '!'} ${esc(doc.label)}</span>`).join('')}</div>
        ${row.documents.filter(doc => !doc.available).map(doc => `<p class="exam-muted">${esc(doc.label)} : ${esc(doc.error)}</p>`).join('')}
        <a href="${esc(row.edit_url)}" target="_blank" rel="noopener">Ouvrir la fiche du stagiaire</a></article>`).join('') || '<p class="exam-empty">Aucun stagiaire inscrit dans cette session.</p>';
    } catch (error) { status.textContent = error.message; }
    finally { loading = false; refresh.disabled = false; panel.removeAttribute('aria-busy'); }
  }
  const certificates = document.querySelector('[data-certificates-url]');
  const list = certificates.querySelector('[data-certificate-list]');
  const listStatus = certificates.querySelector('[data-certificate-list-status]');
  const viewLink = url => `<a href="${esc(url)}" target="_blank" rel="noopener">Voir l’attestation</a>`;
  async function loadCertificates() {
    listStatus.textContent = 'Chargement des attestations…';
    try {
      const response = await fetch(certificates.dataset.certificatesUrl, {cache:'no-store'});
      if (!response.ok) throw new Error();
      const {candidates} = await response.json();
      list.innerHTML = candidates.map(row => `<article class="exam-card">
        <div class="exam-candidate-top"><h4>${esc(row.name)}</h4><span data-certificate-link>${row.available ? viewLink(row.url) : 'À déposer'}</span></div>
        ${certificates.dataset.readOnly === '1' ? '' : `<form data-upload-url="${esc(row.url)}" class="exam-actions">
          <input type="file" name="certificate" accept=".pdf,application/pdf" required aria-label="Attestation de ${esc(row.name)}">
          <button class="btn btn-primary" type="submit">${row.available ? 'Remplacer le PDF' : 'Déposer le PDF'}</button></form>`}
        <p role="status"></p></article>`).join('');
      listStatus.textContent = candidates.length ? '' : 'Aucun stagiaire inscrit dans cette session.';
    } catch {
      listStatus.textContent = 'Impossible de charger les attestations. Rouvrez l’onglet pour réessayer.';
    }
  }
  list.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.target;
    const card = form.closest('article');
    const feedback = card.querySelector('[role="status"]');
    const button = form.querySelector('button');
    const body = new FormData(form);
    body.set('document_check_token', certificates.dataset.token);
    button.disabled = true;
    feedback.textContent = 'Envoi du PDF…';
    try {
      const response = await fetch(form.dataset.uploadUrl, {method:'POST', body, headers:{Accept:'application/json'}});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.error || 'Le dépôt a échoué. Rechargez la page puis réessayez.');
      card.querySelector('[data-certificate-link]').innerHTML = viewLink(form.dataset.uploadUrl);
      form.reset();
      button.textContent = 'Remplacer le PDF';
      feedback.textContent = 'Attestation enregistrée.';
    } catch (error) { feedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.getElementById('btnSsiapExam')?.addEventListener('click', () => panel.hidden ? loadCertificates() : load());
  document.querySelector('[data-exam-tab="certificates"]').addEventListener('click', loadCertificates);
  document.querySelector('[data-exam-tab="scotia"]').addEventListener('click', load);
  refresh.addEventListener('click', load);
})();
