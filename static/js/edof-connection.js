(() => {
  const box = document.getElementById("edof-live");
  const lamp = document.getElementById("edof-lamp");
  const note = document.getElementById("edof-connection-note");
  if (!box || !lamp || !note) return;
  const manualSync = box.querySelector("[data-manual-sync]");
  const feedback = box.querySelector("[data-sync-feedback]");
  let submitting = false;
  let submittedAt = 0;
  let awaitingList = Boolean(manualSync?.querySelector("button").disabled);
  manualSync?.addEventListener("submit", async event => {
    event.preventDefault();
    if (submitting) return;
    submitting = true;
    manualSync.querySelector("button").disabled = true;
    submittedAt = Date.now();
    try {
      const response = await fetch(manualSync.action, {method:"POST", body:new FormData(manualSync),
        headers:{Accept:"application/json"}, cache:"no-store"});
      const result = await response.json();
      feedback.textContent = result.message;
      awaitingList = response.ok;
      if (!response.ok) manualSync.querySelector("button").disabled = false;
    } catch {
      feedback.textContent = "La demande n’a pas pu être confirmée. Vérifiez la connexion et réessayez.";
      manualSync.querySelector("button").disabled = false;
    } finally {
      submitting = false;
    }
  });
  async function refresh() {
    if (!document.hidden) {
      try {
        const started = Date.now();
        const response = await fetch(box.dataset.statusUrl, {cache: "no-store"});
        if (!response.ok) throw Error();
        const state = await response.json();
        const latest = document.getElementById("edof-sync");
        const full = document.getElementById("edof-full-sync");
        if (state.sync.stamp && state.sync.stamp >= Number(latest.dataset.stamp)) {
          latest.dataset.stamp = state.sync.stamp;
          latest.textContent = ["Dernière synchronisation", state.sync.label, state.sync.scope].join(" · ");
        }
        if (state.sync.full_stamp && state.sync.full_stamp >= Number(full.dataset.stamp)) {
          full.dataset.stamp = state.sync.full_stamp;
          full.textContent = "Liste générale · " + state.sync.full_label;
        }
        full.hidden = !Number(full.dataset.stamp) || Number(full.dataset.stamp) >= Number(latest.dataset.stamp);
        const activate = document.getElementById("edof-activate");
        if (manualSync && !submitting && started > submittedAt && state.manual_sync) {
          manualSync.querySelector("button").disabled = state.manual_sync.busy;
          feedback.textContent = state.manual_sync.message;
          if (state.manual_sync.busy) awaitingList = true;
          else if (awaitingList && state.manual_sync.updated && box.dataset.detail === "0") {
            if (!document.activeElement.matches("input, textarea, select")) {
              location.reload();
              return;
            }
          } else awaitingList = false;
        }
        if (activate) activate.hidden = state.manual && (state.active || state.pending || state.paused);
        if (activate) activate.querySelector("button").textContent = state.manual ? "Réessayer la lecture" : "Activer la connexion pour 1 heure";
        const resume = document.getElementById("edof-resume");
        if (resume) resume.hidden = !state.paused;
        lamp.classList.toggle("on", state.active);
        lamp.textContent = state.active ? "Connexion EDOF active" : "Connexion EDOF inactive";
        note.textContent = [state.schedule, state.pending ? (state.phase || "Lecture en cours…") : state.error,
          state.until && "Activation manuelle jusqu’à " + state.until,
          state.checked && "Dernier contrôle le " + state.checked].filter(Boolean).join(" · ");
        if (state.active && box.dataset.list === "1" && state.stamp > Number(box.dataset.stamp)
            && !document.activeElement.matches("input, textarea, select")) location.reload();
      } catch {
        lamp.classList.remove("on");
        lamp.textContent = "Connexion EDOF inactive";
        note.textContent = "Le serveur n’a pas pu confirmer la connexion.";
      }
    }
    setTimeout(refresh, 15000);
  }
  setTimeout(refresh, 3000);
})();

