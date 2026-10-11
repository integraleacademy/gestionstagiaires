const { JSDOM } = require('jsdom');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/vtc-video-companion.js'), 'utf8');

const presentation = {
  scenes: [
    { start: 0, end: 10, title: 'Une règle claire', points: [
      { label: 'Principe', text: 'Première carte', at_seconds: 1.2 },
      { label: 'Exemple', text: 'Deuxième carte', at_seconds: 5 }
    ] },
    { start: 10, end: 20, title: 'Appliquer la règle', points: [
      { label: 'Méthode', text: 'Troisième carte', at_seconds: 12 }
    ] }
  ],
  captions: [
    { start: .5, end: 2, text: 'Bonjour.' },
    { start: 2, end: 4, text: 'Voici le principe.' },
    { start: 12, end: 14, text: 'Passons à la pratique.' }
  ]
};

function fixture({ config = presentation, vtc = true, start = 0 } = {}) {
  const dom = new JSDOM(`<!doctype html><body class="${vtc ? 'vtc-course' : 'a3p-course'}">
    <header><button id="outside">Menu</button></header><main><div class="native-video-shell" data-vtc-video-reader>
    <div data-video-reader-toolbar hidden><button data-video-reader-expand aria-expanded="false">Agrandir la lecture</button></div>
    <div class="vtc-video-picture"><video controls playsinline data-required-video="unchanged-id" aria-label="Ma leçon"></video></div>
    <script type="application/json" data-vtc-video-presentation>${JSON.stringify(config).replaceAll('<', '\\u003c')}</script>
    <section data-video-companion hidden aria-live="off">
      <input type="checkbox" data-video-caption-toggle checked><p data-video-caption></p>
      <span data-video-scene-number></span><h3 data-video-scene-title></h3><ul data-video-points></ul><p data-video-points-wait>Patientez</p>
    </section>
    <select data-playback-rate><option value="0.85">0,85</option></select>
    <div data-learning-pause hidden><button data-pause-stay>Rester en pause</button></div>
    </div><button id="continue">Continuer</button><p id="already-inert" inert>Autre contenu</p></main></body>`,
    { runScripts: 'outside-only', url: 'https://test.invalid/' });
  const { window } = dom, doc = window.document;
  const video = doc.querySelector('video'), shell = doc.querySelector('[data-vtc-video-reader]');
  let currentTime = start, paused = true;
  Object.defineProperty(video, 'currentTime', { get: () => currentTime,
    set: () => { throw new Error('Presentation must never seek the video'); } });
  Object.defineProperty(video, 'playbackRate', { get: () => .85,
    set: () => { throw new Error('Presentation must never change the playback speed'); } });
  Object.defineProperty(video, 'paused', { get: () => paused });
  video.play = () => { throw new Error('Presentation must never resume the video'); };
  video.pause = () => { throw new Error('Presentation must never pause the video'); };
  window.eval(source);
  return { window, doc, video, shell,
    move: (time, event = 'timeupdate') => { currentTime = time; video.dispatchEvent(new window.Event(event)); },
    emit: (event) => video.dispatchEvent(new window.Event(event)),
    at: (selector) => doc.querySelector(selector),
    points: () => [...doc.querySelectorAll('[data-video-points] li')].map((node) => node.textContent),
    close: () => window.close() };
}

test('cards follow the spoken anchors and reset on both forward and backward seeking', () => {
  const f = fixture();
  try {
    assert.equal(f.at('[data-video-companion]').hidden, false);
    assert.deepEqual(f.points(), []);
    f.move(1.19); assert.deepEqual(f.points(), []);
    f.move(1.2); assert.deepEqual(f.points(), ['PrincipePremière carte']);
    f.move(5); assert.equal(f.points().length, 2);
    f.move(10); assert.deepEqual(f.points(), []);
    assert.equal(f.at('[data-video-scene-title]').textContent, 'Appliquer la règle');
    f.move(13, 'seeked'); assert.deepEqual(f.points(), ['MéthodeTroisième carte']);
    f.move(2, 'seeking'); assert.deepEqual(f.points(), ['PrincipePremière carte']);
    assert.equal(f.at('[data-video-scene-number]').textContent, 'Séquence 1 sur 2');
    f.move(0, 'seeked'); assert.deepEqual(f.points(), []);
    assert.equal(f.at('[data-video-points-wait]').hidden, false);
    f.move(20, 'ended'); assert.deepEqual(f.points(), ['MéthodeTroisième carte']);
  } finally { f.close(); }
});

