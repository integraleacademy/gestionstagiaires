(() => {
  "use strict";
  const configNode = document.getElementById("nativeLiveConfig");
  if (!configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent || "{}"); } catch (_error) { return; }

  const body = document.getElementById("nativeLiveBody");
  const tableWrap = document.getElementById("nativeLiveTableWrap");
  const empty = document.getElementById("nativeLiveEmpty");
  const search = document.getElementById("nativeLiveSearch");
  const updated = document.getElementById("nativeLiveUpdated");
  const connection = document.getElementById("nativeLiveConnection");
  const learnerCount = document.getElementById("nativeLiveLearners");
  const liveCount = document.getElementById("nativeLiveNow");
  const average = document.getElementById("nativeLiveAverage");
  const totalTime = document.getElementById("nativeLiveTotalTime");
  let payload = config.initial || { learners: [], summary: {} };
  let polling = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatDuration(rawSeconds) {
    const seconds = Math.max(0, Math.floor(Number(rawSeconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("fr-FR", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);
  }

  function statusLabel(status) {
    return ({ passed: "Réussi", failed: "À revoir", in_progress: "En cours", not_started: "Non démarré" })[status] || "En cours";
  }

  function makeRow(item) {
    const row = document.createElement("tr");
    row.dataset.search = `${item.trainee_name || ""} ${item.session_name || ""}`.toLocaleLowerCase("fr");

    const personCell = document.createElement("td");
    const person = element("div", "nellive-person");
    person.append(element("i", `nellive-person__dot${item.live ? " is-live" : ""}`));
    const personCopy = document.createElement("div");
    personCopy.append(element("strong", "", item.trainee_name || item.trainee_id));
    personCopy.append(element("span", "", item.session_name || item.session_id));
    person.append(personCopy);
    personCell.append(person);
    row.append(personCell);

    const statusCell = document.createElement("td");
    statusCell.append(element("span", `nellive-status nellive-status--${item.status || "in_progress"}`, statusLabel(item.status)));
    row.append(statusCell);
    row.append(element("td", "", item.activity_title || "En attente de reprise"));

    const progressCell = document.createElement("td");
    const progress = element("div", "nellive-progress");
    const track = document.createElement("div");
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(0, Math.min(100, Number(item.progress_percent) || 0))}%`;
    track.append(fill);
    progress.append(track, element("span", "", `${Math.round(Number(item.progress_percent) || 0)} %`));
    progressCell.append(progress);
    row.append(progressCell);
    row.append(element("td", "", `${Math.round(Number(item.score_percent) || 0)} %`));
    row.append(element("td", "nellive-time", item.active_time_label || "00:00:00"));
    row.append(element("td", "", item.live ? "Maintenant" : formatDate(item.updated_at)));
    return row;
  }

  function applySearch() {
    const query = (search?.value || "").trim().toLocaleLowerCase("fr");
    body?.querySelectorAll("tr").forEach((row) => {
      row.hidden = Boolean(query && !row.dataset.search.includes(query));
    });
  }

  function render(nextPayload) {
    payload = nextPayload || payload;
    const learners = Array.isArray(payload.learners) ? payload.learners : [];
    if (learnerCount) learnerCount.textContent = String(learners.length);
    if (liveCount) liveCount.textContent = String(learners.filter((item) => item.live).length);
    const averageValue = learners.length
      ? learners.reduce((sum, item) => sum + (Number(item.progress_percent) || 0), 0) / learners.length
      : 0;
    if (average) average.textContent = `${Math.round(averageValue)} %`;
    if (totalTime) totalTime.textContent = formatDuration(learners.reduce((sum, item) => sum + (Number(item.active_seconds) || 0), 0));
    if (body) {
      body.replaceChildren(...learners.map(makeRow));
      applySearch();
    }
    if (empty) empty.hidden = learners.length > 0;
    if (tableWrap) tableWrap.hidden = learners.length === 0;
    if (updated) updated.textContent = `Mis à jour à ${new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date())}`;
  }

  function setConnected(connected) {
    connection?.classList.toggle("is-offline", !connected);
    const label = connection?.querySelector("b");
    if (label) label.textContent = connected ? "Connecté" : "Reconnexion…";
  }

  async function refresh() {
    if (polling || document.visibilityState === "hidden") return;
    polling = true;
    try {
      const response = await fetch(config.liveUrl, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } });
      const nextPayload = await response.json();
      if (!response.ok || nextPayload.ok === false) throw new Error(nextPayload.error || "refresh_failed");
      render(nextPayload);
      setConnected(true);
    } catch (_error) {
      setConnected(false);
    } finally {
      polling = false;
    }
  }

  search?.addEventListener("input", applySearch);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
  render(payload);
  window.setInterval(refresh, 10000);
})();
