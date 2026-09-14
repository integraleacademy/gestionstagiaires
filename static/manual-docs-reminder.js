(() => {
  const statusLabel = {ACCEPTE: "accepté", ECHEC: "échec", ABSENT: "coordonnée manquante"};
  const readJson = async (response) => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "La relance n’a pas pu être traitée.");
    return body;
  };
  document.querySelectorAll("[data-manual-docs-reminder]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled || button.dataset.manualReminderSending) return;
      const label = button.textContent;
      button.dataset.manualReminderSending = "true";
      button.disabled = true;
      button.textContent = "Vérification des dossiers…";
      try {
        const preview = await readJson(await fetch(button.dataset.previewUrl, {
          headers: {Accept: "application/json"}, cache: "no-store",
        }));
        const recipients = preview.eligible;
        const exclusions = preview.skipped.map((item) => `${item.name} : ${item.reason}`);
        if (!recipients.length) {
          alert("Aucun stagiaire à relancer.\n\n" + exclusions.join("\n"));
          return;
        }
        const names = recipients.map((item) => `${item.name}${!item.email ? " (e-mail absent)" : ""}${!item.phone ? " (téléphone absent)" : ""}`);
        if (!confirm(`Envoyer la relance manuelle par e-mail et SMS à ${recipients.length} stagiaire(s) ?\n\n${names.join("\n")}\n\nChaque message contiendra les éléments manquants, le lien personnel et la date limite à J−10.${exclusions.length ? `\n${exclusions.length} dossier(s) exclu(s).` : ""}`)) return;
        const results = [];
        // One request per trainee avoids a long session-wide request timeout.
        for (const [index, item] of recipients.entries()) {
          button.textContent = `Envoi ${index + 1}/${recipients.length}…`;
          try {
            const result = await readJson(await fetch(item.send_url, {
              method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json"},
              body: JSON.stringify({csrf: preview.csrf, preview_token: item.preview_token, request_id: crypto.randomUUID()}),
            }));
            results.push(`${item.name} — E-mail : ${statusLabel[result.email_status] || "non confirmé"} ; SMS : ${statusLabel[result.sms_status] || "non confirmé"}${result.error ? ` (${result.error})` : ""}`);
          } catch (error) {
            results.push(`${item.name} — ${error.message}`);
          }
        }
        alert("Résultat de la relance manuelle :\n\n" + results.join("\n") + (exclusions.length ? "\n\nDossiers exclus :\n" + exclusions.join("\n") : ""));
      } catch (error) {
        alert(error.message || "Impossible de préparer la relance.");
      } finally {
        delete button.dataset.manualReminderSending;
        button.disabled = button.classList.contains("btn-disabled-muted");
        button.textContent = label;
      }
    });
  });
})();
