// Deterministic browser-DOM checks; the authoritative time/access rules have Python integration tests.
// NODE_PATH=/path/to/node_modules node tests/test_native_elearning_player_ui.cjs
const { JSDOM } = require("jsdom");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/js/native-elearning-player.js"), "utf8");

async function fixture({ lastActivity = false } = {}) {
  const initial = lastActivity ? 14398 : 0;
  const config = { accessToken: "signed", csrfToken: "csrf", activityId: "lesson", idleSeconds: 300,
    heartbeatSeconds: 15, startUrl: "/start", heartbeatUrl: "/heartbeat", finishUrl: "/finish",
    initialActiveSeconds: initial, initialRemainingSeconds: 14400 - initial, initialModuleComplete: false,
    isLastActivity: lastActivity, hasNextModule: true, endLabel: "Module suivant", endUrl: "/next" };
  const dom = new JSDOM(`<!doctype html><strong id="nativeActiveTimer"></strong>
    <div id="nativeTrackingState"><span></span></div><div id="nativeDuplicateNotice"></div>
    <button id="nativeActionButton" data-mode="navigate">Continuer</button>
    <div id="nativeCourseResult"><strong></strong><span></span></div>
    <strong id="nativeRemainingTime"></strong><span id="nativeDurationStatus"></span>
    <div id="nativeIdleNotice" hidden><button id="nativeResumeTimer">Reprendre</button></div>
    <video class="native-course-video"></video>
    <script id="nativeElearningConfig" type="application/json">${JSON.stringify(config)}</script>`,
    { runScripts: "outside-only", url: "https://test.invalid/" });
  const { window } = dom;
  let now = 0, nextTimer = 0, unlocked = false, resumedAt = null, lastSignal;
  const scheduled = new Map(), requests = [];
  window.Date.now = () => now;
  window.setTimeout = (fn, delay = 0) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay }); return id; };
  window.clearTimeout = (id) => scheduled.delete(id);
  window.setInterval = (fn, delay) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay, interval: delay }); return id; };
  Object.defineProperty(window.document, "visibilityState", { value: "visible", configurable: true });
  window.document.hasFocus = () => true;
  const video = window.document.querySelector("video");
  for (const [field, value] of Object.entries({ paused: false, ended: false, readyState: 4 })) {
    Object.defineProperty(video, field, { value, configurable: true });
  }
  const progress = () => {
    const active = lastActivity ? (unlocked ? 14400 : initial)
      : Math.min(now / 1000, 300) + (resumedAt === null ? 0 : Math.min((now - resumedAt) / 1000, 300));
    return { active_seconds: active, remaining_seconds: Math.max(0, 14400 - active), duration_met: unlocked,
      module_complete: unlocked, status: unlocked ? "passed" : lastActivity ? "awaiting_time" : "in_progress",
      score_percent: 100, progress_percent: lastActivity ? 100 : 0 };
  };
  window.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    requests.push({ url, body });
    if (url === "/heartbeat") lastSignal = body;
    return { ok: true, json: async () => ({ ok: true, tracking_session_id: "tracking",
      active: url === "/heartbeat" && body.interaction_age_seconds < 300, progress: progress() }) };
  };
  const settle = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
  window.eval(source);
  await settle();
  const advance = async (milliseconds) => {
    const target = now + milliseconds;
    while (true) {
      const candidate = [...scheduled.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!candidate) break;
      const [id, timer] = candidate;
      now = timer.at;
      if (timer.interval) timer.at += timer.interval; else scheduled.delete(id);
      timer.fn();
      await settle();
    }
    now = target;
    await settle();
  };
  return { window, requests, advance, settle, close: () => dom.window.close(),
    signal: () => lastSignal, unlock: () => { unlocked = true; }, resume: () => { resumedAt = now; } };
}

(async () => {
  const timer = await fixture();
  try {
    const document = timer.window.document;
    await timer.advance(299000);
    assert.equal(document.querySelector("#nativeActiveTimer").textContent, "00:04:59");
    assert.equal(document.querySelector("#nativeIdleNotice").hidden, true);
    // A video's own events do not renew the learner's interaction deadline.
    document.querySelector("video").dispatchEvent(new timer.window.Event("ended"));
    await timer.settle();
    assert.equal(timer.signal().interaction_age_seconds, 299);
    await timer.advance(1000);
    assert.equal(document.querySelector("#nativeActiveTimer").textContent, "00:05:00");
    assert.equal(document.querySelector("#nativeIdleNotice").hidden, false);
    assert.equal(timer.signal().recent_activity, false);
    assert.equal(timer.signal().media_playing, true);
    await timer.advance(300000);
    assert.equal(document.querySelector("#nativeActiveTimer").textContent, "00:05:00");
    timer.resume();
    document.querySelector("#nativeResumeTimer").click();
    await timer.settle();
    assert.equal(timer.signal().interaction_age_seconds, 0);
    assert.equal(document.querySelector("#nativeIdleNotice").hidden, true);
    await timer.advance(15000);
    assert.equal(document.querySelector("#nativeActiveTimer").textContent, "00:05:15");
  } finally { timer.close(); }

  const locked = await fixture({ lastActivity: true });
  try {
    const document = locked.window.document, button = document.querySelector("#nativeActionButton");
    assert.equal(button.disabled, true);
    assert.match(button.textContent, /00:00:02/);
    await locked.advance(10000);
    // A locally extrapolated clock reaching the target is never sufficient to unlock.
    assert.equal(document.querySelector("#nativeActiveTimer").textContent, "04:00:08");
    assert.equal(button.disabled, true);
    locked.unlock();
    await locked.advance(5000);
    assert.equal(button.disabled, false);
    assert.equal(button.textContent, "Module suivant →");
    assert.equal(document.querySelector("#nativeRemainingTime").textContent, "00:00:00");
    assert.equal(document.querySelector("#nativeCourseResult strong").textContent, "Module terminé");
  } finally { locked.close(); }
  console.log("PASS: exact 5-minute pause, video inactivity, no idle accrual, resume, server-confirmed module unlock.");
})().catch((error) => { console.error(error); process.exitCode = 1; });
