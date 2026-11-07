(() => {
  const courseFilter = document.querySelector('.edof-search select[name="course"]');
  courseFilter?.addEventListener("change", () => {
    const periodFilter = courseFilter.form.querySelector('select[name="period"]');
    if (periodFilter) periodFilter.value = "";
    courseFilter.form.requestSubmit();
  });
  const box = document.getElementById("edof-live");
  const lamp = document.getElementById("edof-lamp");
  const note = document.getElementById("edof-connection-note");
  if (!box || !lamp || !note) return;
  const syncControls = Array.from(box.querySelectorAll("[data-manual-sync]"), form => ({
    form, button:form.querySelector("button"), feedback:form.querySelector("[data-sync-feedback]"),
    submitting:false, submittedAt:0, awaiting:form.querySelector("button").disabled,
    statusKey:form.dataset.manualSync === "new" ? "new_sync" : "manual_sync"
  }));
  const feedback = window.edofFeedback;
  let refreshTimer;
  function scheduleRefresh(delay) {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, delay);
  }
  let catchupRequest = null;
  const connectionControls = Array.from(document.querySelectorAll('#edof-activate, form[action$="/directory/resume"]'), form => ({
    form, button:form.querySelector('button'), kind:form.id === 'edof-activate' ? 'connect' : 'reconnect', awaiting:false
  }));
  async function postAction(form) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), 20000);
    try {
      const response = await fetch(form.action, {method:'POST', body:new FormData(form),
        headers:{Accept:'application/json'}, cache:'no-store', signal:abort.signal});
      if (!response.headers.get('content-type')?.includes('application/json')) throw Error('La demande n’a pas pu être confirmée. Actualisez la page et vérifiez le suivi avant de relancer.');
      const result = await response.json();
      if (!response.ok) throw Error(result.message || result.error || 'La demande n’a pas pu être prise en compte.');
      return result;
    } finally { clearTimeout(timeout); }
  }
  function requestError(error) {
    return error.name === 'AbortError' || error instanceof TypeError ?
      'La réponse du serveur n’a pas été reçue. Le traitement a peut-être démarré : vérifiez le suivi avant de relancer.' : error.message;
  }
  const clock = document.getElementById("edof-session-clock");
  let tickTimer;
  function animateClock(elapsed, seconds, confirmed) {
    clearInterval(tickTimer);
    if (!clock || !seconds) return;
    const received = performance.now();
    const value = clock.querySelector("[data-clock-value]");
    tickTimer = setInterval(() => {
      const delta = Math.floor((performance.now() - received) / 1000);
      if (delta >= seconds) {
        clearInterval(tickTimer);
        value.textContent = confirmed;
        clock.querySelector("[data-clock-label]").textContent = "En attente du prochain contrôle";
        return;
      }
      const total = elapsed + delta;
      value.textContent = [Math.floor(total / 3600), Math.floor(total / 60) % 60, total % 60]
        .map(unit => String(unit).padStart(2,"0")).join(":");
    }, 1000);
  }
  function updateClock(state) {
    if (!clock || !state) return;
    clock.querySelector("[data-clock-label]").textContent = state.label;
    clock.querySelector("[data-clock-value]").textContent = state.display;
    clock.querySelector("[data-clock-detail]").textContent = state.detail;
    clock.querySelector("[data-clock-previous]").textContent = state.previous;
    clock.dataset.confirmed = state.confirmed;
    animateClock(state.elapsed, state.tick_for, state.confirmed);
  }
  if (clock) animateClock(Number(clock.dataset.elapsed), Number(clock.dataset.tickFor), clock.dataset.confirmed);
  const catchupPanel = document.getElementById("rattrapage");
  const catchupButton = catchupPanel?.querySelector("[data-catchup-button]");
  let leavingForCatchup = false;
  function busy(button, running, unavailable = false) {
    if (!button) return;
    button.setAttribute("aria-busy", String(running));
    button.disabled = running || unavailable;
  }
  function showCatchup(phase, message) {
    if (!catchupPanel) return;
    catchupPanel.dataset.phase = phase;
    catchupPanel.querySelector(".edof-report").hidden = false;
    const titles = {scan:"Lecture des dossiers EDOF en cours…", send:"Transmission des déclarations en cours…", done:"Dernier bilan"};
    catchupPanel.querySelector("[data-stage-title]").textContent = titles[phase];
    catchupPanel.querySelector("[role=status]").textContent = message;
    busy(catchupButton, phase !== "done", catchupButton?.dataset.active !== "1");
  }
  catchupButton?.form.addEventListener("submit", async event => {
    if (!feedback) { leavingForCatchup = true; return; }
    event.preventDefault();
    if (catchupButton.disabled) return;
    const control = {token:feedback.begin('catchup', 'Lecture des dossiers puis préparation des déclarations en retard.', catchupButton), awaiting:true, submitting:true};
    catchupRequest = control;
    showCatchup("scan", "Demande de rattrapage en cours…");
    try {
      const result = await postAction(catchupButton.form);
      control.requested = result.requested;
      feedback.update(control.token, result.message, 'Demande de rattrapage reçue');
    } catch (error) {
      control.awaiting = false;
      showCatchup('done', requestError(error));
      feedback.finish(control.token, 'error', requestError(error));
    } finally { control.submitting = false; control.submittedAt = Date.now(); scheduleRefresh(500); }
  });
  for (const control of connectionControls) control.form.addEventListener('submit', async event => {
    if (!feedback) return;
    event.preventDefault();
    if (control.awaiting || control.button.disabled) return;
    control.token = feedback.begin(control.kind, control.kind === 'reconnect' ?
      'Une nouvelle authentification EFP va être tentée. La connexion sera confirmée après une lecture EDOF.' :
      'Le serveur vérifie la session puis ouvre votre espace EDOF.', control.button);
    control.awaiting = control.submitting = true;
    busy(control.button, true);
    try {
      const result = await postAction(control.form);
      control.requested = result.requested;
      if (result.active) {
        control.awaiting = false;
        feedback.finish(control.token, 'success', result.message);
        busy(control.button, false);
      } else feedback.update(control.token, result.message, 'Demande de connexion reçue');
    } catch (error) {
      control.awaiting = false;
      busy(control.button, false);
      feedback.finish(control.token, 'error', requestError(error));
    } finally { control.submitting = false; control.submittedAt = Date.now(); scheduleRefresh(500); }
  });
  for (const control of syncControls) {
    control.form.addEventListener("submit", async event => {
      event.preventDefault();
      if (control.submitting || control.button.disabled) return;
      control.submitting = true;
      control.token = feedback?.begin('sync', control.form.dataset.manualSync === 'new' ?
        'Actualisation des nouveaux dossiers à traiter.' : 'Actualisation de tous les dossiers et de leurs statuts.', control.button);
      busy(control.button, true);
      control.feedback.textContent = "Demande de synchronisation en cours…";
      try {
        const result = await postAction(control.form);
        control.feedback.textContent = result.message;
        control.requested = result.requested;
        control.awaiting = true;
        feedback?.update(control.token, result.message, 'Demande de synchronisation reçue');
      } catch (error) {
        control.awaiting = false;
        control.feedback.textContent = requestError(error);
        feedback?.finish(control.token, 'error', requestError(error));
        busy(control.button, false);
      } finally {
        control.submittedAt = Date.now();
        control.submitting = false;
        scheduleRefresh(500);
      }
    });
  }
  function preserveSelection() {
    return feedback?.blockingReload || document.activeElement.matches("input, textarea, select") ||
      document.querySelector('input[form="edof-effective-entries"]:checked');
  }
  async function refresh() {
    if (!document.hidden) {
      try {
        const started = Date.now();
        const response = await fetch(box.dataset.statusUrl, {cache: "no-store", signal:AbortSignal.timeout(12000)});
        if (!response.ok) throw Error();
        const state = await response.json();
        for (const control of connectionControls) {
          if (!control.awaiting || control.submitting || started <= control.submittedAt) continue;
          const read = state.last_read;
          if (read?.finished >= control.requested) {
            control.awaiting = false;
            busy(control.button, false);
            const success = state.active;
            feedback.finish(control.token, success ? 'success' : 'warning', success ?
              'L’accès à EDOF a été vérifié. La connexion est active.' : state.error || 'La connexion n’a pas été confirmée. Consultez les paramètres de connexion.');
          } else feedback.update(control.token, state.phase || 'Le serveur attend son tour puis vérifie l’accès à EDOF.', state.phase || 'Connexion en cours…');
        }
        updateClock(state.clock);
        const priorPhase = catchupPanel?.dataset.phase;
        if (catchupPanel && state.catchup && !leavingForCatchup && !catchupRequest?.submitting &&
            (!catchupRequest?.awaiting || started > catchupRequest.submittedAt && state.catchup.requested === catchupRequest.requested)) {
          showCatchup(state.catchup.phase, state.catchup.message);
          const control = catchupRequest;
          if (control?.awaiting && !control.submitting && started > control.submittedAt && state.catchup.requested === control.requested) {
            if (state.catchup.busy) feedback.update(control.token, state.catchup.message,
              state.catchup.phase === 'send' ? 'Transmission et vérification des déclarations…' : 'Lecture des dossiers EDOF…');
            else {
              control.awaiting = false;
              feedback.finish(control.token, state.catchup.result || 'warning', state.catchup.message, true);
            }
          }
        }
        const reading = document.getElementById("edof-reading");
        if (reading) reading.hidden = !state.pending;
        const budget = document.getElementById('edof-login-budget');
        if (budget) {
          budget.hidden = !state.login_budget;
          budget.textContent = state.login_budget ? `EFP · ${state.login_budget.used}/${state.login_budget.limit} normales · ${state.login_budget.restarts || 0} après redémarrage` : '';
        }
        const recovery = document.getElementById('edof-recovery');
        if (recovery) {
          recovery.hidden = !state.recovery;
          recovery.textContent = state.recovery?.message || '';
          recovery.dataset.pending = state.recovery?.pending ? '1' : '0';
        }
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
        for (const control of syncControls) {
          const status = state[control.statusKey];
          if (control.submitting || started <= control.submittedAt || !status) continue;
          if (control.awaiting && control.requested && status.requested !== control.requested) continue;
          busy(control.button, status.busy);
          control.feedback.textContent = status.message;
          if (control.awaiting && control.token) {
            if (status.busy) feedback.update(control.token, status.message, state.phase || 'Synchronisation en cours…');
            else {
              feedback.finish(control.token, status.complete ? 'success' : status.updated ? 'warning' : 'error',
                status.message, Boolean(status.updated) && box.dataset.detail === '0');
              control.awaiting = false;
              control.token = null;
              control.requested = null;
            }
          }
          if (control.awaiting && !status.busy && status.updated && box.dataset.detail === "0") {
            if (preserveSelection()) continue;
            location.reload();
            return;
          }
          control.awaiting = status.busy;
        }
        if (["scan","send"].includes(priorPhase) && state.catchup?.phase !== priorPhase && !leavingForCatchup && !catchupRequest
            && !preserveSelection()) {
          location.reload();
          return;
        }
        if (activate) activate.hidden = state.manual && (state.active || state.pending || state.paused);
        if (activate) activate.querySelector("button").textContent = state.manual ? "Réessayer la lecture" : "Activer la connexion pour 1 heure";
        const resume = document.getElementById("edof-resume");
        if (resume) resume.hidden = !state.paused;
        lamp.dataset.state = state.connection_state;
        lamp.textContent = state.connection_label;
        note.textContent = [state.schedule, state.pending ? (state.phase || "Lecture en cours…") : state.error,
          state.until && "Activation manuelle jusqu’à " + state.until,
          state.checked && "Dernier contrôle le " + state.checked].filter(Boolean).join(" · ");
        if (state.active && box.dataset.list === "1" && state.stamp > Number(box.dataset.stamp)
            && !preserveSelection()) location.reload();
      } catch {
        lamp.dataset.state = "waiting";
        lamp.textContent = "État de la connexion indisponible";
        note.textContent = "Le statut sera vérifié automatiquement.";
        for (const control of [...syncControls, ...connectionControls, catchupRequest].filter(Boolean)) {
          if (control.awaiting && !control.submitting) feedback?.update(control.token,
            'Le suivi est momentanément indisponible. Le traitement peut continuer sur le serveur ; aucune nouvelle demande n’est envoyée.', 'Vérification en attente…');
        }
        clearInterval(tickTimer);
        if (clock && clock.dataset.confirmed !== "—") {
          clock.querySelector("[data-clock-value]").textContent = clock.dataset.confirmed;
          clock.querySelector("[data-clock-label]").textContent = "Durée confirmée au dernier accès";
        }
      }
    }
    const active = [...syncControls,...connectionControls].some(control => control.awaiting) || catchupRequest?.awaiting || ["scan","send"].includes(catchupPanel?.dataset.phase);
    scheduleRefresh(active ? 3000 : 15000);
  }
  scheduleRefresh(3000);
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

(() => {
  const form = document.getElementById("edof-effective-entries");
  if (!form) return;
  const update = () => {
    const count = document.querySelectorAll('input[form="edof-effective-entries"]:checked').length;
    form.querySelector("button").disabled = !count;
    form.querySelector("[data-entry-count]").textContent = count ? `${count} entrée${count === 1 ? "" : "s"}` : "les entrées sélectionnées";
  };
  document.addEventListener("change", event => { if (event.target.form === form) update(); });
  update();
})();
