(() => {
  'use strict';
  document.querySelectorAll('[data-toggle-password]').forEach(button => {
    button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.togglePassword);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.textContent = show ? 'Masquer' : 'Afficher';
      button.setAttribute('aria-pressed', String(show));
      button.setAttribute('aria-label', `${show ? 'Masquer' : 'Afficher'} le mot de passe`);
    });
  });
  const registration = document.querySelector('[data-register-form]');
  if (registration) {
    const password = registration.elements.password;
    const confirmation = registration.elements.password_confirmation;
    const validate = () => confirmation.setCustomValidity(confirmation.value && password.value !== confirmation.value ? 'Les mots de passe ne sont pas identiques.' : '');
    password.addEventListener('input', validate);
    confirmation.addEventListener('input', validate);
  }
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', () => {
    const button = form.querySelector('[data-submit]');
    if (button && form.checkValidity()) { button.disabled = true; button.textContent = 'Enregistrement en cours…'; }
  }));
  window.addEventListener('pageshow', () => document.querySelectorAll('[data-submit]').forEach(button => { button.disabled = false; }));
  const checkout = document.querySelector('[data-checkout]');
  if (checkout) {
    const { checkoutStatus, checkoutUrl, orderUrl } = checkout.dataset;
    // Back from Qonto returns to order tracking, without reopening checkout.
    history.replaceState(null, '', orderUrl);
    let stopped = false;
    let timer;
    const started = Date.now();
    const openPayment = url => {
      const destination = new URL(url);
      if (destination.protocol !== 'https:' || !['pay.qonto.com', 'pay-sandbox.qonto.com'].includes(destination.hostname) || destination.username || destination.password) throw new Error('Invalid payment URL');
      stopped = true;
      window.location.assign(destination.href);
    };
    window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    const poll = async () => {
      if (stopped) return;
      if (Date.now() - started >= 120000) { location.replace(orderUrl); return; }
      try {
        const response = await fetch(checkoutStatus, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(10000) });
        if (stopped) return;
        if (!response.ok || response.redirected) { location.replace(orderUrl); return; }
        const state = await response.json();
        if (stopped) return;
        if (state.payment_url) { openPayment(state.payment_url); return; }
        if (!state.waiting) { location.replace(orderUrl); return; }
      } catch (_) { /* A transient network failure must not resubmit the order. */ }
      timer = setTimeout(poll, 2000);
    };
    if (checkoutUrl) {
      try { openPayment(checkoutUrl); } catch (_) { location.replace(orderUrl); }
    } else poll();
  }
  const pending = document.querySelector('[data-order-pending]');
  if (pending) {
    const key = 'order-wait-' + pending.dataset.orderPending + '-' + pending.dataset.orderPhase;
    const started = Number(sessionStorage.getItem(key)) || Date.now();
    sessionStorage.setItem(key, String(started));
    if (Date.now() - started < 120000) setTimeout(() => location.reload(), 5000);
  }
  const form = document.querySelector('[data-order-form]');
  if (!form) return;
  const billingToggle = form.querySelector('[data-billing-toggle]');
  const updateBilling = () => {
    if (!billingToggle) return;
    form.querySelector('[data-billing-fields]').hidden = !billingToggle.checked;
    ['billing_address','billing_postal_code','billing_city'].forEach(name => { form.elements[name].required = billingToggle.checked; });
  };
  billingToggle?.addEventListener('change', updateBilling);
  updateBilling();
  const money = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
  const inputs = [...form.querySelectorAll('[data-product]')];
  const summary = form.querySelector('[data-cart-lines]');
  const error = form.querySelector('[data-cart-error]');
  function update() {
    let total = 0;
    let invalid = false;
    summary.replaceChildren();
    inputs.forEach(input => {
      const qty = Number(input.value || 0);
      const valid = Number.isInteger(qty) && qty >= 0 && qty <= Number(input.max) && (qty === 0 || input.dataset.kind !== 'manual' || qty >= 50);
      input.setCustomValidity(valid ? '' : 'Choisissez 0 ou au moins 50 exemplaires pour ce manuel.');
      invalid ||= !valid;
      const price = Number(qty >= 100 ? input.dataset.bulkPrice : input.dataset.price);
      const lineTotal = valid ? qty * price : 0;
      const output = input.closest('.quantity-line')?.querySelector('[data-line-total]');
      if (output) output.textContent = valid ? money.format(lineTotal / 100) : '50 minimum';
      if (qty > 0 && valid) {
        total += lineTotal;
        const row = document.createElement('div'); row.className = 'cart-line';
        const label = document.createElement('span'); label.textContent = input.dataset.label;
        const detail = document.createElement('small'); detail.textContent = `${qty} × ${money.format(price / 100)}`;
        label.append(detail);
        const sum = document.createElement('strong'); sum.textContent = money.format(lineTotal / 100);
        row.append(label, sum); summary.append(row);
      }
    });
    if (!summary.childElementCount) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'Choisissez les quantités souhaitées pour commencer.'; summary.append(empty); }
    form.querySelector('[data-cart-total]').textContent = money.format(total / 100);
    error.textContent = invalid ? 'Un manuel se commande à partir de 50 exemplaires.' : '';
  }
  inputs.forEach(input => input.addEventListener('input', update));
  form.querySelectorAll('[name=personalization]').forEach(input => input.addEventListener('change', () => {
    const upload = form.elements.personalization.value === 'upload';
    form.querySelector('[data-logo-area]').hidden = !upload;
    form.elements.logo.required = upload && !form.querySelector('[data-existing-logo]') && inputs.some(el => el.dataset.kind === 'manual' && Number(el.value) > 0);
    if (!upload) form.elements.logo.value = '';
  }));
  form.addEventListener('submit', event => {
    if (!inputs.some(input => Number(input.value) > 0)) {
      event.preventDefault(); error.textContent = 'Choisissez au moins un article.';
      inputs[0].focus();
    }
  });
  update();
})();
