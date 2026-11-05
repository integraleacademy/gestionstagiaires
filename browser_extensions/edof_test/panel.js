"use strict";
let pairing = null;
let captured = null;
let generation = 0;
let sending = false;
const $ = id => document.getElementById(id);
function reset() {
  generation += 1; pairing = null; captured = null;
  $("pair-key").value = ""; $("preview").hidden = true;
  for (const id of ["folder", "attendee", "email", "title", "dates"]) $(id).textContent = "";
}
$("reset").addEventListener("click", () => { if (!sending) { reset(); $("status").textContent = "Données locales effacées."; } });
$("arm").addEventListener("click", () => {
  if (sending) return;
  const next = EdofTest.parseKey($("pair-key").value);
  reset();
  if (!next) { $("status").textContent = "Code invalide. Créez un code sur la page Test EDOF direct de Gestion Stagiaires."; return; }
  pairing = next;
  $("status").textContent = `Lecture préparée pour le dossier ${pairing.id}. Rechargez maintenant sa fiche dans EDOF (⌘ R).`;
});
chrome.devtools.network.onRequestFinished.addListener(entry => {
  if (!pairing || sending || !EdofTest.matches(entry.request.url, entry.request.method, entry.response.status, pairing.id)) return;
  const currentGeneration = generation;
  const expectedId = pairing.id;
  // Deliberately do not read request/response headers, cookies or HAR history.
  entry.getContent((content, encoding) => {
    if (!pairing || generation !== currentGeneration || sending) return;
    try {
      if (typeof content !== "string" || content.length > 256 * 1024) throw new Error("Réponse trop volumineuse ou indisponible.");
      const body = encoding === "base64" ? new TextDecoder().decode(Uint8Array.from(atob(content), c => c.charCodeAt(0))) : content;
      captured = EdofTest.sanitize(JSON.parse(body), expectedId);
      const f = captured.folder;
      $("folder").textContent = f.id;
      $("attendee").textContent = `${f.attendee.firstName || ""} ${f.attendee.lastName || ""}`.trim() || "Non renseigné";
      $("email").textContent = f.attendee.email || "Non renseigné";
      $("title").textContent = f.trainingActionInfo.title || "Non renseignée";
      $("dates").textContent = `${f.beginDate || "—"} → ${f.endDate || "—"}`;
      $("preview").hidden = false;
      $("status").textContent = "Dossier détecté. Vérifiez l’aperçu, puis transmettez-le à Gestion Stagiaires.";
    } catch { captured = null; $("preview").hidden = true; $("status").textContent = "Réponse non exploitable. Rechargez le dossier après vous être reconnecté à EDOF si nécessaire."; }
  });
});
$("send").addEventListener("click", async () => {
  if (!captured || !pairing || sending) return;
  sending = true;
  for (const id of ["send", "arm", "reset"]) $(id).disabled = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${EdofTest.ORIGIN}/api/edof-test/receive`, {
      method: "POST", credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json", "X-Edof-Test-Key": pairing.key},
      body: JSON.stringify(captured), signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Transmission refusée.");
    reset();
    $("status").textContent = "Dossier reçu dans Gestion Stagiaires. Ouvrez le résultat avec le lien ci-dessous.";
  } catch (error) {
    $("status").textContent = error.name === "AbortError" ? "Délai dépassé. Consultez d’abord le résultat dans Gestion Stagiaires avant de réessayer." : (error.message || "Transmission impossible.");
  } finally {
    clearTimeout(timer); sending = false;
    for (const id of ["send", "arm", "reset"]) $(id).disabled = false;
  }
});
