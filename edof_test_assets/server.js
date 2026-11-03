"use strict";
const serverMessage = document.getElementById("server-message");
const serverCsrf = document.querySelector("main").dataset.csrf;
let polling = false;
let retryTimer;

const efpRefresh = document.getElementById("refresh-efp-state");
async function refreshEfpState() {
  if (!efpRefresh || efpRefresh.disabled) return;
  efpRefresh.disabled = true;
  const label = document.getElementById("efp-state");
  const checked = document.getElementById("efp-checked");
  try {
    const response = await fetch(efpRefresh.dataset.url, {credentials: "same-origin", redirect: "error", cache: "no-store"});
    if (!response.ok) throw new Error();
    const status = await response.json();
    label.dataset.state = status.state;
    label.textContent = status.label;
    checked.textContent = status.checked_at ? "Dernier contrôle sur EDOF le " + status.checked_at + " (Paris)."
      : "Aucun contrôle de session enregistré au cours des dernières 24 heures.";
  } catch {
    label.dataset.state = "unknown";
    label.textContent = "État indisponible";
    checked.textContent = "Le serveur de test n’a pas pu transmettre le dernier contrôle.";
  } finally {
    efpRefresh.disabled = false;
  }
}
efpRefresh?.addEventListener("click", refreshEfpState);

function showRetryTime(seconds) {
  const availableAt = Date.now() + seconds * 1000;
  const update = () => {
    const remaining = Math.max(0, Math.ceil((availableAt - Date.now()) / 1000));
    if (!remaining) {
      clearInterval(retryTimer);
      serverMessage.textContent = "Vous pouvez maintenant lancer un nouvel essai sur EDOF.";
      return;
    }
    const delay = remaining < 60 ? remaining + " s" : Math.floor(remaining / 60) + " min " + (remaining % 60) + " s";
    serverMessage.textContent = "Nouvel essai possible dans " + delay + ". Ce délai est commun au serveur. Les dossiers déjà lus restent consultables.";
  };
  retryTimer = setInterval(update, 1000);
  update();
}

async function watchServerTest(jobId) {
  if (polling) return;
  polling = true;
  const stopAt = Date.now() + 245000;
  while (Date.now() < stopAt) {
    await new Promise(resolve => setTimeout(resolve, 2500));
    try {
      const response = await fetch("/admin/edof-test/server/status", {credentials: "same-origin", redirect: "error", cache: "no-store"});
      if (!response.ok) throw new Error();
      const result = await response.json();
      const latest = jobId ? result.jobs.find(job => job.id === jobId) : result.jobs[0];
      if (latest?.finished) {
        location.assign(location.pathname + (latest.code === "read_success" ? "?result=" + encodeURIComponent(latest.id) + "#dossier-lu" : "?attempt=" + encodeURIComponent(latest.id) + "#historique"));
        return;
      }
      serverMessage.textContent = latest?.message || "Essai en cours sur Render…";
    } catch {
      serverMessage.textContent = "Suivi interrompu. L’essai peut continuer sur Render ; rechargez cette page pour consulter son résultat.";
      polling = false;
      return;
    }
  }
  serverMessage.textContent = "Rechargez cette page pour consulter le résultat du serveur.";
  polling = false;
}

async function runServerTest(spec) {
  clearInterval(retryTimer);
  const buttons = [...document.querySelectorAll("#access-test, button[value=refresh]")];
  const previous = buttons.map(button => button.disabled);
  buttons.forEach(button => { button.disabled = true; });
  serverMessage.textContent = "Connexion à EDOF pour une lecture en direct…";
  try {
    const response = await fetch("/admin/edof-test/server/run", {
      method: "POST", credentials: "same-origin", redirect: "error",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": serverCsrf},
      body: JSON.stringify(spec)
    });
    const result = await response.json();
    if (response.status === 429 && result.retry_after > 0) { showRetryTime(result.retry_after); return; }
    if (!response.ok || !result.ok) throw new Error(result.error || "Lancement impossible.");
    serverMessage.textContent = "Lecture en direct sur EDOF. La recherche dans la liste reste disponible.";
    await watchServerTest(result.job_id);
  } catch (error) { serverMessage.textContent = error.message || "Lancement impossible. Reconnectez-vous à Test V2."; }
  finally { buttons.forEach((button, index) => { button.disabled = previous[index]; }); }
}

const directoryStatus = document.getElementById("directory-status");
const matchesBox = document.getElementById("directory-matches");
const syncButton = document.getElementById("sync-directory");
let lookupNumber = 0;
let pendingDirectoryLookup = null;
let syncingDirectory = false;

