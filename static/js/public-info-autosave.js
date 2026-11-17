// Serialize patches and replay an unacknowledged patch before sending a newer edit.
function createPublicInfoAutosave({initial, send, notify, onPermitSaved}) {
  const saved = {...initial};
  const edits = new Map();
  let timer, active = false, unconfirmed = null;

  function schedule(key, value) {
    edits.set(key, value);
    notify("Modifications en attente…");
    clearTimeout(timer);
    timer = setTimeout(flush, 650);
  }

  function nextPatch() {
    const payload = {_previous: {}};
    for (const [key, value] of edits) {
      if (value === "" || saved[key] === value) continue;
      payload[key] = value;
      payload._previous[key] = saved[key];
    }
    return Object.keys(payload._previous).length ? payload : null;
  }

  async function flush() {
    clearTimeout(timer);
    if (active) return;
    active = true;
    let wrote = false;
    try {
      let payload;
      while ((payload = unconfirmed || nextPatch())) {
        unconfirmed = payload;
        notify("Enregistrement…");
        try {
          await send(payload);
        } catch (error) {
          if (error.rejected) unconfirmed = null;
          notify(error.message || "Enregistrement impossible. Vérifiez votre connexion.", true);
          return;
        }
        unconfirmed = null;
        for (const key of Object.keys(payload._previous)) {
          saved[key] = payload[key];
        }
        if ("no_permis" in payload) onPermitSaved(payload.no_permis);
        wrote = true;
      }
      const keptNonempty = [...edits].some(([key, value]) => value === "" && saved[key] !== "");
      edits.clear();
      notify(keptNonempty ? "Champ vide. Sa valeur enregistrée est conservée."
                          : wrote ? "Modifications enregistrées." : "");
    } finally {
      active = false;
    }
  }

  return {schedule, flush, hasPending: () => active || !!unconfirmed || !!nextPatch()};
}

// Preserve file inputs (including selected files) and their bound upload checks.
function showSavedPermit(row, waived) {
  if (!row) return;
  row.dataset.docSubmitted = waived ? "true" : row.dataset.permitSubmitted;
  row.classList.remove("valid", "pending", "missing");
  const status = waived ? "valid" : row.dataset.permitClass;
  if (status) row.classList.add(status);
  row.querySelectorAll("[data-permit-waived]").forEach(el => el.hidden = !waived);
  row.querySelectorAll("[data-permit-required]").forEach(el => el.hidden = waived);
}

function showDossierProgress(step, complete) {
  if (!step) return;
  step.classList.toggle("done", complete);
  step.classList.toggle("blocked", !complete);
  const badge = step.querySelector(".pill");
  badge.classList.toggle("green", complete);
  badge.classList.toggle("red", !complete);
  badge.textContent = complete ? "COMPLET" : "INCOMPLET";
  const card = step.closest("[data-tracking-total]");
  const percent = Math.floor((Number(card.dataset.trackingOther) + Number(complete)) * 100 / Number(card.dataset.trackingTotal));
  card.querySelector(".progress-percent").textContent = `Dossier complété à ${percent} %`;
  card.querySelector(".progress-fill").style.width = `${percent}%`;
}