// Read the official offer in the background while the locally available form remains editable.
(() => {
  let section = document.getElementById("proposition-edof");
  if (!section) return;
  let reading = false;
  function note(message) {
    const status = section.querySelector("[data-proposal-note]");
    if (status) {
      status.textContent = message;
      status.hidden = false;
    }
  }
  function markEdited(event) {
    if (event.target.closest(".edof-proposal-form") && event.target.name !== "confirm") {
      event.target.dataset.edited = "1";
    }
  }
  function applyOffer(next) {
    const focused = document.activeElement;
    let focusTarget;
    const controls = Array.from(next.querySelectorAll(".edof-proposal-form [name]"));
    for (const prior of section.querySelectorAll(".edof-proposal-form [name]")) {
      if (!prior.dataset.edited && prior !== focused) continue;
      const field = controls.find(el => el.name === prior.name &&
        (prior.type !== "checkbox" || el.value === prior.value));
      if (!field) continue;
      if (prior.dataset.edited) {
        if (field.type === "checkbox") field.checked = prior.checked;
        else field.value = prior.value;
        field.dataset.edited = "1";
      }
      if (prior === focused) focusTarget = field;
    }
    for (const old of section.querySelectorAll("details[data-fold]")) {
      const replacement = next.querySelector('details[data-fold="' + old.dataset.fold + '"]');
      if (replacement) replacement.open = old.open;
    }
    section.replaceWith(next);
    section = next;
    if (focusTarget) {
      focusTarget.focus({preventScroll:true});
      if (focused.selectionStart != null) focusTarget.setSelectionRange(focused.selectionStart, focused.selectionEnd);
    }
  }
  async function load(form, ticketUrl) {
    if (reading) return;
    reading = true;
    const button = form?.querySelector("button");
    if (button) button.disabled = true;
    note("Lecture des conditions de l’offre en attente du connecteur EDOF.");
    try {
      if (!ticketUrl) {
        const response = await fetch(form.action, {method:"POST", body:new FormData(form),
          headers:{Accept:"application/json"}, cache:"no-store"});
        const job = await response.json();
        if (!response.ok) throw Error(job.message || "Lecture de l’offre indisponible.");
        ticketUrl = job.poll_url;
      }
      const deadline = Date.now() + 10 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 5000));
        if (document.hidden) continue;
        const response = await fetch(ticketUrl, {cache:"no-store"});
        if (!response.ok) throw Error();
        const job = await response.json();
        if (job.status !== "finished") continue;
        const updated = await fetch(job.detail_url, {cache:"no-store"});
        if (!updated.ok) throw Error();
        const doc = new DOMParser().parseFromString(await updated.text(), "text/html");
        const next = doc.getElementById("proposition-edof");
        if (!next) throw Error();
        applyOffer(next);
        return;
      }
      note("Le connecteur n’a pas terminé la lecture. Vous pouvez enregistrer votre brouillon ou relancer la lecture.");
    } catch {
      note("Lecture de l’offre indisponible. Votre saisie est conservée. Vous pouvez relancer la lecture.");
    } finally {
      reading = false;
      if (button) button.disabled = false;
    }
  }
  document.addEventListener("invalid", event => {
    if (!event.target.closest(".edof-proposal-form")) return;
    for (let el = event.target.parentElement; el; el = el.parentElement) {
      if (el.tagName === "DETAILS") el.open = true;
    }
  }, true);
  document.addEventListener("input", markEdited);
  document.addEventListener("change", markEdited);
  document.addEventListener("submit", event => {
    if (event.target.id !== "edof-proposal-load") return;
    event.preventDefault();
    load(event.target);
  });
  const form = section.querySelector("#edof-proposal-load");
  if (section.dataset.pollUrl || form?.hasAttribute("data-autoload")) load(form, section.dataset.pollUrl);
})();