test('caption boundaries do not overlap and silent intervals clear the spoken text', () => {
  const f = fixture();
  try {
    const caption = f.at('[data-video-caption]');
    assert.equal(caption.textContent, '');
    f.move(.5); assert.equal(caption.textContent, 'Bonjour.');
    f.move(2); assert.equal(caption.textContent, 'Voici le principe.');
    f.move(4); assert.equal(caption.textContent, '');
    f.move(13, 'pause'); assert.equal(caption.textContent, 'Passons à la pratique.');
    const toggle = f.at('[data-video-caption-toggle]');
    toggle.checked = false; toggle.dispatchEvent(new f.window.Event('change'));
    assert.equal(caption.hidden, true);
    f.move(2); assert.equal(caption.textContent, 'Voici le principe.');
    toggle.checked = true; toggle.dispatchEvent(new f.window.Event('change'));
    assert.equal(caption.hidden, false);
    assert.equal(f.at('[data-video-companion]').getAttribute('aria-live'), 'off');
    assert.equal(f.doc.querySelector('[role="alert"], [role="status"], [aria-live="polite"]'), null);
  } finally { f.close(); }
});

test('opening and closing the reader preserves the media, .85 speed and active learning pause', () => {
  const f = fixture({ start: 13 });
  try {
    const button = f.at('[data-video-reader-expand]'), pause = f.at('[data-learning-pause]');
    pause.hidden = false;
    button.focus(); button.click();
    assert.equal(f.shell.classList.contains('is-expanded'), true);
    assert.equal(f.shell.getAttribute('role'), 'dialog');
    assert.equal(f.shell.getAttribute('aria-modal'), 'true');
    assert.equal(f.doc.querySelector('video'), f.video);
    assert.equal(f.video.currentTime, 13);
    assert.equal(f.video.playbackRate, .85);
    assert.equal(f.video.dataset.requiredVideo, 'unchanged-id');
    assert.equal(pause.hidden, false);
    assert.equal(f.at('#outside').closest('header').hasAttribute('inert'), true);
    assert.equal(f.at('#continue').hasAttribute('inert'), true);
    assert.equal(f.doc.documentElement.style.overflow, 'hidden');
    f.shell.dispatchEvent(new f.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    assert.equal(f.shell.classList.contains('is-expanded'), false);
    assert.equal(f.shell.hasAttribute('role'), false);
    assert.equal(f.at('#continue').hasAttribute('inert'), false);
    assert.equal(f.at('#already-inert').hasAttribute('inert'), true);
    assert.equal(f.doc.documentElement.style.overflow, '');
    assert.equal(f.doc.activeElement, button);
    assert.equal(pause.hidden, false);
  } finally { f.close(); }
});

test('keyboard focus stays inside the expanded reader and includes a visible pause button', () => {
  const f = fixture();
  try {
    const button = f.at('[data-video-reader-expand]');
    button.focus(); button.click();
    button.dispatchEvent(new f.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }));
    assert.equal(f.doc.activeElement, f.at('[data-playback-rate]'));
    f.doc.activeElement.dispatchEvent(new f.window.KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
    assert.equal(f.doc.activeElement, button);
    f.at('[data-learning-pause]').hidden = false;
    button.dispatchEvent(new f.window.KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }));
    assert.equal(f.doc.activeElement, f.at('[data-pause-stay]'));
  } finally { f.close(); }
});

test('text from the authorized presentation cannot inject markup or scripts', () => {
  const config = structuredClone(presentation);
  config.scenes[0].title = '<img src=x onerror=alert(1)>';
  config.scenes[0].points[0].text = '<script>malicious()</script>';
  config.captions[0].text = '<svg onload=alert(1)>';
  const f = fixture({ config });
  try {
    f.move(1.5);
    assert.equal(f.at('[data-video-scene-title]').textContent, config.scenes[0].title);
    assert.match(f.points()[0], /<script>/);
    assert.equal(f.at('[data-video-caption]').textContent, config.captions[0].text);
    assert.equal(f.at('[data-video-companion]').querySelector('img,svg,script'), null);
  } finally { f.close(); }
});

test('malformed or missing metadata keeps ordinary video playback available', () => {
  for (const config of [null, {}, { scenes: [], captions: [] }, { scenes: [{ start: -1, end: 2 }], captions: [] }]) {
    const f = fixture({ config });
    try {
      assert.equal(f.at('[data-video-companion]').hidden, true);
      assert.equal(f.at('[data-video-reader-toolbar]').hidden, true);
      assert.equal(f.video.controls, true);
    } finally { f.close(); }
  }
});

test('APS and A3P pages are not enhanced even if stray metadata is present', () => {
  const f = fixture({ vtc: false });
  try {
    assert.equal(f.at('[data-video-companion]').hidden, true);
    f.move(13); assert.deepEqual(f.points(), []);
    f.at('[data-video-reader-expand]').click();
    assert.equal(f.shell.classList.contains('is-expanded'), false);
  } finally { f.close(); }
});
