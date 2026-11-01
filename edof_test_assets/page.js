"use strict";
const csrf = document.querySelector("main").dataset.csrf;
const message = document.getElementById("prepare-message");
async function post(path, data) {
  const response = await fetch(path, {method: "POST", credentials: "same-origin", redirect: "error", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Action impossible. Reconnectez-vous à Test V2.");
  return result;
}
document.getElementById("prepare-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  document.getElementById("pairing").hidden = true;
  message.textContent = "Préparation…";
  try {
    const result = await post("/admin/edof-test/prepare", {folder_id: document.getElementById("folder-id").value.trim()});
    document.getElementById("pair-code").value = result.code;
    document.getElementById("pairing").hidden = false;
    document.getElementById("expiry").textContent = "Valable 15 minutes, pour une seule transmission du dossier choisi. Tout ancien code non utilisé de cette session est annulé.";
    message.textContent = "Copiez ce code dans l’onglet Intégrale EDOF de Chrome.";
  } catch (error) { message.textContent = error.message || "Préparation impossible."; }
  finally { button.disabled = false; }
});
document.getElementById("copy-code").addEventListener("click", async () => {
  const input = document.getElementById("pair-code");
  try { await navigator.clipboard.writeText(input.value); message.textContent = "Code copié."; }
  catch { input.focus(); input.select(); message.textContent = "Copiez le code sélectionné avec ⌘ C."; }
});
document.getElementById("clear-result")?.addEventListener("click", async event => {
  event.currentTarget.disabled = true;
  try { await post("/admin/edof-test/clear", {}); location.replace("/admin/edof-test"); }
  catch { message.textContent = "Effacement impossible. Reconnectez-vous puis réessayez."; event.currentTarget.disabled = false; }
});
