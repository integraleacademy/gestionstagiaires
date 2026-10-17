(() => {
  'use strict';
  let active = false;
  const safeLocal = value => {
    const url = new URL(value, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/admin/organisme/e-learning/commandes/')) throw new Error('Adresse de commande invalide.');
    return url.href;
  };
  const safePayment = value => {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !['pay.qonto.com', 'pay-sandbox.qonto.com'].includes(url.hostname) || url.username || url.password) throw new Error('Adresse de paiement invalide.');
    return url.href;
  };
  function paymentWindow() {
    // Reserve the window during the user's click, before asynchronous creation.
    // Qonto forbids framing (frame-ancestors 'none'); never proxy its payment UI.
    let popup;
    try {
      const screen = window.screen || {};
      const width = Math.min(600, screen.availWidth || 600), height = Math.min(800, screen.availHeight || 800);
      const left = Math.round((screen.availLeft || 0) + Math.max(0, ((screen.availWidth || width) - width) / 2));
      const top = Math.round((screen.availTop || 0) + Math.max(0, ((screen.availHeight || height) - height) / 2));
      popup = window.open('', '_blank', `popup=yes,width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`);
      if (popup) {
        popup.document.write('<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paiement · Intégrale Connect</title><link rel="stylesheet" href="' + location.origin + '/static/css/elearning-orders.css?v=20261017-followup"><body class="el-popup-preparation"><main class="el-payment-followup"><div class="el-payment-orbit" aria-hidden="true"><span></span></div><p class="eyebrow">INTÉGRALE CONNECT</p><h1>Préparation du paiement en cours</h1><p>Votre page de paiement sécurisé arrive dans quelques instants.</p><p>Après paiement, fermez cette fenêtre pour retrouver votre confirmation.</p></main></body></html>');
        popup.document.close();
        // Qonto must never get an opener capable of navigating our order page.
        popup.opener = null;
      }
    } catch (_) { try { popup?.close(); } catch (_) {} return null; }
    return popup || null;
  }
  function checkout(container, csrf, needsPayment) {
    active = true;
    window.elPaymentInProgress = true;
    const previousFocus = document.activeElement;
    const fallback = document.createElement('section');
    fallback.className = 'form-card el-payment-followup';
    fallback.hidden = true;
    fallback.innerHTML = '<div class="el-payment-orbit" data-payment-spinner aria-hidden="true"><span></span></div><h2 data-payment-title>Préparation du paiement en cours</h2><p data-payment-message role="status">Votre commande est en cours de préparation.</p><div class="action-row"><button class="button primary" type="button" data-payment-resume>Retrouver le paiement</button><button class="button secondary" type="button" data-payment-check hidden>J’ai terminé, vérifier mon paiement</button><a class="button secondary" data-order-open hidden>Consulter ma commande</a></div>';
    container.after(fallback);
    const dialog = document.createElement('dialog');
    dialog.className = 'el-payment-dialog';
    dialog.setAttribute('aria-labelledby', 'el-payment-title');
    dialog.setAttribute('aria-describedby', 'el-payment-message');
    dialog.innerHTML = '<div class="el-payment-dialog-top"><span class="el-payment-brand connect-brand"><span class="connect-brand__mark" aria-hidden="true"><img src="/static/logoic.webp" alt="" width="384" height="144"></span>Intégrale Connect</span><button type="button" class="el-dialog-close" data-payment-close aria-label="Fermer et vérifier le paiement">×</button></div><div class="el-payment-dialog-body"><div class="el-payment-orbit" data-payment-spinner aria-hidden="true"><span></span></div><span class="eyebrow blue">DERNIÈRE ÉTAPE</span><h2 id="el-payment-title" data-payment-title>Préparation du paiement en cours</h2><p id="el-payment-message" data-payment-message role="status">Quelques instants, nous préparons votre paiement sécurisé.</p><div class="el-payment-steps" aria-hidden="true"><span>Commande enregistrée</span><i></i><strong>Paiement sécurisé</strong><i></i><span>Confirmation</span></div><div class="el-payment-actions"><button type="button" class="button primary" data-payment-open hidden>Ouvrir le paiement Qonto</button><button type="button" class="button secondary" data-payment-check hidden>J’ai terminé, vérifier mon paiement</button></div><p class="el-payment-help">Gardez cette page ouverte. Après paiement, fermez la fenêtre Qonto : votre confirmation apparaîtra ici.</p></div>';
    document.body.append(dialog);
    let popup = needsPayment ? paymentWindow() : null;
    // Never leave two overlapping dialogs behind the hosted payment window.
    if (popup) fallback.hidden = false;
    else dialog.showModal();
    let urls, paymentUrl = '', launched = false, dismissed = false, checking = false;
    let stopped = false, disposed = false, busy = false, pendingRefresh = false, timer, watcher;
    let ignoredCloses = 0;
    const started = Date.now();
    const openButton = dialog.querySelector('[data-payment-open]');
    const checkButton = dialog.querySelector('[data-payment-check]');
    function showTracking() {
      fallback.hidden = true;
      if (!dialog.open) dialog.showModal();
    }
    function parkTracking() {
      fallback.hidden = false;
      if (dialog.open) { ignoredCloses++; dialog.close(); }
    }
    function paint(title, message, waiting = true) {
      for (const panel of [dialog, fallback]) {
        panel.querySelector('[data-payment-title]').textContent = title;
        panel.querySelector('[data-payment-message]').textContent = message;
        panel.querySelector('[data-payment-spinner]').hidden = !waiting;
        panel.setAttribute('aria-busy', String(waiting));
      }
    }
    function closePopup() {
      try { if (popup && !popup.closed) popup.close(); } catch (_) {}
      popup = null;
    }
    function stop() {
      stopped = true;
      clearTimeout(timer);
      clearInterval(watcher);
      window.removeEventListener('focus', returned);
      document.removeEventListener('visibilitychange', visible);
    }
    function finish() {
      stop();
      closePopup();
      paint('Paiement confirmé !', 'Votre confirmation est prête…');
      location.assign(urls.confirmation_url);
    }
    function launch() {
      if (!paymentUrl || stopped) return;
      try {
        if (!popup || popup.closed) popup = paymentWindow();
        if (!popup) {
          paint('Votre paiement est prêt', 'Cliquez sur « Ouvrir le paiement Qonto » et autorisez son ouverture pour continuer.', false);
          return;
        }
        popup.location.replace(safePayment(paymentUrl));
        popup.focus();
        launched = true;
        dismissed = false;
        checking = false;
        parkTracking();
        openButton.textContent = 'Retrouver le paiement Qonto';
        paint('Votre paiement est ouvert', 'Réglez votre facture dans la fenêtre Qonto, puis fermez-la pour retrouver votre commande.');
      } catch (_) {
        closePopup();
        paint('Votre paiement est prêt', 'Cliquez sur « Ouvrir le paiement Qonto » pour poursuivre.', false);
      }
    }
    async function poll(refresh = false) {
      if (stopped) return;
      if (!urls || busy) { pendingRefresh = pendingRefresh || refresh; return; }
      clearTimeout(timer);
      busy = true;
      try {
        if (refresh) {
          const body = new FormData(); body.append('csrf_token', csrf);
          const refreshResponse = await fetch(urls.refresh_url, {method: 'POST', credentials: 'same-origin', body, headers: {'Accept': 'application/json'}});
          if (!refreshResponse.ok || refreshResponse.redirected) throw new Error('refresh');
        }
        const response = await fetch(urls.status_url, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (response.redirected || response.status === 401 || response.status === 403) {
          stop(); closePopup(); openButton.hidden = true;
          paint('Retrouvez votre commande', 'Reconnectez-vous à votre espace pour consulter la confirmation.', false);
          fallback.hidden = false;
          return;
        }
        if (!response.ok) throw new Error('status');
        const state = await response.json();
        if (state.paid === true) { finish(); return; }
        paymentUrl = state.checkout_url ? safePayment(state.checkout_url) : '';
        openButton.hidden = !paymentUrl;
        if (state.invoice_status === 'canceled') {
          stop(); closePopup();
          showTracking();
          paint('Commande annulée', 'Cette commande a été annulée. Retrouvez vos autres commandes dans votre espace.', false);
        } else if (state.payment_status === 'partially_paid') {
          paint('Règlement partiel reçu', 'Votre commande sera confirmée après règlement du solde. Consultez le suivi de votre commande.', false);
        } else if (state.payment_status === 'processing' || state.payment_link_status === 'paid' || checking) {
          paint('Vérification du paiement en cours', 'Nous attendons la confirmation de Qonto. Si vous venez de payer, patientez quelques instants.');
        } else if (paymentUrl) {
          if (!launched && !dismissed && popup && !popup.closed) launch();
          else if (!launched) paint('Votre paiement est prêt', 'Cliquez sur « Ouvrir le paiement Qonto » pour régler votre commande.', false);
        } else if (['needs_setup', 'needs_review', 'retry'].includes(state.status)) {
          closePopup();
          showTracking();
          paint('Votre commande est enregistrée', 'La préparation du paiement demande une vérification. Retrouvez son suivi dans votre espace.', false);
        }
      } catch (_) {
        paint('Vérification momentanément indisponible', 'Votre commande est enregistrée. Nous réessayons automatiquement ; vous pouvez aussi la retrouver dans votre espace.', false);
      } finally {
        busy = false;
        if (!stopped && pendingRefresh) { pendingRefresh = false; poll(true); }
        else if (!stopped && Date.now() - started < 30 * 60 * 1000) timer = setTimeout(poll, 3000);
        else if (!stopped) { stop(); paint('Retrouvez votre commande', 'Le suivi reste disponible dans votre espace. Aucun nouveau paiement n’est nécessaire si vous venez de régler.', false); }
      }
    }
    function verify(reveal = false) {
      if (stopped) return;
      if (reveal) showTracking();
      checking = true;
      dismissed = true;
      paint('Vérification du paiement en cours', 'Nous vérifions votre règlement auprès de Qonto…');
      poll(true);
    }
    function returned() { if (launched && !document.hidden) verify(); }
    function visible() { if (!document.hidden) returned(); }
    watcher = setInterval(() => {
      if (popup && popup.closed) { popup = null; verify(true); }
    }, 700);
    window.addEventListener('focus', returned);
    document.addEventListener('visibilitychange', visible);
    dialog.querySelector('[data-payment-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', () => {
      if (ignoredCloses) { ignoredCloses--; return; }
      if (disposed) return;
      fallback.hidden = false;
      closePopup();
      verify();
      fallback.querySelector('[data-payment-resume]').focus();
    });
    fallback.querySelector('[data-payment-resume]').addEventListener('click', () => {
      if (popup && !popup.closed) { popup.focus(); return; }
      showTracking(); poll();
    });
    openButton.addEventListener('click', () => {
      if (popup && !popup.closed && launched) { popup.focus(); return; }
      launch();
    });
    for (const button of [checkButton, fallback.querySelector('[data-payment-check]')]) {
      button.addEventListener('click', () => { closePopup(); verify(true); });
    }
    return {
      start(value) {
        urls = Object.fromEntries(['order_url', 'status_url', 'confirmation_url', 'refresh_url'].map(key => [key, safeLocal(value[key])]));
        const link = fallback.querySelector('[data-order-open]'); link.href = urls.order_url; link.hidden = false;
        window.history.replaceState(null, '', urls.order_url);
        checkButton.hidden = false;
        fallback.querySelector('[data-payment-check]').hidden = false;
        const refresh = pendingRefresh; pendingRefresh = false;
        poll(refresh);
      },
      dispose() {
        disposed = true; stop(); closePopup(); dialog.close(); dialog.remove(); fallback.remove();
        active = false; window.elPaymentInProgress = false;
        previousFocus?.focus();
      }
    };
  }
  document.querySelectorAll('[data-el-checkout]').forEach(form => {
    form.addEventListener('submit', async event => {
      if (active) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      event.preventDefault();
      const flow = checkout(form, form.querySelector('[name="csrf_token"]').value, form.dataset.elFree !== 'true');
      const button = form.querySelector('button[type="submit"]');
      const label = button.textContent;
      form.hidden = true; button.disabled = true;
      try {
        const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', body: new FormData(form), headers: {'Accept': 'application/json'}});
        if (!response.ok || response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Vérifiez les informations et rechargez le récapitulatif avant de réessayer.');
        const urls = await response.json();
        if (form.dataset.elFree === 'true') { location.assign(safeLocal(urls.confirmation_url)); return; }
        flow.start(urls);
      } catch (error) {
        flow.dispose(); form.hidden = false; button.disabled = false; button.textContent = label;
        let notice = form.querySelector('[data-payment-error]');
        if (!notice) { notice = document.createElement('p'); notice.dataset.paymentError = ''; notice.className = 'notice warning'; notice.setAttribute('role', 'alert'); form.prepend(notice); }
        notice.textContent = error.message || 'La validation a été interrompue. Réessayez : votre commande ne sera pas créée en double.';
        notice.scrollIntoView({block: 'center'});
      }
    });
  });
  document.querySelectorAll('[data-el-pay]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    if (active) return;
    const container = link.closest('[data-el-status]');
    if (!container) return;
    const flow = checkout(container, container.querySelector('[name="csrf_token"]').value, true);
    try {
      flow.start({order_url: location.pathname, status_url: container.dataset.elStatus, confirmation_url: container.dataset.elConfirmation, refresh_url: container.dataset.elRefresh});
    } catch (_) { flow.dispose(); }
  }));
})();
