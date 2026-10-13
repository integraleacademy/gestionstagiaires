(() => {
  "use strict";

  // This is presentation only. The existing video element, pacing controller
  // and server-confirmed viewing progression remain authoritative.
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const validInterval = (item) => item && finite(item.start) && finite(item.end)
    && item.start >= 0 && item.end > item.start;
  let expandedReader = null;

  function attach(shell) {
    const video = shell.querySelector("video");
    const configNode = shell.querySelector("[data-vtc-video-presentation]");
    const panel = shell.querySelector("[data-video-companion]");
    const toolbar = shell.querySelector("[data-video-reader-toolbar]");
    if (!video || !configNode || !panel || !toolbar) return;
    let config;
    try { config = JSON.parse(configNode.textContent); } catch (_) { return; }
    if (!config || !Array.isArray(config.scenes) || !Array.isArray(config.captions)) return;
    const scenes = config.scenes.filter(validInterval).sort((a, b) => a.start - b.start);
    if (!scenes.length) return;

    const sceneTitle = panel.querySelector("[data-video-scene-title]");
    const sceneNumber = panel.querySelector("[data-video-scene-number]");
    const points = panel.querySelector("[data-video-points]");
    const waiting = panel.querySelector("[data-video-points-wait]");
    const expand = toolbar.querySelector("[data-video-reader-expand]");
    let lastScene = null, lastPoints = "", framePending = false;
    let restoreOutside = [], restoreOverflow = "", priorFocus = null;
    const originalTabIndex = video.getAttribute("tabindex");

    function render() {
      const time = Number(video.currentTime) || 0;
      // Keep the final scene on the final frame and never expose a future scene
      // in a short timing gap. Backward seeking recomputes every revealed card.
      const scene = scenes.find((item) => time >= item.start && time < item.end)
        || [...scenes].reverse().find((item) => time >= item.start) || scenes[0];
      const visiblePoints = (Array.isArray(scene.points) ? scene.points : [])
        .filter((point) => point && finite(point.at_seconds) && point.at_seconds <= time);
      const key = JSON.stringify(visiblePoints);
      if (scene !== lastScene) {
        sceneTitle.textContent = scene.title || "Repères de la vidéo";
        sceneNumber.textContent = `Séquence ${scenes.indexOf(scene) + 1} sur ${scenes.length}`;
      }
      if (scene !== lastScene || key !== lastPoints) {
        points.replaceChildren(...visiblePoints.map((point) => {
          const item = document.createElement("li");
          const label = document.createElement("strong");
          const body = document.createElement("span");
          label.textContent = point.label || "À retenir";
          body.textContent = point.text || "";
          item.append(label, body);
          return item;
        }));
        waiting.hidden = visiblePoints.length > 0;
        // An expanded side panel may have been scrolled to the previous slide.
        if (scene !== lastScene) panel.scrollTop = 0;
        lastPoints = key;
      }
      lastScene = scene;
    }

    function watchFrame() {
      if (framePending || video.paused || video.ended) return;
      const requestFrame = typeof video.requestVideoFrameCallback === "function"
        ? (callback) => video.requestVideoFrameCallback(callback)
        : typeof window.requestAnimationFrame === "function"
          ? (callback) => window.requestAnimationFrame(callback) : null;
      if (!requestFrame) return;
      framePending = true;
      requestFrame(() => { framePending = false; render(); watchFrame(); });
    }

    function closeReader() {
      if (expandedReader !== closeReader) return;
      shell.classList.remove("is-expanded");
      shell.removeAttribute("role");
      shell.removeAttribute("aria-modal");
      shell.removeAttribute("aria-label");
      expand.setAttribute("aria-expanded", "false");
      expand.textContent = "Agrandir la lecture";
      if (originalTabIndex === null) video.removeAttribute("tabindex");
      else video.setAttribute("tabindex", originalTabIndex);
      restoreOutside.forEach(([element, inert]) => {
        if (inert === null) element.removeAttribute("inert");
        else element.setAttribute("inert", inert);
      });
      restoreOutside = [];
      document.documentElement.style.overflow = restoreOverflow;
      expandedReader = null;
      if (priorFocus?.isConnected) priorFocus.focus({ preventScroll: true });
    }

    function openReader() {
      expandedReader?.();
      priorFocus = document.activeElement;
      restoreOverflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = "hidden";
      shell.classList.add("is-expanded");
      shell.setAttribute("role", "dialog");
      shell.setAttribute("aria-modal", "true");
      shell.setAttribute("aria-label", `Lecture agrandie · ${video.getAttribute("aria-label") || "Vidéo VTC"}`);
      expand.setAttribute("aria-expanded", "true");
      expand.textContent = "Réduire la lecture";
      video.setAttribute("tabindex", "0");
      // Make only branches outside this same player inert; no video is moved
      // or cloned, so playback and pause/progress listeners survive unchanged.
      for (let branch = shell; branch.parentElement; branch = branch.parentElement) {
        for (const sibling of branch.parentElement.children) {
          if (sibling === branch) continue;
          restoreOutside.push([sibling, sibling.getAttribute("inert")]);
          sibling.setAttribute("inert", "");
        }
        if (branch.parentElement === document.body) break;
      }
      expandedReader = closeReader;
      expand.focus({ preventScroll: true });
    }

    expand.addEventListener("click", () => {
      if (expandedReader === closeReader) closeReader(); else openReader();
    });
    shell.addEventListener("keydown", (event) => {
      if (expandedReader !== closeReader) return;
      if (event.key === "Escape") { event.preventDefault(); closeReader(); return; }
      if (event.key !== "Tab") return;
      const focusable = [...shell.querySelectorAll("button, select, input, video, a[href], [tabindex]")]
        .filter((element) => !element.disabled && element.tabIndex >= 0
          && !element.closest("[hidden], [inert]") && window.getComputedStyle(element).display !== "none");
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first?.focus();
      }
    });
    for (const event of ["loadedmetadata", "timeupdate", "seeking", "seeked", "pause", "ended", "emptied"]) {
      video.addEventListener(event, render);
    }
    video.addEventListener("play", () => { render(); watchFrame(); });
    window.addEventListener("pagehide", closeReader);
    panel.hidden = false;
    toolbar.hidden = false;
    render();
    watchFrame();
  }

  document.querySelectorAll(".vtc-course [data-vtc-video-reader]").forEach(attach);
})();
