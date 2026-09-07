(() => {
  "use strict";
  const configNode = document.getElementById("nativeAdminUploadConfig");
  const form = document.getElementById("nativeCourseUploadForm");
  const input = document.getElementById("nativeCourseFile");
  if (!configNode || !form || !input) return;

  let config;
  try { config = JSON.parse(configNode.textContent || "{}"); } catch (_error) { return; }

  const zone = document.getElementById("nativeUploadZone");
  const selectedLabel = document.getElementById("nativeSelectedFile");
  const button = document.getElementById("nativeImportButton");
  const progress = document.getElementById("nativeUploadProgress");
  const bar = document.getElementById("nativeUploadBar");
  const percentLabel = document.getElementById("nativeUploadPercent");
  const stepLabel = document.getElementById("nativeUploadStep");
  const status = document.getElementById("nativeUploadStatus");
  let selectedFile = null;

  function fileSize(bytes) {
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
    return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;
  }

  function setFile(file) {
    selectedFile = file || null;
    if (!selectedLabel) return;
    selectedLabel.textContent = selectedFile
      ? `${selectedFile.name} · ${fileSize(selectedFile.size)}`
      : "Aucun fichier sélectionné";
  }

  function setProgress(value, label) {
    const safeValue = Math.max(0, Math.min(100, Math.round(value)));
    progress?.classList.add("is-visible");
    if (bar) bar.style.width = `${safeValue}%`;
    if (percentLabel) percentLabel.textContent = `${safeValue} %`;
    if (stepLabel) stepLabel.textContent = label;
  }

  function setStatus(message, type) {
    if (!status) return;
    status.textContent = message;
    status.classList.remove("is-error", "is-success");
    status.classList.add("is-visible", type === "success" ? "is-success" : "is-error");
  }

  async function jsonResponse(response) {
    let payload = {};
    try { payload = await response.json(); } catch (_error) { payload = {}; }
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "L’import a échoué.");
    return payload;
  }

  input.addEventListener("change", () => setFile(input.files?.[0]));
  ["dragenter", "dragover"].forEach((eventName) => zone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    zone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((eventName) => zone?.addEventListener(eventName, (event) => {
    event.preventDefault();
    zone.classList.remove("is-dragging");
  }));
  zone?.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (file) setFile(file);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = selectedFile || input.files?.[0];
    status?.classList.remove("is-visible", "is-error", "is-success");
    if (!file || !file.name.toLowerCase().endsWith(".zip")) {
      setStatus("Sélectionnez un export Easygenerator au format ZIP.", "error");
      return;
    }
    if (!file.size || file.size > Number(config.maxBytes || 0)) {
      setStatus("Ce fichier dépasse la taille maximale autorisée.", "error");
      return;
    }

    button.disabled = true;
    input.disabled = true;
    setProgress(1, "Préparation de l’envoi…");
    try {
      const creation = await jsonResponse(await fetch(config.createUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-Elearning-CSRF": config.csrfToken,
        },
        body: JSON.stringify({ filename: file.name, size: file.size }),
      }));

      const chunkSize = Number(creation.chunk_size);
      let offset = 0;
      while (offset < file.size) {
        const chunk = file.slice(offset, Math.min(offset + chunkSize, file.size));
        const response = await fetch(creation.chunk_url, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/octet-stream",
            "X-Elearning-CSRF": config.csrfToken,
            "X-Upload-Offset": String(offset),
          },
          body: chunk,
        });
        const result = await jsonResponse(response);
        offset = Number(result.received);
        setProgress(5 + (offset / file.size) * 82, `Envoi du ZIP · ${fileSize(offset)} sur ${fileSize(file.size)}`);
      }

      setProgress(92, "Contrôle du ZIP et conversion du cours…");
      const completed = await jsonResponse(await fetch(creation.complete_url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-Elearning-CSRF": config.csrfToken,
        },
        body: "{}",
      }));
      setProgress(100, "Cours prêt");
      const counts = completed.course?.counts || {};
      setStatus(`${completed.course?.title || "Cours"} importé : ${counts.sections || 0} séquences et ${counts.activities || 0} activités.`, "success");
      window.setTimeout(() => window.location.reload(), 1000);
    } catch (error) {
      setStatus(error.message || "L’import a échoué.", "error");
      setProgress(0, "Import interrompu");
      button.disabled = false;
      input.disabled = false;
    }
  });
})();