async function lookupDirectory(spec) {
  const sequence = ++lookupNumber;
  pendingDirectoryLookup = null;
  const panel = document.getElementById("dossier-lu");
  panel.hidden = true;
  matchesBox.textContent = "Recherche dans la liste EDOF…";
  try {
    const response = await fetch("/admin/edof-test/server/directory/lookup", {
      method: "POST", credentials: "same-origin", redirect: "error",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": serverCsrf}, body: JSON.stringify(spec)
    });
    const result = await response.json();
    if (sequence !== lookupNumber) return;
    if (!response.ok) throw new Error(result.error || "Recherche indisponible.");
    if (result.matches?.length === 1) {
      location.assign(result.matches[0].url);
      return;
    }
    if (result.needs_sync) pendingDirectoryLookup = spec;
    matchesBox.textContent = result.needs_sync && syncingDirectory
      ? "Votre recherche sera affichée dès la fin de la première synchronisation."
      : result.message || "Plusieurs dossiers correspondent. Sélectionnez la fiche souhaitée.";
    for (const match of result.matches || []) {
      const link = document.createElement("a");
      link.href = match.url;
      const fields = match.fields;
      link.textContent = [fields.first_name + " " + fields.last_name, fields.title, fields.session_start_date,
                          "n° " + fields.folder_id].filter(Boolean).join(" · ");
      const row = document.createElement("p");
      row.append(link);
      matchesBox.append(row);
    }
  } catch (error) {
    if (sequence === lookupNumber) matchesBox.textContent = error.message || "Recherche indisponible.";
  }
}

async function watchDirectory(id) {
  syncingDirectory = true;
  if (syncButton) syncButton.disabled = true;
  const stopAt = Date.now() + 455000;
  try {
    directoryStatus.textContent = "Synchronisation de la liste EDOF en cours sur le serveur. Vous pouvez continuer vos recherches.";
    while (Date.now() < stopAt) {
      await new Promise(resolve => setTimeout(resolve, 2500));
      const url = id ? "/admin/edof-test/server/status" : "/admin/edof-test/connection-status";
      const response = await fetch(url, {credentials: "same-origin", redirect: "error", cache: "no-store"});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (!id) {
        const sync = data.manual_sync;
        if (!sync || sync.busy) continue;
        directoryStatus.textContent = sync.message;
        if (pendingDirectoryLookup) await lookupDirectory(pendingDirectoryLookup);
        return;
      }
      const job = data.jobs.find(item => item.id === id);
      if (!job || !job.finished) continue;
      void refreshEfpState();
      directoryStatus.textContent = job.code === "directory_ready" ?
        job.candidate_count + " dossiers synchronisés. Vous pouvez rechercher un nom." : job.message;
      if (job.code === "directory_ready" && pendingDirectoryLookup) await lookupDirectory(pendingDirectoryLookup);
      return;
    }
    directoryStatus.textContent = "Consultez l’historique pour connaître le résultat de la synchronisation.";
  } catch {
    directoryStatus.textContent = "Rechargez la page pour voir l’état de la synchronisation.";
  } finally {
    syncingDirectory = false;
    if (syncButton) syncButton.disabled = false;
  }
}

syncButton?.addEventListener("click", async () => {
  syncButton.disabled = true;
  try {
    const response = await fetch("/admin/edof-test/synchroniser", {
      method: "POST", credentials: "same-origin", redirect: "error", headers: {"X-CSRF-Token": serverCsrf, Accept:"application/json"}
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Synchronisation indisponible.");
    await watchDirectory();
  } catch (error) {
    directoryStatus.textContent = error.message || "Synchronisation indisponible.";
    syncButton.disabled = false;
  }
});

document.getElementById("access-test").addEventListener("click", () => runServerTest({mode: "access"}));
document.getElementById("server-read-form").addEventListener("submit", event => {
  event.preventDefault();
  const spec = {mode: "read", folder_id: document.getElementById("server-folder").value.trim(),
    first_name: document.getElementById("server-first").value.trim(), last_name: document.getElementById("server-last").value.trim()};
  if (event.submitter?.value === "refresh") runServerTest(spec);
  else lookupDirectory(spec);
});
const activeJob = document.querySelector("[data-running]");
if (activeJob?.dataset.mode === "directory") watchDirectory(activeJob.dataset.job);
else if (activeJob) watchServerTest(activeJob.dataset.job);
