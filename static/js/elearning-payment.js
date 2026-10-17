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
  function preparation(container) {
    active = true;
    window.elPaymentInProgress = true;
    const panel = document.createElement('section');
    panel.className = 'form-card el-payment-followup';
    panel.setAttribute('aria-live', 'polite');
    panel.setAttribute('aria-busy', 'true');
    panel.innerHTML = '<div class="el-payment-orbit" aria-hidden="true"><span></span></div><span class="eyebrow blue">PAIEMENT SÉCURISÉ</span><h2 data-payment-title>Préparation du paiement en cours</h2><p data-payment-message>Quelques instants, nous préparons votre paiement sécurisé.</p><p class="small">Le paiement Qonto s’affichera automatiquement dans cet onglet.</p><div class="action-row"><a class="button primary" data-payment-open hidden rel="noreferrer">Continuer vers le paiement</a><a class="button secondary" data-order-open hidden>Retrouver ma commande</a></div>';
    container.after(panel);
    container.hidden = true;
    panel.scrollIntoView({behavior: 'smooth', block: 'center'});
    return panel;
  }
  function followPayment(urls, panel) {
    const statusUrl = safeLocal(urls.status_url);
    const confirmationUrl = safeLocal(urls.confirmation_url);
    const orderUrl = safeLocal(urls.order_url);
    const orderLink = panel.querySelector('[data-order-open]');
    orderLink.href = orderUrl;
    orderLink.hidden = false;
    // Back or reload must restore the existing order, never the submitted quote.
    window.history.replaceState(null, '', orderUrl);
    const message = panel.querySelector('[data-payment-message]');
    const title = panel.querySelector('[data-payment-title]');
    const payLink = panel.querySelector('[data-payment-open]');
    const spinner = panel.querySelector('.el-payment-orbit');
    let launched = false, leaving = false, busy = false, stopped = false, timer;
    const started = Date.now();
    function waiting(value) {
      spinner.hidden = !value;
      panel.setAttribute('aria-busy', String(value));
    }
    function openPayment() {
      const paymentUrl = safePayment(payLink.href);
      launched = true;
      leaving = true;
      title.textContent = 'Ouverture du paiement sécurisé';
      message.textContent = 'Vous allez régler votre commande sur Qonto.';
      waiting(true);
      location.assign(paymentUrl);
    }
    payLink.addEventListener('click', event => { event.preventDefault(); openPayment(); });
    async function poll() {
      if (busy || stopped || leaving) return;
      clearTimeout(timer);
      busy = true;
      try {
        const response = await fetch(statusUrl, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (response.redirected || response.status === 401 || response.status === 403) {
          title.textContent = 'Retrouvez votre commande';
          message.textContent = 'Reconnectez-vous pour consulter la confirmation de votre commande.';
          stopped = true;
          waiting(false);
          return;
        }
        if (!response.ok) throw new Error('Suivi temporairement indisponible');
        const state = await response.json();
        if (state.paid) {
          stopped = true;
          title.textContent = 'Commande confirmée';
          message.textContent = 'Paiement reçu. Nous affichons votre confirmation.';
          location.assign(confirmationUrl);
          return;
        }
        if (state.checkout_url) {
          payLink.href = safePayment(state.checkout_url);
          payLink.hidden = false;
          if (!launched) { openPayment(); return; }
          title.textContent = 'Suivi de votre paiement';
          message.textContent = 'Si vous avez réglé, la confirmation apparaîtra dès validation du paiement. Vous pouvez aussi reprendre un paiement interrompu.';
          waiting(false);
        } else {
          payLink.hidden = true;
          waiting(true);
          if (state.payment_status === 'processing' || state.payment_link_status === 'paid') {
            title.textContent = 'Confirmation du paiement en cours';
            message.textContent = 'Votre règlement est en cours de vérification. Patientez quelques instants…';
          } else if (state.payment_status === 'partially_paid') {
            title.textContent = 'Règlement partiel reçu';
            message.textContent = 'Consultez votre commande pour le suivi du solde.';
            waiting(false);
          } else if (state.invoice_status === 'canceled') {
            title.textContent = 'Commande annulée';
            message.textContent = 'Cette commande a été annulée.';
            stopped = true;
            waiting(false);
          } else if (['needs_setup', 'needs_review', 'retry'].includes(state.status)) {
            title.textContent = 'Votre commande est enregistrée';
            message.textContent = 'La préparation du paiement demande une vérification. Retrouvez son suivi dans votre espace.';
            waiting(false);
          }
        }
      } catch (_) {
        title.textContent = 'Vérification en cours';
        message.textContent = 'La vérification reprend dans quelques instants. Votre commande est enregistrée.';
      } finally {
        busy = false;
        if (!stopped && !leaving && Date.now() - started < 30 * 60 * 1000) timer = setTimeout(poll, 3000);
        else if (!stopped && !leaving) { message.textContent = 'Retrouvez le suivi et la confirmation de votre paiement dans votre commande.'; waiting(false); }
      }
    }
    // Qonto's invoice page has no documented return URL. If the browser restores
    // this page from its cache, refresh payment status without reopening Qonto.
    window.addEventListener('pageshow', event => {
      if (event.persisted) { leaving = false; launched = true; stopped = false; poll(); }
    });
    window.addEventListener('focus', poll);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    poll();
  }
  document.querySelectorAll('[data-el-checkout]').forEach(form => {
    form.addEventListener('submit', async event => {
      if (active) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      event.preventDefault();
      const panel = preparation(form);
      const button = form.querySelector('button[type="submit"]');
      const label = button.textContent;
      button.disabled = true;
      button.textContent = 'Validation en cours…';
      try {
        const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', body: new FormData(form), headers: {'Accept': 'application/json'}});
        if (!response.ok || response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Vérifiez les informations et rechargez le récapitulatif avant de réessayer.');
        const urls = await response.json();
        if (form.dataset.elFree === 'true') { location.assign(safeLocal(urls.confirmation_url)); return; }
        followPayment(urls, panel);
      } catch (error) {
        active = false;
        window.elPaymentInProgress = false;
        panel.remove();
        form.hidden = false;
        button.disabled = false;
        button.textContent = label;
        let notice = form.querySelector('[data-payment-error]');
        if (!notice) { notice = document.createElement('p'); notice.dataset.paymentError = ''; notice.className = 'notice warning'; notice.setAttribute('role', 'alert'); form.prepend(notice); }
        notice.textContent = error.message || 'La validation a été interrompue. Réessayez : votre commande ne sera pas créée en double.';
        notice.scrollIntoView({block: 'center'});
      }
    });
  });
  document.querySelectorAll('[data-el-pay]').forEach(link => link.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (active) return;
    const container = link.closest('[data-el-status]');
    if (!container) { location.assign(safePayment(link.href)); return; }
    followPayment({order_url: location.pathname, status_url: container.dataset.elStatus, confirmation_url: container.dataset.elConfirmation}, preparation(container));
  }));
})();
