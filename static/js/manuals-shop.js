(() => {
  'use strict';
  const menu = document.querySelector('[data-navigation-toggle]');
  const navigation = document.getElementById('primary-navigation');
  if (menu && navigation) {
    // Keep this breakpoint aligned with connect-responsive.css.
    const mobile = window.matchMedia('(max-width:1100px)');
    const label = menu.querySelector('[data-navigation-label]');
    const setMenu = (open) => {
      navigation.hidden = !open;
      menu.setAttribute('aria-expanded', String(open));
      if (label) label.textContent = open ? 'Fermer' : 'Menu';
    };
    const resetMenu = () => {
      menu.hidden = !mobile.matches;
      setMenu(!mobile.matches);
    };
    menu.addEventListener('click', () => setMenu(navigation.hidden));
    navigation.addEventListener('click', event => {
      if (mobile.matches && event.target.closest('a')) setMenu(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && mobile.matches && !navigation.hidden) {
        setMenu(false);
        menu.focus();
      }
    });
    document.addEventListener('click', event => {
      if (mobile.matches && !navigation.hidden && !menu.contains(event.target) && !navigation.contains(event.target)) setMenu(false);
    });
    mobile.addEventListener('change', resetMenu);
    resetMenu();
  }
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
  const clear = document.querySelector('[data-cart-complete]');
  if (clear) { try { localStorage.removeItem('integrale-cart-v1:' + clear.dataset.cartComplete); } catch (_) {} }
  const form = document.querySelector('[data-order-form]');
  if (!form) return;
  form.noValidate = true; // Reveal the correct step/category before native validation.
  const inputs = [...form.querySelectorAll('[data-product]')];
  const key = 'integrale-cart-v1:' + form.dataset.cartKey;
  const steps = [...form.querySelectorAll('[data-checkout-step]')];
  const money = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
  const summary = form.querySelector('[data-cart-lines]');
  const error = form.querySelector('[data-cart-error]');
  let restored = false;
  let counted = false;
  if (form.dataset.restore !== 'no') {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      if (saved && Date.now() - saved.updated < 30 * 86400000) {
        inputs.forEach(input => { if (/^\d{1,5}$/.test(String(saved.quantities[input.name]))) input.value = saved.quantities[input.name]; });
        restored = true;
        counted = !!saved.counted;
      } else localStorage.removeItem(key);
    } catch (_) {}
  }
  const article = new URLSearchParams(location.search).get('article');
  if (article && form.elements[article]?.hasAttribute('data-product') && !Number(form.elements[article].value)) {
    form.elements[article].value = form.elements[article].dataset.kind === 'manual' ? '50' : '1';
  }
  function save() {
    if (!counted && inputs.some(input => Number(input.value) > 0)) {
      counted = true;
      const event = new FormData(); event.set('csrf_token', form.elements.csrf_token.value);
      fetch('/admin/manuels/evenement-panier', {method:'POST',body:event,credentials:'same-origin',keepalive:true}).catch(() => {});
    }
    try {
      localStorage.setItem(key, JSON.stringify({ updated: Date.now(), counted, quantities: Object.fromEntries(inputs.map(input => [input.name, input.value])) }));
    } catch (_) { form.querySelector('[data-basket-status]').textContent = 'La sauvegarde locale est indisponible sur cet appareil.'; }
  }
  function showStep(name, scroll = true) {
    steps.forEach(step => { step.hidden = step.dataset.checkoutStep !== name; });
    form.querySelectorAll('.checkout-steps [data-step-go]').forEach(button => {
      if (button.dataset.stepGo === name) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    });
    const bar = form.querySelector('[data-basket-bar]');
    bar.hidden = name !== 'selection';
    if (scroll) form.querySelector(`[data-checkout-step="${name}"]`).scrollIntoView({block: 'start'});
  }
  function reveal(input) {
    const step = input.closest('[data-checkout-step]');
    if (step) showStep(step.dataset.checkoutStep, false);
    const card = input.closest('[data-catalogue-card]');
    if (card) card.closest('[data-catalogue]').dispatchEvent(new CustomEvent('catalogue:reveal', {detail: {category: card.dataset.category}}));
    input.scrollIntoView({block: 'center'}); input.focus(); input.reportValidity();
  }
  function validateSelection() {
    update();
    const invalid = inputs.find(input => !input.validity.valid);
    if (invalid) { reveal(invalid); return false; }
    if (!inputs.some(input => Number(input.value) > 0)) {
      error.textContent = 'Choisissez au moins un article.';
      inputs[0].setCustomValidity('Choisissez au moins un article pour continuer.'); reveal(inputs[0]); return false;
    }
    return true;
  }
  const billingToggle = form.querySelector('[data-billing-toggle]');
  function updateOptions() {
    if (billingToggle) {
      form.querySelector('[data-billing-fields]').hidden = !billingToggle.checked;
      ['billing_address','billing_postal_code','billing_city'].forEach(name => { form.elements[name].required = billingToggle.checked; });
    }
    const upload = form.elements.personalization.value === 'upload';
    form.querySelector('[data-logo-area]').hidden = !upload;
    form.elements.logo.required = upload && !form.querySelector('[data-existing-logo]') && inputs.some(el => el.dataset.kind === 'manual' && Number(el.value) > 0);
  }
  function update() {
    let total = 0, invalid = false;
    summary.replaceChildren();
    inputs.forEach(input => {
      const qty = Number(input.value || 0);
      const valid = !input.validity.badInput && Number.isInteger(qty) && qty >= 0 && qty <= Number(input.max) && (qty === 0 || input.dataset.kind !== 'manual' || qty >= 50);
      const message = input.dataset.kind === 'manual' ? 'Choisissez 0 ou de 50 à 10 000 exemplaires.' : 'Choisissez un nombre entier de 0 à 100 clés USB.';
      input.setCustomValidity(valid ? '' : message);
      input.setAttribute('aria-invalid', String(!valid));
      invalid ||= !valid;
      const price = Number(qty >= 100 ? input.dataset.bulkPrice : input.dataset.price);
      const lineTotal = valid ? qty * price : 0;
      const output = input.closest('.quantity-line')?.querySelector('[data-line-total]');
      if (output) output.textContent = valid ? money.format(lineTotal / 100) : 'Quantité à corriger';
      if (qty > 0 && valid) {
        total += lineTotal;
        const row = document.createElement('div'); row.className = 'cart-line';
        const label = document.createElement('span'); label.textContent = input.dataset.label;
        const detail = document.createElement('small'); detail.textContent = `${qty} × ${money.format(price / 100)}`; label.append(detail);
        const sum = document.createElement('strong'); sum.textContent = money.format(lineTotal / 100);
        const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'text-link'; edit.textContent = 'Modifier'; edit.setAttribute('aria-label', 'Modifier ' + input.dataset.label); edit.addEventListener('click', () => reveal(input));
        row.append(label, sum, edit); summary.append(row);
      }
    });
    if (!summary.childElementCount) { const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = 'Choisissez les quantités souhaitées pour commencer.'; summary.append(empty); }
    form.querySelectorAll('[data-cart-total],[data-basket-total]').forEach(output => { output.textContent = money.format(total / 100); });
    error.textContent = invalid ? 'Une quantité doit être corrigée. Cliquez sur Continuer pour retrouver l’article.' : '';
    updateOptions();
  }
  inputs.forEach(input => input.addEventListener('input', () => { update(); save(); }));
  form.querySelectorAll('[data-step-go]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.stepGo === 'selection' || validateSelection()) showStep(button.dataset.stepGo);
  }));
  form.querySelector('[data-cart-clear]').addEventListener('click', () => { inputs.forEach(input => { input.value = '0'; }); counted = false; update(); save(); });
  form.querySelectorAll('[name=personalization],[data-billing-toggle]').forEach(input => input.addEventListener('change', updateOptions));
  form.addEventListener('submit', event => {
    update();
    if (!validateSelection()) { event.preventDefault(); return; }
    const invalid = [...form.elements].find(input => input.willValidate && !input.validity.valid);
    if (invalid) { event.preventDefault(); reveal(invalid); return; }
    save();
  });
  update();
  save();
  showStep('selection', false);
  if (restored) form.querySelector('[data-basket-status]').textContent = 'Votre panier a été restauré. Les tarifs affichés sont ceux du catalogue actuel.';
  const target = location.hash ? document.getElementById(location.hash.slice(1)) : null;
  const requestedInput = target?.matches('[data-product]') ? target : target?.querySelector('[data-product]');
  if (requestedInput) reveal(requestedInput);
})();
