(() => {
  document.querySelectorAll('[data-association-preference]').forEach(form => {
    const checkbox = form.querySelector('input[name="ignore"]');
    const status = form.querySelector('[data-preference-status]');
    form.querySelector('[data-preference-submit]').style.display = 'none';
    let saved = checkbox.checked;
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const body = new FormData(form);
      checkbox.disabled = true;
      status.textContent = 'Enregistrement…';
      try {
        const response = await fetch(form.action, {method: 'POST', body, headers: {Accept: 'application/json'}});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.message || 'Enregistrement impossible. Réessayez.');
        saved = checkbox.checked;
        status.textContent = result.message;
        window.location.reload();
      } catch (error) {
        checkbox.checked = saved;
        checkbox.disabled = false;
        status.textContent = error.message || 'Connexion interrompue. Réessayez.';
      }
    });
    checkbox.addEventListener('change', () => form.requestSubmit());
  });
})();
