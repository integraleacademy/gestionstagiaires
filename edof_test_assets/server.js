"use strict";
const serverMessage = document.getElementById("server-message");
const serverCsrf = document.querySelector("main").dataset.csrf;
let polling = false;
let retryTimer;

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

async function runServerTest(spec, preferSaved = false) {
  clearInterval(retryTimer);
  const buttons = [...document.querySelectorAll("button")];
  const previous = buttons.map(button => button.disabled);
  buttons.forEach(button => { button.disabled = true; });
  serverMessage.textContent = preferSaved ? "Recherche dans les dossiers déjà lus…" : "Lancement de l’essai sur Render…";
  try {
    const response = await fetch("/admin/edof-test/server/run" + (preferSaved ? "?prefer_saved=1" : ""), {
      method: "POST", credentials: "same-origin", redirect: "error",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": serverCsrf},
      body: JSON.stringify(spec)
    });
    const result = await response.json();
    if (response.status === 429 && result.retry_after > 0) { showRetryTime(result.retry_after); return; }
    if (!response.ok || !result.ok) throw new Error(result.error || "Lancement impossible.");
    if (result.saved) {
      serverMessage.textContent = "Dossier déjà lu. Affichage du résultat enregistré.";
      location.assign(result.result_url);
      return;
    }
    serverMessage.textContent = "Essai en cours sur Render. Vous pouvez fermer votre Chrome.";
    await watchServerTest(result.job_id);
  } catch (error) { serverMessage.textContent = error.message || "Lancement impossible. Reconnectez-vous à Test V2."; }
  finally { buttons.forEach((button, index) => { button.disabled = previous[index]; }); }
}

document.getElementById("access-test").addEventListener("click", () => runServerTest({mode: "access"}));
document.getElementById("server-read-form").addEventListener("submit", event => {
  event.preventDefault();
  runServerTest({mode: "read", folder_id: document.getElementById("server-folder").value.trim(),
    first_name: document.getElementById("server-first").value.trim(), last_name: document.getElementById("server-last").value.trim()}, event.submitter?.value !== "refresh");
});
if (document.querySelector("[data-running]")) watchServerTest();
