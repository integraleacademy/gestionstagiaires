"use strict";
const serverMessage = document.getElementById("server-message");
const serverCsrf = document.querySelector("main").dataset.csrf;
let polling = false;

async function watchServerTest() {
  if (polling) return;
  polling = true;
  const stopAt = Date.now() + 185000;
  while (Date.now() < stopAt) {
    await new Promise(resolve => setTimeout(resolve, 2500));
    try {
      const response = await fetch("/admin/edof-test/server/status", {credentials: "same-origin", redirect: "error", cache: "no-store"});
      if (!response.ok) throw new Error();
      const result = await response.json();
      const latest = result.jobs[0];
      if (latest?.finished) { location.reload(); return; }
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
  const buttons = [...document.querySelectorAll("button")];
  const previous = buttons.map(button => button.disabled);
  buttons.forEach(button => { button.disabled = true; });
  serverMessage.textContent = "Lancement de l’essai sur Render…";
  try {
    const response = await fetch("/admin/edof-test/server/run", {
      method: "POST", credentials: "same-origin", redirect: "error",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": serverCsrf},
      body: JSON.stringify(spec)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Lancement impossible.");
    serverMessage.textContent = "Essai en cours sur Render. Vous pouvez fermer votre Chrome.";
    await watchServerTest();
  } catch (error) { serverMessage.textContent = error.message || "Lancement impossible. Reconnectez-vous à Test V2."; }
  finally { buttons.forEach((button, index) => { button.disabled = previous[index]; }); }
}

document.getElementById("access-test").addEventListener("click", () => runServerTest({mode: "access"}));
document.getElementById("server-read-form").addEventListener("submit", event => {
  event.preventDefault();
  runServerTest({mode: "read", folder_id: document.getElementById("server-folder").value.trim(),
    first_name: document.getElementById("server-first").value.trim(), last_name: document.getElementById("server-last").value.trim()});
});
if (document.querySelector("[data-running]")) watchServerTest();
