(() => {
  const modal = document.querySelector('#wedof-loading-modal');
  if (!modal) return;

  const tokens = new Set();
  let safetyTimer;
  let rescueTimer;
  const closeButton = document.querySelector('#wedof-loading-close');
  const description = document.querySelector('#wedof-loading-description');
  const show = () => {
    const token = Symbol('wedof-loading');
    tokens.add(token);
    if (!modal.open) modal.showModal();
    if (closeButton) closeButton.hidden = true;
    clearTimeout(rescueTimer);
    rescueTimer = setTimeout(() => { if (closeButton && tokens.size) closeButton.hidden = false; }, 10000);
    clearTimeout(safetyTimer);
    safetyTimer = setTimeout(() => {
      if (description) description.textContent = 'Le traitement prend plus de temps que prévu. Vous pouvez réessayer.';
      forceHide();
    }, 45000);
    return token;
  };
  const hide = token => {
    if (!tokens.delete(token)) return;
    if (tokens.size === 0) forceHide();
  };
  const forceHide = () => {
    tokens.clear();
    clearTimeout(safetyTimer);
    clearTimeout(rescueTimer);
    if (closeButton) closeButton.hidden = true;
    if (modal.open) modal.close();
  };

  modal.addEventListener('cancel', event => { if (tokens.size && closeButton?.hidden) event.preventDefault(); else forceHide(); });
  closeButton?.addEventListener('click', forceHide);
  document.querySelectorAll('form[action^="/admin/wedof"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (form.matches('#wedof-manual-form, [data-wedof-loading-managed], [data-wedof-no-global-loading]')) return;
      if (!event.defaultPrevented && form.checkValidity()) show();
    });
  });
  window.addEventListener('pageshow', forceHide);

  window.WedofLoading = {show, hide, forceHide, pendingCount: () => tokens.size};
})();
