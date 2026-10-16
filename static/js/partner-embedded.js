/* Keep administrative detail forms inside the partner dossier's dialog. */
(function () {
  'use strict';
  function embedded(value) {
    const url = new URL(value, window.location.href);
    if (url.origin === window.location.origin && url.pathname.startsWith('/admin/') && !/\.(pdf|csv|zip)$/.test(url.pathname)) {
      url.searchParams.set('embed', '1');
      return url.pathname + url.search + url.hash;
    }
    return value;
  }
  document.querySelectorAll('form').forEach(form => { form.action = embedded(form.action || window.location.href); });
  document.querySelectorAll('a[href]').forEach(link => {
    if (!link.target && !link.hasAttribute('download')) link.href = embedded(link.href);
  });
})();
