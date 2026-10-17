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
    const popup = window.open('about:blank', '_blank', 'popup,width=1100,height=850');
    if (popup) {
      popup.opener = null;
      popup.document.title = 'Paiement · Intégrale Connect';
      popup.document.body.style.cssText = 'font:18px Arial,sans-serif;color:#18304b;background:#f4f7fb;padding:60px 30px;line-height:1.6';
      const title = popup.document.createElement('h1');
      title.textContent = 'Intégrale Connect';
      const message = popup.document.createElement('p');
      message.textContent = 'Préparation de votre paiement sécurisé… Cette fenêtre va afficher le paiement Qonto.';
      popup.document.body.append(title, message);
    }
    return popup;
  }
  function closePayment(popup) { try { if (popup && !popup.closed) popup.close(); } catch (_) { /* The provider can isolate its window. */ } }
  function followPayment(urls, popup, container) {
    active = true;
    window.elPaymentInProgress = true;
    const statusUrl = safeLocal(urls.status_url);
    const confirmationUrl = safeLocal(urls.confirmation_url);
    const panel = document.createElement('section');
    panel.className = 'form-card el-payment-followup';
    panel.setAttribute('aria-live', 'polite');
    panel.innerHTML = '<span class="eyebrow blue">VOTRE COMMANDE</span><h2>Paiement sécurisé</h2><p data-payment-message>Préparation de votre paiement…</p><p>Cette page confirme automatiquement votre commande dès que votre règlement est validé.</p><div class="action-row"><a class="button primary" data-payment-open hidden target="_blank" rel="noopener noreferrer">Ouvrir le paiement Qonto</a><a class="button secondary" data-order-open>Retrouver ma commande</a></div>';
    panel.querySelector('[data-order-open]').href = safeLocal(urls.order_url);
    container.after(panel);
    container.hidden = true;
    panel.scrollIntoView({behavior: 'smooth', block: 'center'});
    const message = panel.querySelector('[data-payment-message]');
    const payLink = panel.querySelector('[data-payment-open]');
    let launched = false, busy = false, stopped = false, timer;
    const started = Date.now();
    payLink.addEventListener('click', event => {
      event.preventDefault();
      closePayment(popup);
      popup = paymentWindow();
      if (popup) { popup.location.replace(safePayment(payLink.href)); launched = true; }
      else window.open(safePayment(payLink.href), '_blank', 'noopener,noreferrer');
    });
    async function poll() {
      if (busy || stopped) return;
      clearTimeout(timer);
      busy = true;
      try {
        const response = await fetch(statusUrl, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (response.redirected || response.status === 401 || response.status === 403) {
          message.textContent = 'Reconnectez-vous pour retrouver la confirmation de votre commande.';
          stopped = true;
          return;
        }
        if (!response.ok) throw new Error('Suivi temporairement indisponible');
        const state = await response.json();
        if (state.paid) {
          stopped = true;
          message.textContent = 'Paiement reçu. Votre commande est confirmée.';
          closePayment(popup);
          window.focus();
          location.assign(confirmationUrl);
          return;
        }
        if (state.checkout_url) {
          payLink.href = safePayment(state.checkout_url);
          payLink.hidden = false;
          if (!launched && popup && !popup.closed) {
            popup.location.replace(payLink.href);
            launched = true;
          }
          message.textContent = launched ? 'Effectuez votre règlement dans la fenêtre Qonto. Votre confirmation s’affichera ici.' : 'Votre paiement est prêt. Cliquez ci-dessous si la fenêtre ne s’est pas ouverte.';
        } else {
          payLink.hidden = true;
          if (state.payment_status === 'processing' || state.payment_link_status === 'paid') message.textContent = 'Votre paiement est en cours de confirmation. Patientez quelques instants…';
          else if (state.payment_status === 'partially_paid') message.textContent = 'Un règlement partiel a été reçu. Consultez votre commande pour le suivi du solde.';
          else if (state.invoice_status === 'canceled') { message.textContent = 'Cette commande a été annulée.'; stopped = true; closePayment(popup); }
          else if (['needs_setup', 'needs_review', 'retry'].includes(state.status)) message.textContent = 'Votre commande est enregistrée. La préparation du paiement demande une vérification. Vous pouvez retrouver son suivi dans votre espace.';
        }
      } catch (_) {
        message.textContent = 'La vérification du paiement reprend dans quelques instants. Votre commande est enregistrée.';
      } finally {
        busy = false;
        if (!stopped && Date.now() - started < 30 * 60 * 1000) timer = setTimeout(poll, 3000);
        else if (!stopped) message.textContent = 'Retrouvez le suivi et la confirmation de votre paiement dans votre commande.';
      }
    }
    window.addEventListener('focus', poll);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    poll();
  }
  document.querySelectorAll('[data-el-checkout]').forEach(form => {
    form.addEventListener('submit', async event => {
      if (active) { event.preventDefault(); return; }
      if (!form.checkValidity()) return;
      event.preventDefault();
      active = true;
      const popup = form.dataset.elFree === 'true' ? null : paymentWindow();
      const button = form.querySelector('button[type="submit"]');
      const label = button.textContent;
      button.disabled = true;
      button.textContent = 'Validation en cours…';
      try {
        const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', body: new FormData(form), headers: {'Accept': 'application/json'}});
        if (!response.ok || response.redirected || !(response.headers.get('content-type') || '').includes('application/json')) throw new Error('Vérifiez les informations de facturation et rechargez le récapitulatif avant de réessayer.');
        const urls = await response.json();
        if (form.dataset.elFree === 'true') { location.assign(safeLocal(urls.confirmation_url)); return; }
        followPayment(urls, popup, form);
      } catch (error) {
        active = false;
        closePayment(popup);
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
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || active) return;
    const container = link.closest('[data-el-status]');
    if (!container) return;
    event.preventDefault();
    followPayment({order_url: location.pathname, status_url: container.dataset.elStatus, confirmation_url: container.dataset.elConfirmation}, paymentWindow(), container);
  }));
})();
