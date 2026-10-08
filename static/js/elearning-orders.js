(() => {
  'use strict';
  const form = document.getElementById('el-form');
  if (form) {
    const people = document.getElementById('el-learners');
    const add = document.getElementById('el-add');
    const money = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'});
    function update() {
      const rows = [...people.querySelectorAll('.el-person')];
      const selected = form.querySelector('[name="course_code"]:checked');
      const price = selected ? Number(selected.dataset.price) : null;
      document.getElementById('el-count').textContent = rows.length + ' accès individuel' + (rows.length > 1 ? 's' : '');
      document.getElementById('el-total').textContent = price === null ? 'Choisissez votre parcours' : (price === 0 ? 'Gratuit' : money.format(price * rows.length / 100) + ' TTC');
      form.querySelectorAll('[data-billing]').forEach(input => { input.required = price !== 0; });
      rows.forEach(row => { row.querySelector('.el-remove').disabled = rows.length === 1; });
      add.disabled = rows.length >= 100;
      const seen = new Set();
      people.querySelectorAll('[name="email"]').forEach(input => {
        const email = input.value.trim().toLowerCase();
        input.setCustomValidity(email && seen.has(email) ? 'Cette adresse figure déjà dans le groupe.' : '');
        if (email) seen.add(email);
      });
    }
    add.addEventListener('click', () => {
      if (people.children.length >= 100) return;
      const row = people.firstElementChild.cloneNode(true);
      row.querySelectorAll('input').forEach(input => { input.value = ''; input.setCustomValidity(''); });
      people.append(row); update(); row.querySelector('input').focus();
    });
    people.addEventListener('click', event => {
      const button = event.target.closest('.el-remove');
      if (button && people.children.length > 1) { button.closest('.el-person').remove(); update(); }
    });
    form.addEventListener('input', update); form.addEventListener('change', update); update();
  }
  const status = document.querySelector('[data-el-status]');
  if (status) {
    const signature = value => JSON.stringify([value.status, value.payment_status, value.invoice_status, value.active, value.mail_sent]);
    const previous = status.dataset.elInitial ? signature(JSON.parse(status.dataset.elInitial)) : null;
    let ticks = 0;
    const poll = async () => {
      if (++ticks > 180) return;
      if (!document.hidden) {
        try {
          const response = await fetch(status.dataset.elStatus, {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
          if (!response.ok || response.redirected) return;
          const current = signature(await response.json());
          if (previous !== null && current !== previous) { location.reload(); return; }
        } catch (_) { /* Keep the page and retry after a transient network error. */ }
      }
      window.setTimeout(poll, 10000);
    };
    poll();
  }
})();
