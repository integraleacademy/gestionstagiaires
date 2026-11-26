(() => {
  const panel = document.querySelector(".conv-wait");
  if (!panel) return;
  const status = panel.querySelector(".conv-wait__status");
  const title = panel.querySelector("h1");
  const progress = panel.querySelector(".conv-wait__progress");
  const retry = panel.querySelector("[data-conv-retry]");
  const back = panel.querySelector("[data-conv-back]");
  const embedded = window.parent !== window;
  const signal = state => {
    if (embedded) window.parent.postMessage({ convocationPreview: state }, location.origin);
  };

  retry.href = location.href;
  if (embedded) {
    signal("waiting");
    back.textContent = "Fermer l’aperçu";
    back.addEventListener("click", event => { event.preventDefault(); signal("close"); });
    window.addEventListener("keydown", event => { if (event.key === "Escape") signal("close"); });
  }
  title.focus({ preventScroll: true });
  if (!status.dataset.jobId) return;

  const statusUrl = new URL(location.href);
  statusUrl.searchParams.set("preparation", status.dataset.jobId);
  window.convocationJobs.wait({ statusUrl, result: { status: "queued" } })
    .then(() => {
      title.textContent = "Votre convocation est prête";
      status.textContent = "Ouverture du document PDF…";
      progress.hidden = true;
      retry.textContent = "Ouvrir le PDF";
      retry.hidden = false;
      signal("ready");
      location.reload();
    })
    .catch(error => {
      title.textContent = "Préparation interrompue";
      status.textContent = error.message || "Le PDF n’a pas pu être préparé.";
      progress.hidden = true;
      retry.hidden = false;
    });
})();
