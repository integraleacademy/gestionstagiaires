(() => {
  const dialog = document.getElementById("manualDocsReminderModal");
  if (!dialog) return;
  const element = (name) => document.getElementById(`manualReminder${name}`);
  const title = element("Title"), description = element("Description");
  const closeButton = element("Close"), sendButton = element("Send");
  const progress = element("Progress"), progressLabel = element("ProgressLabel");
  const summary = element("Summary"), recipientsList = element("Recipients");
  const note = element("Note");
  const statusLabel = {
    ACCEPTE: "transmis", ECHEC: "échec", ABSENT: "coordonnée manquante",
    EN_ATTENTE: "en attente", EN_COURS: "en cours…", INCONNU: "non confirmé",
  };
  let activeButton = null, originalLabel = "", prepared = null, sending = false, generation = 0;
  let rows = [];

  const readJson = async (response) => {
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "La relance n’a pas pu être traitée.");
    return body;
  };
  const preventLeaving = (event) => {
    event.preventDefault();
    event.returnValue = "";
  };
  const setStatus = (badge, channel, status) => {
    badge.dataset.status = status || "INCONNU";
    badge.textContent = `${channel} : ${statusLabel[status] || statusLabel.INCONNU}`;
  };
  const makeRow = (item) => {
    const card = document.createElement("div");
    card.className = "manual-reminder__recipient";
    const name = document.createElement("strong");
    name.className = "manual-reminder__name";
    name.textContent = item.name;
    const channels = document.createElement("div");
    channels.className = "manual-reminder__channels";
    const email = document.createElement("span"), sms = document.createElement("span");
    email.className = sms.className = "manual-reminder__channel";
    setStatus(email, "E-mail", item.email ? "EN_ATTENTE" : "ABSENT");
    setStatus(sms, "SMS", item.phone ? "EN_ATTENTE" : "ABSENT");
    channels.append(email, sms);
    const error = document.createElement("p");
    error.className = "manual-reminder__error";
    error.hidden = true;
    card.append(name, channels, error);
    recipientsList.append(card);
    return { card, email, sms, error };
  };

  closeButton.addEventListener("click", () => { if (!sending) dialog.close(); });
  dialog.addEventListener("cancel", (event) => { if (sending) event.preventDefault(); });
  dialog.addEventListener("close", () => {
    generation += 1;
    if (activeButton) {
      delete activeButton.dataset.manualReminderSending;
      activeButton.disabled = activeButton.classList.contains("btn-disabled-muted");
      activeButton.textContent = originalLabel;
    }
    activeButton = null;
    prepared = null;
  });

  document.querySelectorAll("[data-manual-docs-reminder]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.disabled || activeButton) return;
      activeButton = button;
      originalLabel = button.textContent;
      button.dataset.manualReminderSending = "true";
      button.disabled = true;
      button.textContent = "Vérification des dossiers…";
      const currentGeneration = ++generation;
      title.textContent = "Préparation de la relance manuelle";
      description.textContent = "Vérification des documents et renseignements manquants…";
      closeButton.disabled = false;
      closeButton.textContent = "Annuler";
      sendButton.hidden = true;
      sendButton.disabled = false;
      summary.hidden = true;
      element("Skipped").hidden = true;
      recipientsList.replaceChildren();
      element("ProgressWrap").hidden = true;
      note.textContent = "";
      // Open before any network request, so the click always has visible feedback.
      dialog.showModal();
      try {
        const preview = await readJson(await fetch(button.dataset.previewUrl, {
          headers: {Accept: "application/json"}, cache: "no-store",
        }));
        if (currentGeneration !== generation) return;
        prepared = preview;
        rows = preview.eligible.map(makeRow);
        const skippedList = element("SkippedList");
        skippedList.replaceChildren();
        preview.skipped.forEach((item) => {
          const line = document.createElement("li");
          line.textContent = `${item.name} : ${item.reason}`;
          skippedList.append(line);
        });
        element("Skipped").hidden = !preview.skipped.length;
        element("SkippedTitle").textContent = `Dossiers non relancés (${preview.skipped.length})`;
        title.textContent = preview.eligible.length ? "Confirmer la relance manuelle" : "Aucun stagiaire à relancer";
        description.textContent = preview.eligible.length
          ? `${preview.eligible.length} stagiaire(s) recevront une relance personnalisée par e-mail et SMS, selon les coordonnées disponibles.`
          : "Les motifs sont indiqués ci-dessous. Aucun message n’a été envoyé.";
        note.textContent = "Chaque message indique les éléments manquants, le lien personnel et la date limite à 10 jours avant l’entrée en formation.";
        sendButton.textContent = `Envoyer la relance (${preview.eligible.length})`;
        sendButton.hidden = !preview.eligible.length;
        closeButton.textContent = preview.eligible.length ? "Annuler" : "Fermer";
      } catch (error) {
        if (currentGeneration !== generation) return;
        title.textContent = "Relance indisponible";
        description.textContent = error.message || "Impossible de préparer la relance.";
        closeButton.textContent = "Fermer";
      }
    });
  });

  sendButton.addEventListener("click", async () => {
    if (sending || !prepared || !prepared.eligible.length) return;
    sending = true;
    sendButton.disabled = true;
    sendButton.hidden = true;
    closeButton.disabled = true;
    closeButton.textContent = "Transmission en cours…";
    title.textContent = "Relance manuelle en cours de transmission";
    description.textContent = "Gardez cette fenêtre ouverte jusqu’à la fin de l’envoi.";
    element("ProgressWrap").hidden = false;
    progress.max = prepared.eligible.length;
    progress.value = 0;
    window.addEventListener("beforeunload", preventLeaving);
    let emailCount = 0, smsCount = 0, issues = 0;
    try {
      // Separate requests avoid session-wide server timeouts. Keep every result
      // visible, including partial failures, and never automatically retry a POST.
      for (const [index, item] of prepared.eligible.entries()) {
        const row = rows[index];
        row.card.dataset.state = "sending";
        setStatus(row.email, "E-mail", item.email ? "EN_COURS" : "ABSENT");
        setStatus(row.sms, "SMS", item.phone ? "EN_COURS" : "ABSENT");
        progressLabel.textContent = `${index + 1} / ${prepared.eligible.length} · ${item.name}`;
        activeButton.textContent = `Envoi ${index + 1}/${prepared.eligible.length}…`;
        try {
          const result = await readJson(await fetch(item.send_url, {
            method: "POST", headers: {"Content-Type": "application/json", Accept: "application/json"},
            body: JSON.stringify({csrf: prepared.csrf, preview_token: item.preview_token, request_id: crypto.randomUUID()}),
          }));
          setStatus(row.email, "E-mail", result.email_status);
          setStatus(row.sms, "SMS", result.sms_status);
          emailCount += Number(result.email_status === "ACCEPTE");
          smsCount += Number(result.sms_status === "ACCEPTE");
          const complete = result.email_status === "ACCEPTE" && result.sms_status === "ACCEPTE";
          issues += Number(!complete);
          row.card.dataset.state = complete ? "success" : "warning";
          row.error.textContent = result.error || "";
          row.error.hidden = !result.error;
        } catch (error) {
          issues += 1;
          row.card.dataset.state = "warning";
          setStatus(row.email, "E-mail", item.email ? "INCONNU" : "ABSENT");
          setStatus(row.sms, "SMS", item.phone ? "INCONNU" : "ABSENT");
          row.error.textContent = `${error.message} Vérifiez l’historique avant une nouvelle relance.`;
          row.error.hidden = false;
        }
        progress.value = index + 1;
        document.dispatchEvent(new CustomEvent("manual-docs-reminder-updated", {detail: {traineeId: item.trainee_id}}));
      }
      title.textContent = issues ? "Relance terminée — résultat à vérifier" : "Relance manuelle terminée";
      description.textContent = "Le résultat de chaque transmission est indiqué ci-dessous.";
      progressLabel.textContent = `${prepared.eligible.length} / ${prepared.eligible.length} dossiers traités`;
      summary.textContent = `${emailCount} e-mail(s) transmis · ${smsCount} SMS transmis${issues ? ` · ${issues} dossier(s) à vérifier` : ""}`;
      summary.dataset.state = issues ? "warning" : "success";
      summary.hidden = false;
      note.textContent = "Les mails transmis sont consultables dans l’historique de chaque stagiaire.";
    } finally {
      sending = false;
      closeButton.disabled = false;
      closeButton.textContent = "Fermer";
      activeButton.textContent = originalLabel;
      window.removeEventListener("beforeunload", preventLeaving);
    }
  });
})();
