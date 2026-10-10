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
  const requiredVideos = videos.filter((video) => Object.prototype.hasOwnProperty.call(config.requiredVideos || {}, video.dataset.requiredVideo));
  const videoReaders = new Map();
  const playbackRates = [0.85, 0.9, 1];
  const allowedPlaybackRate = (rate) => playbackRates.includes(Number(rate));
  const remainingTime = document.getElementById("nativeRemainingTime");
  const durationStatus = document.getElementById("nativeDurationStatus");
  const idleNotice = document.getElementById("nativeIdleNotice");
  const idleMilliseconds = Number(config.idleSeconds || 300) * 1000;

  const state = {
    trackingSessionId: "",
    heartbeatRunning: false,
    heartbeatQueued: false,
    stopped: false,
    serverActive: false,
    serverMediaActive: false,
    playbackAvailable: false,
    lastReceipt: 0,
    idlePaused: false,
    baseSeconds: Number(config.initialActiveSeconds || 0),
    displayAnchor: Date.now(),
    lastInteraction: Date.now(),
    toastTimeout: 0,
    saving: false,
    progress: {
      remaining_seconds: Number(config.initialRemainingSeconds || 0),
      module_complete: Boolean(config.initialModuleComplete),
      video_progress: config.initialVideoProgress || {},
    },
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

  function displayedSeconds() {
    const extra = state.serverActive ? Math.max(0, Math.min(
      Date.now() - state.displayAnchor, 20000,
      confirmedPlayback() ? 20000 : state.lastInteraction + idleMilliseconds - state.displayAnchor
    ) / 1000) : 0;
    return state.baseSeconds + extra;
  }

  function renderTimer() {
    if (timer) timer.textContent = formatSeconds(displayedSeconds());
  }

  function pauseDisplay() {
    state.baseSeconds = displayedSeconds();
    state.serverActive = false;
    state.displayAnchor = Date.now();
    renderTimer();
  }

  function updateAction() {
    if (!actionButton) return;
    const blocked = actionButton.dataset.mode === "navigate" && config.isLastActivity
      && config.hasNextModule && !state.progress.module_complete;
    const videoBlocked = requiredVideos.some((video) => !videoCompleted(video));
    actionButton.disabled = state.saving || blocked || videoBlocked;
    if (videoBlocked && !state.saving) {
      actionButton.textContent = "Regardez la vidéo jusqu’à la fin";
      return;
    }
    if (requiredVideos.length && !state.saving && !blocked) {
      actionButton.textContent = actionButton.dataset.mode === "navigate"
        ? `${config.isLastActivity ? (config.endLabel || 'Retour au parcours') : 'Continuer'} →`
        : `${config.isLastActivity ? 'Terminer le module' : 'Terminer et continuer'} →`;
    }
    if (actionButton.dataset.mode === "navigate" && config.isLastActivity && !state.saving) {
      actionButton.textContent = blocked
        ? (state.progress.remaining_seconds > 0 ? `Encore ${formatSeconds(state.progress.remaining_seconds)} de temps actif` : "Terminez les activités du module")
        : `${config.endLabel || 'Retour au parcours'} →`;
    }
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
    const age = Math.max(0, (Date.now() - state.lastInteraction) / 1000);
    const recent = age < idleMilliseconds / 1000;
    const mediaPlaying = videos.some((video) => !video.paused && !video.ended && video.readyState >= 2);
    return {
      visible: document.visibilityState === "visible",
      focused: document.hasFocus(),
      recent_activity: recent,
      media_playing: mediaPlaying,
      interaction_age_seconds: age,
    };
  }

  function advancingVideo(video) {
    const reader = videoReaders.get(video);
    return Boolean(reader && !reader.waiting && reader.lastAdvance !== null
      && Date.now() - reader.lastAdvance < 6000 && !video.paused && !video.ended
      && !video.seeking && video.readyState >= 2 && allowedVideoRate(video)
      && document.visibilityState === "visible" && document.hasFocus());
  }

  function allowedVideoRate(video) {
    const reader = videoReaders.get(video);
    return (reader?.pacing?.rates || reader?.allowedRates || [1]).includes(video.playbackRate);
  }

  function enforceVideoRate(video) {
    const reader = videoReaders.get(video);
    // attach() sets the reviewed default rate before returning its policy.
    // Some players dispatch ratechange synchronously during that assignment.
    if (reader?.pacingInitializing) return;
    const pacing = reader?.pacing;
    if ((pacing || !videoCompleted(video)) && !allowedVideoRate(video)) video.playbackRate = pacing ? .85 : 1;
  }

  function learningPauseActive() {
    return state.playbackAvailable && requiredVideos.some(video => {
      const reader = videoReaders.get(video);
      return reader?.pacing?.isPausing() || (!reader?.waiting && reader?.pacing?.isResuming());
    });
  }

  function confirmedPlayback() {
    return state.serverMediaActive && Date.now() - state.lastReceipt < 10000
      && requiredVideos.some(advancingVideo);
  }

  function videoProgress(video) {
    return state.progress.video_progress?.[config.activityId]?.[video.dataset.requiredVideo] || {};
  }

  function videoCompleted(video) {
    return videoProgress(video).completed === true;
  }

  function videoSignals() {
    return requiredVideos.map((video) => ({
      id: video.dataset.requiredVideo,
      position: Math.max(0, Number(video.currentTime) || 0),
      rate: Number(video.playbackRate) || 1,
      playing: !video.paused && !video.ended && !video.seeking && video.readyState >= 2
        && !videoReaders.get(video)?.waiting,
      ended: video.ended,
    }));
  }

  function pauseRequiredVideos(reset = false) {
    optionalVideoPacing.forEach((pacing, video) => {
      pacing?.cancelPause();
      if (!video.paused) video.pause();
    });
    requiredVideos.forEach((video) => {
      videoReaders.get(video)?.pacing?.cancelPause();
      if (!video.paused) video.pause();
      if (videoCompleted(video)) return;
      if (reset && video.readyState >= 1) {
        const reader = videoReaders.get(video);
        const position = Number(videoProgress(video).watched_seconds) || 0;
        if (reader) reader.maximum = position;
        if (Math.abs(video.currentTime - position) > .05) video.currentTime = position;
      }
    });
  }

  function renderVideoProgress() {
    requiredVideos.forEach((video) => {
      const reader = videoReaders.get(video);
      if (!reader) return;
      const progress = videoProgress(video);
      const confirmed = Number(progress.watched_seconds) || 0;
      reader.maximum = Math.max(reader.maximum, confirmed);
      reader.pacing?.markPast(confirmed);
      const percent = Math.min(100, confirmed / Number(config.requiredVideos[video.dataset.requiredVideo]) * 100);
      const panel = reader.panel;
      if (!panel) return;
      panel.classList.toggle("is-complete", progress.completed === true);
      const status = panel.querySelector("[data-video-status]");
      if (status) status.textContent = progress.completed ? "Vidéo entièrement visionnée ✓"
        : `Visionnage enregistré : ${Math.floor(percent)} %`;
      const bar = panel.querySelector('[role="progressbar"]');
      bar?.setAttribute("aria-valuenow", String(Math.floor(percent)));
      const fill = bar?.querySelector("i");
      if (fill) fill.style.width = `${percent}%`;
      document.querySelectorAll("[data-video-chapters]").forEach((chapters) => {
        if (chapters.dataset.videoChapters !== video.dataset.requiredVideo) return;
        const unlocked = progress.completed === true;
        chapters.querySelectorAll("[data-chapter-start]").forEach((button) => { button.disabled = !unlocked; });
        const hint = chapters.querySelector("[data-chapter-hint]");
        if (hint) hint.textContent = unlocked
          ? "Choisissez un chapitre pour revoir un passage."
          : "Les chapitres deviennent accessibles après le visionnage complet.";
      });
    });
  }

  function setupRequiredVideos() {
    const panels = Array.from(document.querySelectorAll("[data-video-followup]"));
    const rateSelectors = Array.from(document.querySelectorAll("[data-video-rate]"));
    requiredVideos.forEach((video) => {
      const rateSelector = rateSelectors.find((select) => select.dataset.videoRate === video.dataset.requiredVideo);
      if (rateSelector) {
        try {
          const savedRate = Number(sessionStorage.getItem("nativeElearningPlaybackRate"));
          if (allowedPlaybackRate(savedRate)) video.playbackRate = savedRate;
        } catch (_error) { /* The control remains usable without browser storage. */ }
        rateSelector.value = String(video.playbackRate);
        rateSelector.addEventListener("change", () => {
          const rate = Number(rateSelector.value);
          if (!allowedPlaybackRate(rate)) return;
          markActivity();
          video.playbackRate = rate;
          try { sessionStorage.setItem("nativeElearningPlaybackRate", String(rate)); } catch (_error) { /* Optional preference. */ }
        });
      }
      const reader = { maximum: Number(videoProgress(video).watched_seconds) || 0,
        allowedRates: rateSelector ? playbackRates : [1],
        lastPosition: 0, lastTime: Date.now(), lastRate: video.playbackRate,
        lastAdvance: null, waiting: false, restored: false,
        panel: panels.find((panel) => panel.dataset.videoFollowup === video.dataset.requiredVideo) };
      videoReaders.set(video, reader);
      const anchor = () => {
        reader.lastPosition = video.currentTime; reader.lastTime = Date.now(); reader.lastRate = video.playbackRate;
      };
      const restore = () => {
        if (reader.restored || video.readyState < 1) return;
        reader.restored = true;
        if (!videoCompleted(video) && reader.maximum > 0) {
          video.currentTime = Math.min(reader.maximum, Math.max(0, video.duration - .1));
        }
        anchor();
      };
      video.addEventListener("loadedmetadata", restore);
      restore();
      video.addEventListener("timeupdate", () => {
        const elapsed = Math.max(0, (Date.now() - reader.lastTime) / 1000);
        const delta = video.currentTime - reader.lastPosition;
        const possibleAdvance = elapsed * Math.max(reader.lastRate, video.playbackRate);
        if (!video.paused && !video.seeking && allowedVideoRate(video) && !reader.waiting
            && document.visibilityState === "visible" && document.hasFocus()
            && delta > 0 && delta <= possibleAdvance + .5
            && (videoCompleted(video) || video.currentTime <= reader.maximum + possibleAdvance + .5)) {
          reader.lastAdvance = Date.now();
          if (!videoCompleted(video)) reader.maximum = Math.max(reader.maximum, video.currentTime);
        }
        anchor();
      });
      video.addEventListener("seeking", () => {
        reader.lastAdvance = null;
        if (!videoCompleted(video) && video.currentTime > reader.maximum + .25) {
          video.currentTime = reader.maximum;
          showToast("Regardez ce passage avant d’avancer dans la vidéo.");
        }
        anchor();
      });
      video.addEventListener("seeked", () => { anchor(); sendHeartbeat(); });
      video.addEventListener("ratechange", () => {
        reader.lastAdvance = null;
        enforceVideoRate(video);
        if (rateSelector) rateSelector.value = String(video.playbackRate);
        anchor();
        sendHeartbeat();
      });
      const playing = () => {
        if (!state.trackingSessionId || document.visibilityState !== "visible" || !document.hasFocus()) {
          video.pause();
          return;
        }
        requiredVideos.forEach((other) => { if (other !== video && !other.paused) other.pause(); });
        enforceVideoRate(video);
        reader.waiting = false;
        anchor();
        sendHeartbeat();
      };
      video.addEventListener("play", playing);
      video.addEventListener("playing", playing);
      ["pause", "ended", "waiting"].forEach((eventName) => video.addEventListener(eventName, () => {
        reader.waiting = eventName === "waiting";
        reader.lastAdvance = null;
        anchor(); scheduleIdlePause(); sendHeartbeat();
      }));
      video.addEventListener("error", () => {
        showToast("La vidéo ne peut pas être chargée. Vérifiez votre connexion puis rechargez la page.", true);
      });
      reader.pacingInitializing = true;
      reader.pacing = window.NativeVideoPacing?.attach(video, {
        savedPosition: reader.maximum,
        canResume: () => Boolean(state.trackingSessionId && !state.stopped && state.playbackAvailable),
        beforePause: (position) => {
          // Decoded-frame callbacks can precede timeupdate. Record only the
          // same small, naturally reached prefix before snapping to its frame.
          const elapsed = Math.max(0, (Date.now() - reader.lastTime) / 1000);
          if (!video.paused && !video.seeking && !reader.waiting && allowedVideoRate(video)
              && position >= reader.lastPosition && position <= video.currentTime + .00001
              && position - reader.lastPosition <= elapsed * video.playbackRate + .5
              && position <= reader.maximum + elapsed * video.playbackRate + .5) {
            reader.maximum = Math.max(reader.maximum, position);
          }
        },
      });
      reader.pacingInitializing = false;
      enforceVideoRate(video);
    });
    document.querySelectorAll("[data-video-chapters]").forEach((chapters) => {
      const video = requiredVideos.find((item) => item.dataset.requiredVideo === chapters.dataset.videoChapters);
      chapters.querySelectorAll("[data-chapter-start]").forEach((button) => {
        button.addEventListener("click", () => {
          if (!video || !videoCompleted(video)) return;
          const position = Number(button.dataset.chapterStart);
          if (!Number.isFinite(position) || position < 0 || position >= video.duration) return;
          video.pause();
          video.currentTime = position;
          video.focus();
          showToast("Chapitre sélectionné. Appuyez sur lecture pour le revoir.");
        });
      });
    });
    renderVideoProgress();
  }

  // Existing enrolments can watch the new explanations without changing their
  // completion requirements. They use the same pace and learning pauses.
  const optionalVideoPacing = new Map();
  function setupOptionalVideos() {
    document.querySelectorAll('.native-video-shell video').forEach((video) => {
      if (requiredVideos.includes(video) || !video.closest('.native-video-shell')?.querySelector('[data-video-pacing-config]')) return;
      optionalVideoPacing.set(video, window.NativeVideoPacing?.attach(video, {
        canResume: () => Boolean(state.trackingSessionId && !state.stopped && state.playbackAvailable),
      }));
    });
  }

  function applyProgress(progress) {
    if (!progress) return;
    state.progress = progress;
    renderVideoProgress();
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
    if (remainingTime) remainingTime.textContent = formatSeconds(progress.remaining_seconds);
    if (durationStatus) durationStatus.textContent = progress.duration_met ? "Durée obligatoire atteinte" : "Temps actif restant";
    updateAction();
    showCourseResult(progress);
  }

  async function sendHeartbeat() {
    if (!state.trackingSessionId || state.stopped) return;
    if (state.heartbeatRunning) { state.heartbeatQueued = true; return; }
    state.heartbeatRunning = true;
    try {
      const result = await postJson(config.heartbeatUrl, {
        tracking_session_id: state.trackingSessionId,
        activity_id: config.activityId,
        ...activitySignals(),
        videos: videoSignals(),
      });
      applyProgress(result.progress);
      for (const video of requiredVideos) {
        const position = result.video_resync?.[video.dataset.requiredVideo];
        if (Number.isFinite(position)) {
          videoReaders.get(video)?.pacing?.cancelPause();
          video.pause();
          videoReaders.get(video).maximum = position;
          if (Math.abs(video.currentTime - position) > .05) video.currentTime = position;
          showToast("Reprenez la vidéo à la dernière position enregistrée.");
        }
      }
      state.serverMediaActive = Boolean(result.media_active);
      state.playbackAvailable = !result.duplicate;
      state.lastReceipt = Date.now();
      state.serverActive = Boolean(result.active) && document.visibilityState === "visible" && document.hasFocus()
        && (activitySignals().recent_activity || confirmedPlayback());
      state.displayAnchor = Date.now();
      if (result.duplicate) {
        pauseRequiredVideos(true);
        setTrackingState("duplicate", "Autre onglet actif");
        if (duplicateNotice) duplicateNotice.classList.add("is-visible");
      } else {
        if (duplicateNotice) duplicateNotice.classList.remove("is-visible");
        setTrackingState(
          state.serverActive ? "active" : "paused",
          state.serverActive ? "Chrono actif" : (activitySignals().recent_activity ? "Chrono en pause" : "Pause · inactif depuis 5 min")
        );
      }
      scheduleIdlePause();
    } catch (error) {
      pauseRequiredVideos(true);
      state.playbackAvailable = false;
      state.serverActive = false;
      state.serverMediaActive = false;
      state.displayAnchor = Date.now();
      setTrackingState("offline", "Suivi déconnecté");
      if ([401, 403, 409].includes(Number(error.status))) showToast("Votre accès ou le parcours a changé. Rechargez la page.", true);
    } finally {
      state.heartbeatRunning = false;
      if (state.heartbeatQueued) {
        state.heartbeatQueued = false;
        window.setTimeout(sendHeartbeat, 0);
      }
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
    state.playbackAvailable = false;
    pauseRequiredVideos();
    state.serverActive = false;
    postJson(
      config.finishUrl,
      { tracking_session_id: state.trackingSessionId, activity_id: config.activityId },
      { keepalive: true }
    ).catch(() => {});
  }

  let activityHeartbeatTimeout = 0;
  let idleTimeout = 0;
  function scheduleIdlePause() {
    window.clearTimeout(idleTimeout);
    const remaining = state.lastInteraction + idleMilliseconds - Date.now();
    if (remaining <= 0 && (confirmedPlayback() || learningPauseActive())) {
      state.idlePaused = false;
      if (idleNotice) idleNotice.hidden = true;
      // Watching is evidenced by advancing video and server receipts, never by
      // manufacturing pointer events or resetting the learner interaction age.
      idleTimeout = window.setTimeout(scheduleIdlePause, 1000);
      return;
    }
    idleTimeout = window.setTimeout(() => {
      if (confirmedPlayback() || learningPauseActive()) { scheduleIdlePause(); return; }
      if (state.idlePaused) return;
      state.idlePaused = true;
      pauseRequiredVideos();
      pauseDisplay();
      setTrackingState("paused", "Pause · inactif depuis 5 min");
      if (idleNotice) idleNotice.hidden = false;
      sendHeartbeat();
    }, Math.max(0, remaining));
  }
  function markActivity() {
    const wasIdle = Date.now() - state.lastInteraction >= idleMilliseconds;
    if (wasIdle) pauseDisplay();
    state.lastInteraction = Date.now();
    state.idlePaused = false;
    if (idleNotice) idleNotice.hidden = true;
    scheduleIdlePause();
    if (wasIdle) {
      window.clearTimeout(activityHeartbeatTimeout);
      activityHeartbeatTimeout = window.setTimeout(sendHeartbeat, 150);
    }
  }

  ["pointerdown", "pointermove", "keydown", "touchstart", "scroll"].forEach((eventName) => {
    window.addEventListener(eventName, markActivity, { passive: true });
  });
  window.addEventListener("focus", () => { markActivity(); sendHeartbeat(); });
  window.addEventListener("blur", () => { pauseRequiredVideos(); pauseDisplay(); sendHeartbeat(); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") { pauseRequiredVideos(); pauseDisplay(); }
    sendHeartbeat();
  });
  document.getElementById("nativeResumeTimer")?.addEventListener("click", () => { markActivity(); sendHeartbeat(); });
  videos.filter((video) => !requiredVideos.includes(video)).forEach((video) => {
    ["play", "pause", "ended", "seeking"].forEach((eventName) => {
      // Playback events (including autoplay/ended) are not learner interactions.
      video.addEventListener(eventName, sendHeartbeat);
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

  function showAnswerFeedback(correct, retryRequired = false) {
    if (!feedback) return;
    feedback.classList.remove("is-correct", "is-incorrect");
    feedback.classList.add("is-visible", correct ? "is-correct" : "is-incorrect");
    feedback.textContent = correct
      ? "Bonne réponse enregistrée."
      : retryRequired ? "À reprendre : consultez l’explication et choisissez à nouveau avant de continuer."
      : "Réponse enregistrée. La correction sera reprise avec votre formateur.";
    feedback.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function showCourseResult(progress, scroll = false) {
    if (!courseResult || !progress) return;
    if (!["passed", "failed", "awaiting_time"].includes(progress.status)) {
      courseResult.classList.remove("is-visible"); return;
    }
    const score = Math.round(Number(progress.score_percent) || 0);
    courseResult.dataset.status = progress.status;
    courseResult.classList.add("is-visible");
    const title = courseResult.querySelector("strong");
    const detail = courseResult.querySelector("span");
    if (title) title.textContent = progress.status === "awaiting_time" ? "Activités terminées · temps à compléter" : "Module terminé";
    if (detail) {
      detail.textContent = progress.status === "awaiting_time"
        ? `Il reste ${formatSeconds(progress.remaining_seconds)} de temps actif à suivre. Reprenez les séquences depuis le sommaire pour poursuivre votre formation.`
        : progress.status === "passed"
        ? `Objectif atteint avec un score de ${score} %.`
        : `Parcours terminé avec un score de ${score} %. L’équipe pédagogique pourra vous accompagner.`;
    }
    if (scroll) courseResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function handleAction() {
    if (!actionButton || actionButton.disabled) return;
    const mode = actionButton.dataset.mode;
    if (mode === "navigate") {
      window.location.assign(config.isLastActivity ? (config.endUrl || config.portalUrl) : config.nextUrl);
      return;
    }
    actionButton.disabled = true;
    state.saving = true;
    const originalLabel = actionButton.textContent;
    actionButton.textContent = "Enregistrement…";
    try {
      if (mode === "answer") {
        const result = await postJson(config.answerUrl, { answer: collectAnswer() });
        applyProgress(result.progress);
        showAnswerFeedback(Boolean(result.correct), Boolean(result.retry_required));
        if (result.explanation) {
          const detail = document.createElement('p');
          detail.textContent = result.explanation;
          document.getElementById('nativeAnswerFeedback')?.append(detail);
        }
        if (result.retry_required) {
          actionButton.dataset.mode = "answer";
          actionButton.textContent = "Vérifier à nouveau";
          return;
        }
        showCourseResult(result.progress, true);
        actionButton.dataset.mode = "navigate";
        actionButton.textContent = config.isLastActivity ? `${config.endLabel || 'Retour au parcours'} →` : "Continuer →";
        questionForm?.querySelectorAll("input,select").forEach((field) => { field.disabled = true; });
      } else {
        const practice = document.querySelector('[data-aps-practice]');
        const production = document.querySelector('[data-aps-production]');
        if (production && !window.aps62Production) throw new Error('Le dossier est en cours de chargement. Réessayez.');
        const reflection = document.getElementById('apsReflection');
        if (reflection && reflection.value.trim().length < Number(reflection.dataset.minChars)) {
          throw new Error(`Développez votre production : ${reflection.dataset.minChars} caractères minimum.`);
        }
        if (practice && !window.aps62Practice) throw new Error('L’atelier est en cours de chargement. Réessayez.');
        const payload = production ? window.aps62Production.collectForCompletion() : practice ? {practice_answers: window.aps62Practice.collectForCompletion()}
          : reflection ? {reflection: reflection.value.trim()} : {};
        const result = await postJson(config.completeUrl, payload);
        if (practice) window.aps62Practice.clearDraft();
        if (production) window.aps62Production.markCompleted();
        applyProgress(result.progress);
        if (config.isLastActivity) {
          showCourseResult(result.progress, true);
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
      state.saving = false;
      updateAction();
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

  restoreSavedAnswer();
  setupRequiredVideos();
  setupOptionalVideos();
  updateAction();
  renderTimer();
  scheduleIdlePause();
  startTracking();
  window.setInterval(renderTimer, 1000);
  window.setInterval(sendHeartbeat, requiredVideos.length ? 4000 : Math.max(5, Number(config.heartbeatSeconds || 15)) * 1000);
  window.addEventListener("pagehide", finishTracking);
  window.addEventListener("pageshow", (event) => { if (event.persisted && state.stopped) startTracking(); });
})();
