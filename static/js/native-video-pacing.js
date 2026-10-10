(() => {
  "use strict";
  // The same presentation controls serve learner playback and admin previews.
  // They never manufacture learner interaction or confirmed viewing progress.
  window.NativeVideoPacing = {
    attach(video, options = {}) {
      const shell = video.closest(".native-video-shell");
      const node = shell?.querySelector("[data-video-pacing-config]");
      if (!node) return null;
      let config;
      try { config = JSON.parse(node.textContent); } catch (_) { return null; }
      if (config.default_playback_rate !== .85 || JSON.stringify(config.allowed_playback_rates) !== "[0.85,1]") return null;
      const rates = [.85, 1];
      const pauses = (config.learning_pauses || []).filter(p => Number.isFinite(p.at_seconds)
        && p.at_seconds > 0 && [4, 5].includes(p.duration_seconds)).sort((a, b) => a.at_seconds - b.at_seconds);
      const seen = new Set(pauses.filter(p => p.at_seconds <= Number(options.savedPosition || 0)));
      const panel = shell.querySelector("[data-learning-pause]");
      const message = panel?.querySelector("[data-pause-message]");
      const countdown = panel?.querySelector("[data-pause-countdown]");
      const selector = shell.querySelector("[data-playback-rate]");
      let active = null, timer = 0, resumeUntil = 0, previous = video.currentTime, lastTime = Date.now();
      const visible = () => document.visibilityState === "visible" && document.hasFocus();
      const mayResume = () => visible() && (!options.canResume || options.canResume());
      const anchor = () => { previous = video.currentTime; lastTime = Date.now(); };
      const clearPause = () => {
        window.clearTimeout(timer); timer = 0; active = null;
        if (panel) panel.hidden = true;
      };
      const cancelPause = () => { clearPause(); resumeUntil = 0; };
      const resume = () => {
        const allowed = mayResume();
        cancelPause();
        if (allowed && !video.ended) {
          resumeUntil = Date.now() + 6000;
          video.play().catch(cancelPause);
        }
      };
      const tick = () => {
        if (!active) return;
        if (!mayResume()) { cancelPause(); return; }
        const remaining = Math.max(0, Math.ceil((active.until - Date.now()) / 1000));
        if (countdown) countdown.textContent = `Reprise dans ${remaining} s`;
        if (!remaining) { resume(); return; }
        timer = window.setTimeout(tick, 100);
      };
      video.playbackRate = .85;
      video.defaultPlaybackRate = .85;
      video.preservesPitch = true;
      if (selector) {
        selector.value = "0.85";
        selector.addEventListener("change", () => {
          const rate = Number(selector.value);
          if (rates.includes(rate)) video.playbackRate = rate;
        });
      }
      video.addEventListener("ratechange", () => {
        if (!rates.includes(video.playbackRate)) video.playbackRate = .85;
        if (selector) selector.value = String(video.playbackRate);
        anchor();
      });
      const checkPause = () => {
        const now = Date.now(), position = video.currentTime;
        const continuous = position > previous && position - previous <= (now - lastTime) / 1000 * video.playbackRate + .5;
        const pause = pauses.find(p => !seen.has(p) && previous < p.at_seconds && position + .00001 >= p.at_seconds);
        anchor();
        if (!pause || !continuous || active || video.paused || video.seeking || !mayResume()) return;
        seen.add(pause);
        // Stop on the intended frame even if timeupdate arrived a little late.
        options.beforePause?.(pause.at_seconds);
        video.currentTime = pause.at_seconds;
        active = { until: now + pause.duration_seconds * 1000 };
        if (panel) panel.hidden = false;
        if (message) message.textContent = pause.message || "Prenez un instant pour retenir cette notion.";
        video.pause();
        anchor(); tick();
      };
      video.addEventListener("timeupdate", checkPause);
      // A few pause windows are close to a slide cut. Check on decoded frames
      // where available; timeupdate alone may arrive only four times a second.
      let framePending = false;
      const watchFrame = () => {
        if (framePending || video.paused || video.ended) return;
        const requestFrame = typeof video.requestVideoFrameCallback === "function"
          ? callback => video.requestVideoFrameCallback(callback)
          : typeof window.requestAnimationFrame === "function" ? callback => window.requestAnimationFrame(callback) : null;
        if (!requestFrame) return;
        framePending = true;
        requestFrame(() => { framePending = false; checkPause(); watchFrame(); });
      };
      video.addEventListener("play", () => { clearPause(); anchor(); watchFrame(); });
      video.addEventListener("seeked", anchor);
      // Seeking during a pause is an explicit learner action: no timed restart.
      video.addEventListener("seeking", () => {
        if (active && Math.abs(video.currentTime - previous) > .1) cancelPause();
        anchor();
      });
      video.addEventListener("ended", cancelPause);
      panel?.querySelector("[data-pause-resume]")?.addEventListener("click", resume);
      panel?.querySelector("[data-pause-stay]")?.addEventListener("click", cancelPause);
      window.addEventListener("blur", () => { cancelPause(); if (!video.paused) video.pause(); });
      document.addEventListener("visibilitychange", () => {
        if (!visible()) { cancelPause(); if (!video.paused) video.pause(); }
      });
      window.addEventListener("pagehide", () => { cancelPause(); if (!video.paused) video.pause(); });
      return { rates, cancelPause, isPausing: () => Boolean(active),
        isResuming: () => Date.now() < resumeUntil && !video.paused && video.readyState >= 2,
        markPast(position) { pauses.filter(p => p.at_seconds <= position).forEach(p => seen.add(p)); } };
    },
  };
})();
