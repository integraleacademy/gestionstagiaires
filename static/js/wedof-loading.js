(() => {
  const modal = document.querySelector('#wedof-loading-modal');
  if (!modal) return;

  let pendingRequests = 0;
  const show = () => {
    pendingRequests += 1;
    if (!modal.open) modal.showModal();
  };
  const hide = () => {
    pendingRequests = Math.max(0, pendingRequests - 1);
    if (pendingRequests === 0 && modal.open) modal.close();
  };

  modal.addEventListener('cancel', event => event.preventDefault());
  document.querySelectorAll('form[action^="/admin/wedof"]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!event.defaultPrevented && form.checkValidity()) show();
    });
  });

  window.WedofLoading = {show, hide};
})();
