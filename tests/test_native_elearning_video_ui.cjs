// Client controls complement the authoritative Flask/SQLite tests.
const { JSDOM } = require("jsdom");
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../static/js/native-elearning-player.js"), "utf8");

async function fixture({ watched = 0, completed = false, duration = 8, autoAdvance = false } = {}) {
  let record = { watched_seconds: watched, completed, duration_seconds: duration };
  const config = { accessToken: "signed", csrfToken: "csrf", activityId: "lesson", idleSeconds: 300,
    startUrl: "/start", heartbeatUrl: "/heartbeat", finishUrl: "/finish", completeUrl: "/complete",
    requiredVideos: { capsule: duration }, initialVideoProgress: { lesson: { capsule: record } },
    isLastActivity: true, hasNextModule: false, endLabel: "Retour au parcours" };
  const dom = new JSDOM(`<!doctype html><div id="nativeTrackingState"><span></span></div>
    <button id="nativeActionButton" data-mode="complete">Terminer le module</button>
    <div id="nativeToast"></div><video class="native-course-video" data-required-video="capsule"></video>
    <strong id="nativeActiveTimer"></strong><div id="nativeIdleNotice" hidden><button id="nativeResumeTimer">Reprendre</button></div>
    <details data-video-chapters="capsule"><p data-chapter-hint></p><button data-chapter-start="4" disabled>Chapitre 2</button></details>
    <div data-video-followup="capsule"><span data-video-status></span>
      <div role="progressbar"><i></i></div></div>
    <script id="nativeElearningConfig" type="application/json">${JSON.stringify(config)}</script>`,
    { runScripts: "outside-only", url: "https://test.invalid/" });
  const { window } = dom, video = window.document.querySelector("video");
  let now = 0, nextTimer = 0, focused = true, offline = false, resync = {}, receiptPosition = 0;
  let blockedResponse = null, releaseResponse = null;
  const scheduled = new Map(), requests = [];
  window.Date.now = () => now;
  window.setTimeout = (fn, delay = 0) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay }); return id; };
  window.clearTimeout = (id) => scheduled.delete(id);
  window.setInterval = (fn, delay) => { const id = ++nextTimer; scheduled.set(id, { fn, at: now + delay, interval: delay }); return id; };
  Object.defineProperty(window.document, "visibilityState", { value: "visible", configurable: true });
  window.document.hasFocus = () => focused;
  for (const [field, value] of Object.entries({ currentTime: 0, paused: true, ended: false, seeking: false, readyState: 4, duration })) {
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
    const advancing = body.videos?.[0]?.playing && video.currentTime > receiptPosition;
    if (url === '/heartbeat') receiptPosition = video.currentTime;
    const response = { ok: true, tracking_session_id: "tracking", active: focused, media_active: Boolean(advancing), video_resync: resync,
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
      const elapsed = (timer.at - now) / 1000;
      now = timer.at;
      if (autoAdvance && elapsed > 0 && !video.paused && !video.seeking && video.readyState >= 3) {
        video.currentTime = Math.min(duration, video.currentTime + elapsed * video.playbackRate);
        emit('timeupdate');
      }
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

test("a long advancing video continues beyond five minutes without manufacturing interactions", async () => {
  const f = await fixture({ duration: 660, autoAdvance: true });
  try {
    await f.video.play(); await f.advance(0);
    await f.advance(304000);
    f.emit('stalled'); // A slow fetch may coexist with healthy buffered playback.
    await f.advance(316000);
    assert.equal(f.video.paused, false);
    assert.equal(f.window.document.getElementById('nativeIdleNotice').hidden, true);
    const receipt = f.requests.filter(r => r.url === '/heartbeat').at(-1).body;
    assert.equal(receipt.interaction_age_seconds, 620);
    assert.equal(receipt.recent_activity, false);
    assert.equal(receipt.videos[0].position, 620);
    assert.equal(f.window.document.getElementById('nativeActiveTimer').textContent, '00:10:20');
    f.video.pause(); await f.advance(0);
    assert.equal(f.window.document.getElementById('nativeIdleNotice').hidden, false);
    assert.equal(f.window.document.getElementById('nativeTrackingState').dataset.state, 'paused');
  } finally { f.close(); }
});

test("buffering or missing server receipts cannot extend the long-video presence exception", async () => {
  for (const reason of ['buffering', 'lost receipts']) {
    const f = await fixture({ duration: 660, autoAdvance: true });
    try {
      await f.video.play(); await f.advance(0); await f.advance(304000);
      assert.equal(f.video.paused, false);
      if (reason === 'buffering') { f.video.readyState = 2; f.emit('waiting'); }
      else { f.hold(); }
      await f.advance(12000);
      assert.equal(f.video.paused, true, reason);
      assert.equal(f.window.document.getElementById('nativeIdleNotice').hidden, false, reason);
      if (reason === 'lost receipts') { f.release(); await f.advance(0); }
    } finally { f.close(); }
  }
});

test("chapters unlock only after server-confirmed completion, including after reload", async () => {
  const f = await fixture();
  try {
    const chapter = f.window.document.querySelector('[data-chapter-start]');
    assert.equal(chapter.disabled, true);
    chapter.click(); assert.equal(f.video.currentTime, 0);
    f.confirm(8, true); await f.advance(4000);
    assert.equal(chapter.disabled, false);
    chapter.click(); assert.equal(f.video.currentTime, 4);
    assert.equal(f.video.paused, true);
  } finally { f.close(); }
  const reloaded = await fixture({watched:8, completed:true});
  try {
    const chapter = reloaded.window.document.querySelector('[data-chapter-start]');
    assert.equal(chapter.disabled, false);
    chapter.click(); assert.equal(reloaded.video.currentTime, 4);
    await reloaded.video.play(); await reloaded.advance(0); reloaded.blur();
    assert.equal(reloaded.video.paused, true);
  } finally { reloaded.close(); }
});
