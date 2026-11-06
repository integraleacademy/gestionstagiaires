(() => {
  const panel = document.querySelector("[data-payment-state]");
  if (!panel) return;
  const state = panel.dataset.paymentState;
  const dialog = document.querySelector("#payment-wait");
  const hint = panel.querySelector("[data-wait-hint]");
  const start = Date.now();
  let delay = 2500;
  let timer;
  let checking = false;

  // The dossier remains usable with a slow provider, a keyboard, or JavaScript disabled.
  if (dialog && typeof dialog.showModal === "function") {
    dialog.showModal();
    dialog.querySelector("[data-close-dialog]").addEventListener("click", () => dialog.close());
    window.setTimeout(() => {
      if (dialog.open) dialog.close();
      if (hint) hint.textContent = "La préparation prend un peu de temps. Vous pouvez laisser ce dossier ouvert ou retrouver le lien dans votre e-mail de paiement.";
    }, 30000);
  }

  async function check() {
    window.clearTimeout(timer);
    if (checking || document.hidden) return;
    checking = true;
    try {
      const response = await fetch(panel.dataset.statusUrl, {cache: "no-store", headers: {"Accept": "application/json"}});
      if (!response.ok) throw new Error("status");
      const update = await response.json();
      if (typeof update.state === "string" && update.state !== state) {
        window.location.reload();
        return;
      }
    } catch {
      if (hint) hint.textContent = "La connexion au dossier a été interrompue. Vous pouvez actualiser la page pour reprendre.";
    } finally {
      checking = false;
    }
    if (Date.now() - start < 5 * 60000) {
      delay = Math.min(Math.round(delay * 1.35), 15000);
      timer = window.setTimeout(check, delay);
    } else if (hint) {
      hint.textContent = "Vous pouvez actualiser le dossier ou revenir depuis votre e-mail pour consulter son état.";
    }
  }
  timer = window.setTimeout(check, delay);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
  window.addEventListener("pageshow", event => { if (event.persisted) check(); });
})();
