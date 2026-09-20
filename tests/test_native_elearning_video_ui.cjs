// Client controls complement the authoritative Flask/SQLite tests.
const { JSDOM } = require("jsdom");
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/js/native-elearning-player.js"), "utf8");

async function fixture({ watched = 0, completed = false } = {}) {
  let record = { watched_seconds: watched, completed, duration_seconds: 8 };
  const config = { accessToken: "signed", csrfToken: "csrf", activityId: "lesson", idleSeconds: 300,
    startUrl: "/start", heartbeatUrl: "/heartbeat", finishUrl: "/finish", completeUrl: "/complete",
    requiredVideos: { capsule: 8 }, initialVideoProgress: { lesson: { capsule: record } },
    isLastActivity: true, hasNextModule: false, endLabel: "Retour au parcours" };
  const dom = new JSDOM(`<!doctype html><div id="nativeTrackingState"><span></span></div>
    <button id="nativeActionButton" data-mode="complete">Terminer le module</button>
    <div id="nativeToast"></div><video class="native-course-video" data-required-video="capsule"></video>
    <div data-video-followup="capsule"><span data-video-status></span>
      <div role="progressbar"><i></i></div></div>
    <script id="nativeElearningConfig" type="application/json">${JSON.stringify(config)}</script>`,
    { runScripts: "outside-only", url: "https://test.invalid/" });
  const { window } = dom, video = window.document.querySelector("video");
  let now = 0, nextTimer = 0, focused = true, offline = false, resync = {};
  let blockedResponse = null, releaseResponse = null;
  const scheduled = new Map(), requests = [];
  window.Date.now = () => now;
  window.setTimeout = (fn, delay = 0) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay }); return id; };
  window.clearTimeout = (id) => scheduled.delete(id);
  window.setInterval = (fn, delay) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay, interval: delay }); return id; };
  Object.defineProperty(window.document, "visibilityState", { value: "visible", configurable: true });
  window.document.hasFocus = () => focused;
  for (const [field, value] of Object.entries({ currentTime: 0, paused: true, ended: false, seeking: false, readyState: 4, duration: 8 })) {
    Object.defineProperty(video, field, { value, writable: true, configurable: true });
  }
  const emit = (name) => video.dispatchEvent(new window.Event(name));
  video.pause = () => { if (!video.paused) { video.paused = true; emit("pause"); } };
  video.play = async () => { video.paused = false; video.ended = false; emit("play"); emit("playing"); };
  window.fetch = async (url, options) => {
    const body = JSON.parse(options.body);
    requests.push({ url, body });
    if (url === "/heartbeat" && blockedResponse) await blockedResponse;
    if (offline) throw new Error("offline");
    const response = { ok: true, tracking_session_id: "tracking", active: focused, video_resync: resync,
      progress: { video_progress: { lesson: { capsule: { ...record } } }, active_seconds: now / 1000,
        module_complete: url === "/complete", progress_percent: url === "/complete" ? 100 : 0 } };
    resync = {};
    return { ok: true, json: async () => response };
  };
  const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  const advance = async (milliseconds) => {
    const target = now + milliseconds;
    for (let calls = 0; calls < 10000; calls++) {
      const candidate = [...scheduled.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!candidate) break;
      const [id, timer] = candidate;
      now = timer.at;
      if (timer.interval) timer.at += timer.interval; else scheduled.delete(id);
      timer.fn();
      await settle();
      if (calls === 9999) throw new Error("Unbounded heartbeat retry");
    }
    now = target;
    await settle();
  };
  window.eval(source);
  await settle();
  return { window, video, emit, requests, settle, advance,
    button: window.document.querySelector("#nativeActionButton"), close: () => dom.window.close(),
    confirm: (seconds, done = false) => { record = { ...record, watched_seconds: seconds, completed: done }; },
    disconnect: () => { offline = true; }, resync: (position) => { resync = { capsule: position }; },
    blur: () => { focused = false; window.dispatchEvent(new window.Event("blur")); },
    hold: () => { blockedResponse = new Promise((resolve) => { releaseResponse = resolve; }); },
    release: () => { blockedResponse = null; releaseResponse(); },
  };
}

test("video completion needs server confirmation, including an ended event queued during a heartbeat", async () => {
  const f = await fixture();
  try {
    assert.equal(f.button.disabled, true);
    f.button.click();
    assert.equal(f.requests.some((request) => request.url === "/complete"), false);
    await f.video.play();
    await f.advance(0);
    f.hold();
    await f.advance(4000);
    f.video.currentTime = 8;
    f.video.paused = true;
    f.video.ended = true;
    f.emit("ended");
    assert.equal(f.button.disabled, true);
    f.release();
    await f.settle();
    await f.advance(0);
    assert.equal(f.requests.at(-1).body.videos[0].ended, true);
    assert.equal(f.button.disabled, true); // A browser event alone is insufficient.
    f.confirm(8, true);
    await f.advance(4000);
    assert.equal(f.button.disabled, false);
    assert.equal(f.button.textContent, "Terminer le module →");
    assert.match(f.window.document.querySelector("[data-video-status]").textContent, /entièrement visionnée/);
    f.button.click();
    await f.settle();
    assert.equal(f.requests.at(-1).url, "/complete");
    assert.equal(f.button.dataset.mode, "navigate");
  } finally { f.close(); }
});

test("reload resumes the saved position, forward seeking is blocked and replay stays available", async () => {
  const f = await fixture({ watched: 3 });
  try {
    assert.equal(f.video.currentTime, 3);
    f.video.currentTime = 7;
    f.emit("seeking");
    assert.equal(f.video.currentTime, 3);
    f.video.currentTime = 1;
    f.emit("seeking");
    assert.equal(f.video.currentTime, 1);
    f.video.playbackRate = 2;
    f.emit("ratechange");
    assert.equal(f.video.playbackRate, 1);
    assert.equal(f.button.disabled, true);
  } finally { f.close(); }
});

test("leaving the page pauses the required video", async () => {
  const f = await fixture();
  try {
    await f.video.play();
    await f.advance(0);
    assert.equal(f.video.paused, false);
    f.blur();
    await f.settle();
    await f.advance(0);
    assert.equal(f.video.paused, true);
    assert.equal(f.requests.at(-1).body.focused, false);
    assert.equal(f.button.disabled, true);
  } finally { f.close(); }
});

test("server resync and a lost connection return to confirmed viewing without unlocking", async () => {
  const f = await fixture({ watched: 3 });
  try {
    await f.video.play();
    await f.advance(0);
    f.video.currentTime = 5;
    f.resync(3);
    await f.advance(4000);
    assert.equal(f.video.paused, true);
    assert.equal(f.video.currentTime, 3);
    await f.video.play();
    await f.advance(0);
    f.video.currentTime = 6;
    f.disconnect();
    await f.advance(4000);
    assert.equal(f.video.paused, true);
    assert.equal(f.video.currentTime, 3);
    assert.equal(f.button.disabled, true);
    assert.equal(f.window.document.querySelector("#nativeTrackingState").dataset.state, "offline");
  } finally { f.close(); }
});
