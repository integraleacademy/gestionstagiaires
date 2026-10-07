(() => {
  const content = document.getElementById("traineeEmailHistoryContent");
  const status = document.getElementById("traineeEmailHistoryStatus");
  if (!content || !status) return;
  let revision = 0;
  window.refreshTraineeEmailHistory = async () => {
    const currentRevision = ++revision;
    status.textContent = "Actualisation de l’historique…";
    content.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(content.dataset.historyUrl, {
        headers: {Accept: "text/html"}, cache: "no-store",
      });
      if (!response.ok) throw new Error("history_unavailable");
      const fragment = await response.text();
      if (currentRevision !== revision) return;
      // This authenticated server-rendered fragment uses the same escaped Jinja
      // partial as the initial page; mail HTML stays in escaped data attributes.
      content.innerHTML = fragment;
      status.textContent = "";
    } catch (error) {
      if (currentRevision !== revision) return;
      status.textContent = "L’historique n’a pas pu être actualisé. Fermez puis rouvrez cette fenêtre pour réessayer.";
    } finally {
      if (currentRevision === revision) content.setAttribute("aria-busy", "false");
    }
  };

  content.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-email-preview]");
    if (!button || !content.contains(button)) return;
    const iframe = document.getElementById("emailHtmlPreviewFrame");
    const meta = document.getElementById("emailHtmlPreviewMeta");
    if (!iframe || !meta) return;
    const subject = button.dataset.emailSubject || "(Sans objet)";
    const sentDate = button.dataset.emailDate || "";
    meta.textContent = `${subject}${sentDate ? " · " + sentDate : ""}`;
    iframe.srcdoc = button.dataset.emailHtml || "";
    window.openModal("emailHtmlPreviewModal");
  });
  document.addEventListener("manual-docs-reminder-updated", (event) => {
    if (event.detail.traineeId === content.dataset.traineeId) window.refreshTraineeEmailHistory();
  });
})();
