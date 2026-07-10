(() => {
  const form = document.querySelector('[data-login-form]');
  const passwordInput = document.getElementById('admin-password');
  const toggle = document.querySelector('[data-password-toggle]');
  const submitButton = document.querySelector('[data-submit-button]');
  const submitText = document.querySelector('[data-submit-text]');

  toggle?.addEventListener('click', () => {
    if (!passwordInput) return;
    const isVisible = passwordInput.type === 'text';
    passwordInput.type = isVisible ? 'password' : 'text';
    toggle.classList.toggle('is-visible', !isVisible);
    toggle.setAttribute('aria-pressed', String(!isVisible));
    toggle.setAttribute('aria-label', isVisible ? 'Afficher le mot de passe' : 'Masquer le mot de passe');
    passwordInput.focus();
  });

  form?.addEventListener('submit', (event) => {
    if (!form.checkValidity()) {
      return;
    }

    if (submitButton?.classList.contains('is-loading')) {
      event.preventDefault();
      return;
    }

    submitButton?.classList.add('is-loading');
    if (submitButton) submitButton.disabled = true;
    if (submitText) submitText.textContent = 'Connexion en cours…';
  });
})();
