(() => {
  "use strict";

  const configNode = document.getElementById("nativeElearningConfig");
  if (!configNode) return;

  let config;
  try {
    config = JSON.parse(configNode.textContent || "{}");
  } catch (_error) {
    return;
  }

  const timer = document.getElementById("nativeActiveTimer");
  const trackingState = document.getElementById("nativeTrackingState");
  const duplicateNotice = document.getElementById("nativeDuplicateNotice");
  const actionButton = document.getElementById("nativeActionButton");
  const feedback = document.getElementById("nativeAnswerFeedback");
  const courseResult = document.getElementById("nativeCourseResult");
  const progressBar = document.getElementById("nativeProgressBar");
  const progressLabel = document.getElementById("nativeProgressLabel");
  const scoreLabel = document.getElementById("nativeScoreLabel");
  const toast = document.getElementById("nativeToast");
  const questionForm = document.getElementById("nativeQuestionForm");
  const videos = Array.from(document.querySelectorAll(".native-course-video"));

  const state = {
    trackingSessionId: "",
    heartbeatRunning: false,
    stopped: false,
    serverActive: false,
    baseSeconds: Number(config.initialActiveSeconds || 0),
    displayAnchor: Date.now(),
    lastInteraction: Date.now(),
    toastTimeout: 0,
  };

  function makeId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  }

  let tabId = "";
  try {
    tabId = sessionStorage.getItem("nativeElearningTabId") || makeId();
    sessionStorage.setItem("nativeElearningTabId", tabId);
  } catch (_error) {
    tabId = makeId();
  }

  function formatSeconds(rawSeconds) {
    const total = Math.max(0, Math.floor(Number(rawSeconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const seconds = total % 60;
    return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
  }

  function renderTimer() {
    const extra = state.serverActive ? Math.max(0, (Date.now() - state.displayAnchor) / 1000) : 0;
    if (timer) timer.textContent = formatSeconds(state.baseSeconds + extra);
  }

  function setTrackingState(nextState, label) {
    if (!trackingState) return;
    trackingState.dataset.state = nextState;
    const text = trackingState.querySelector("span");
    if (text) text.textContent = label;
  }

  function showToast(message, isError = false) {
    if (!toast) return;
    window.clearTimeout(state.toastTimeout);
    toast.textContent = message;
    toast.classList.toggle("is-error", isError);
    toast.classList.add("is-visible");
    state.toastTimeout = window.setTimeout(() => toast.classList.remove("is-visible"), 4200);
  }

  async function postJson(url, payload, options = {}) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      keepalive: Boolean(options.keepalive),
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Elearning-CSRF": config.csrfToken,
      },
      body: JSON.stringify({ access_token: config.accessToken, ...payload }),
    });
    let result = {};
    try {
      result = await response.json();
    } catch (_error) {
      result = {};
    }
    if (!response.ok || result.ok === false) {
      const error = new Error(result.error || "Le serveur de suivi ne répond pas.");
      error.status = response.status;
      throw error;
    }
    return result;
  }

  function activitySignals() {
    const recent = (Date.now() - state.lastInteraction) / 1000 <= Number(config.idleSeconds || 120);
    const mediaPlaying = videos.some((video) => !video.paused && !video.ended && video.readyState >= 2);
    return {
      visible: document.visibilityState === "visible",
      focused: document.hasFocus(),
      recent_activity: recent,
      media_playing: mediaPlaying,
    };
  }

  function applyProgress(progress) {
    if (!progress) return;
    const activeSeconds = Number(progress.active_seconds);
    if (Number.isFinite(activeSeconds)) {
      state.baseSeconds = activeSeconds;
      state.displayAnchor = Date.now();
      renderTimer();
    }
    const percent = Math.max(0, Math.min(100, Number(progress.progress_percent) || 0));
    if (progressBar) progressBar.style.width = `${percent}%`;
    if (progressLabel) progressLabel.textContent = `${Math.round(percent)} %`;
    if (scoreLabel) scoreLabel.textContent = `${Math.round(Number(progress.score_percent) || 0)} %`;
  }

  async function sendHeartbeat() {
    if (!state.trackingSessionId || state.heartbeatRunning || state.stopped) return;
    state.heartbeatRunning = true;
    try {
      const result = await postJson(config.heartbeatUrl, {
        tracking_session_id: state.trackingSessionId,
        activity_id: config.activityId,
        ...activitySignals(),
      });
      applyProgress(result.progress);
      state.serverActive = Boolean(result.active);
      state.displayAnchor = Date.now();
      if (result.duplicate) {
        setTrackingState("duplicate", "Autre onglet actif");
        if (duplicateNotice) duplicateNotice.classList.add("is-visible");
      } else {
        if (duplicateNotice) duplicateNotice.classList.remove("is-visible");
        setTrackingState(
          result.active ? "active" : "paused",
          result.active ? "Chrono actif" : "Chrono en pause"
        );
      }
    } catch (error) {
      state.serverActive = false;
      state.displayAnchor = Date.now();
      setTrackingState("offline", "Suivi déconnecté");
      if ([401, 403, 409].includes(Number(error.status))) showToast("Votre accès ou le parcours a changé. Rechargez la page.", true);
    } finally {
      state.heartbeatRunning = false;
      renderTimer();
    }
  }

  async function startTracking() {
    state.stopped = false;
    setTrackingState("connecting", "Connexion…");
    try {
      const result = await postJson(config.startUrl, {
        tab_id: tabId,
        activity_id: config.activityId,
      });
      state.trackingSessionId = result.tracking_session_id || "";
      applyProgress(result.progress);
      await sendHeartbeat();
    } catch (_error) {
      setTrackingState("offline", "Suivi déconnecté");
      showToast("Impossible de démarrer le suivi du temps. Rechargez la page.", true);
    }
  }

  function finishTracking() {
    if (!state.trackingSessionId || state.stopped) return;
    state.stopped = true;
    state.serverActive = false;
    postJson(
      config.finishUrl,
      { tracking_session_id: state.trackingSessionId, activity_id: config.activityId },
      { keepalive: true }
    ).catch(() => {});
  }

  let activityHeartbeatTimeout = 0;
  function markActivity() {
    const wasIdle = (Date.now() - state.lastInteraction) / 1000 > Number(config.idleSeconds || 120);
    state.lastInteraction = Date.now();
    if (wasIdle) {
      window.clearTimeout(activityHeartbeatTimeout);
      activityHeartbeatTimeout = window.setTimeout(sendHeartbeat, 150);
    }
  }

  ["pointerdown", "keydown", "touchstart", "scroll"].forEach((eventName) => {
    window.addEventListener(eventName, markActivity, { passive: true });
  });
  window.addEventListener("focus", () => { markActivity(); sendHeartbeat(); });
  window.addEventListener("blur", sendHeartbeat);
  document.addEventListener("visibilitychange", sendHeartbeat);
  videos.forEach((video) => {
    ["play", "pause", "ended", "seeking"].forEach((eventName) => {
      video.addEventListener(eventName, () => { markActivity(); sendHeartbeat(); });
    });
  });

  function restoreSavedAnswer() {
    const answer = config.savedAnswer || {};
    if (config.questionType === "matching" && Array.isArray(answer.selected)) {
      document.querySelectorAll("[data-match-index]").forEach((select) => {
        const index = Number(select.dataset.matchIndex);
        if (answer.selected[index]) select.value = answer.selected[index];
      });
    }
    if (config.questionType === "fill_blank" && answer.groups) {
      document.querySelectorAll(".native-elearning-blank[data-group-id]").forEach((select) => {
        const value = answer.groups[select.dataset.groupId];
        if (value) select.value = value;
        if (config.activityCompleted) select.disabled = true;
      });
    }
  }

  function collectAnswer() {
    if (["single_choice", "multiple_choice", "statement"].includes(config.questionType)) {
      const selected = Array.from(document.querySelectorAll('input[name="answer"]:checked')).map((input) => input.value);
      if (!selected.length) throw new Error("Sélectionnez au moins une réponse.");
      return { selected };
    }
    if (config.questionType === "matching") {
      const selects = Array.from(document.querySelectorAll("[data-match-index]"));
      const selected = selects.map((select) => select.value);
      if (!selected.length || selected.some((value) => !value)) {
        throw new Error("Réalisez toutes les associations avant de valider.");
      }
      return { selected };
    }
    if (config.questionType === "fill_blank") {
      const selects = Array.from(document.querySelectorAll(".native-elearning-blank[data-group-id]"));
      const groups = {};
      selects.forEach((select) => { groups[select.dataset.groupId] = select.value; });
      if (!selects.length || selects.some((select) => !select.value)) {
        throw new Error("Complétez toutes les zones avant de valider.");
      }
      return { groups };
    }
    throw new Error("Cette question ne peut pas encore être validée.");
  }

  function showAnswerFeedback(correct) {
    if (!feedback) return;
    feedback.classList.remove("is-correct", "is-incorrect");
    feedback.classList.add("is-visible", correct ? "is-correct" : "is-incorrect");
    feedback.textContent = correct
      ? "Bonne réponse enregistrée."
      : "Réponse enregistrée. La correction sera reprise avec votre formateur.";
    feedback.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function showCourseResult(progress) {
    if (!courseResult || !progress || !["passed", "failed"].includes(progress.status)) return;
    const score = Math.round(Number(progress.score_percent) || 0);
    courseResult.classList.add("is-visible");
    const title = courseResult.querySelector("strong");
    const detail = courseResult.querySelector("span");
    if (title) title.textContent = "Cours terminé";
    if (detail) {
      detail.textContent = progress.status === "passed"
        ? `Objectif atteint avec un score de ${score} %.`
        : `Parcours terminé avec un score de ${score} %. L’équipe pédagogique pourra vous accompagner.`;
    }
    courseResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function handleAction() {
    if (!actionButton || actionButton.disabled) return;
    const mode = actionButton.dataset.mode;
    if (mode === "navigate") {
      window.location.assign(config.isLastActivity ? (config.endUrl || config.portalUrl) : config.nextUrl);
      return;
    }
    actionButton.disabled = true;
    const originalLabel = actionButton.textContent;
    actionButton.textContent = "Enregistrement…";
    try {
      if (mode === "answer") {
        const result = await postJson(config.answerUrl, { answer: collectAnswer() });
        applyProgress(result.progress);
        showAnswerFeedback(Boolean(result.correct));
        showCourseResult(result.progress);
        actionButton.dataset.mode = "navigate";
        actionButton.textContent = config.isLastActivity ? `${config.endLabel || 'Retour au parcours'} →` : "Continuer →";
        questionForm?.querySelectorAll("input,select").forEach((field) => { field.disabled = true; });
      } else {
        const result = await postJson(config.completeUrl, {});
        applyProgress(result.progress);
        if (config.isLastActivity) {
          showCourseResult(result.progress);
          actionButton.dataset.mode = "navigate";
          actionButton.textContent = `${config.endLabel || 'Retour au parcours'} →`;
        } else {
          window.location.assign(config.nextUrl);
          return;
        }
      }
    } catch (error) {
      showToast(error.message || "Impossible d’enregistrer cette activité.", true);
      actionButton.textContent = originalLabel;
    } finally {
      actionButton.disabled = false;
    }
  }

  actionButton?.addEventListener("click", handleAction);
  questionForm?.addEventListener("submit", (event) => { event.preventDefault(); handleAction(); });

  document.querySelectorAll(".native-block--checklistitem,.native-block--howtoitem").forEach((item) => {
    item.tabIndex = 0;
    item.setAttribute("role", "checkbox");
    item.setAttribute("aria-checked", "false");
    const toggle = () => {
      const checked = item.classList.toggle("is-checked");
      item.setAttribute("aria-checked", String(checked));
      markActivity();
    };
    item.addEventListener("click", toggle);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggle(); }
    });
  });

  document.querySelectorAll(".flip-card-wrapper").forEach((card) => {
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-pressed", "false");
    const flip = () => {
      const flipped = card.classList.toggle("is-flipped");
      card.setAttribute("aria-pressed", String(flipped));
      markActivity();
    };
    card.addEventListener("click", flip);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); flip(); }
    });
  });

  const menuButton = document.getElementById("nativeMenuButton");
  const sidebar = document.getElementById("nativeSidebar");
  const sidebarOverlay = document.getElementById("nativeSidebarOverlay");
  function setMenu(open) {
    sidebar?.classList.toggle("is-open", open);
    sidebarOverlay?.classList.toggle("is-open", open);
    menuButton?.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
  }
  menuButton?.addEventListener("click", () => setMenu(!sidebar?.classList.contains("is-open")));
  sidebarOverlay?.addEventListener("click", () => setMenu(false));
  window.addEventListener("keydown", (event) => { if (event.key === "Escape") setMenu(false); });

  restoreSavedAnswer();
  renderTimer();
  startTracking();
  window.setInterval(renderTimer, 1000);
  window.setInterval(sendHeartbeat, Math.max(5, Number(config.heartbeatSeconds || 15)) * 1000);
  window.addEventListener("pagehide", (event) => { if (!event.persisted) finishTracking(); });
  window.addEventListener("pageshow", (event) => { if (event.persisted && state.stopped) startTracking(); });
})();
