(() => {
  const pending = new Set();
  const saves = new WeakMap();
  async function post(input, fields) {
    const body = new URLSearchParams({ csrf: input.dataset.csrf, ...fields });
    const response = await fetch(input.dataset.url, { method: 'POST', headers: { Accept: 'application/json' }, body, keepalive: true });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || 'Enregistrement impossible.');
    return result;
  }
  async function save(input) {
    const state = saves.get(input);
    clearTimeout(state.timer);
    if (state.promise) return state.promise;
    state.promise = (async () => {
      try {
        while (input.value !== state.saved) {
          const comment = input.value;
          const reply = await post(input, {comment, version: input.dataset.version});
          input.dataset.version = reply.version;
          state.saved = comment;
          for (const other of document.querySelectorAll('[data-edof-comment]')) {
            if (other !== input && other.dataset.url === input.dataset.url && !pending.has(other)) {
              other.value = comment;
              other.dataset.version = reply.version;
              saves.get(other).saved = comment;
            }
          }
        }
        pending.delete(input);
        delete input.dataset.unsaved;
        state.status.textContent = 'Enregistré';
      } catch (error) {
        state.status.textContent = error.message || 'Enregistrement impossible. Réessayez en quittant le champ.';
      }
    })();
    try { await state.promise; } finally { state.promise = null; }
  }
  for (const input of document.querySelectorAll('[data-edof-comment]')) {
    const state = {saved: input.value, status: input.nextElementSibling};
    saves.set(input, state);
    input.addEventListener('input', () => {
      pending.add(input);
      input.dataset.unsaved = "true";
      state.status.textContent = 'Enregistrement…';
      clearTimeout(state.timer);
      state.timer = setTimeout(() => save(input), 450);
    });
    input.addEventListener('blur', () => { if (pending.has(input)) save(input); });
  }
  window.addEventListener('pagehide', () => { for (const input of pending) save(input); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) for (const input of pending) save(input); });
  for (const input of document.querySelectorAll('[data-edof-refusal]')) {
    input.addEventListener('change', async () => {
      if (!input.checked) return;
      input.disabled = true;
      const status = input.parentElement.nextElementSibling;
      try {
        await Promise.all([...pending].map(save));
        if (pending.size) throw new Error('Enregistrez le commentaire avant de masquer ce dossier.');
        await post(input, {refusal: input.dataset.edofRefusal});
        location.reload();
      } catch (error) {
        input.checked = false; input.disabled = false;
        status.textContent = error.message || 'Impossible de prendre en compte le refus.';
      }
    });
  }
})();
