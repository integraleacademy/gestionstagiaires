// The public excerpt has baked captions; native text tracks must never duplicate them.
const { JSDOM } = require('jsdom');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/mac-aps-demo.js'), 'utf8');

function fixture({ metadataLoaded = false } = {}) {
  const dom = new JSDOM('<video class="mac-demo-video"></video><video id="other"></video>',
    { runScripts: 'outside-only', url: 'https://test.invalid/' });
  const { window } = dom;
  const video = window.document.querySelector('.mac-demo-video');
  const tracks = new window.EventTarget();
  tracks.items = [];
  tracks[Symbol.iterator] = function* () { yield* this.items; };
  Object.defineProperty(video, 'textTracks', { value: tracks });
  Object.defineProperty(video, 'readyState', { value: metadataLoaded ? 4 : 0 });
  video.currentTime = 17.25;
  video.playbackRate = .9;
  video.play = video.pause = () => { throw new Error('Caption handling must not control playback'); };
  window.fetch = () => { throw new Error('The demo must not start tracking'); };
  const other = window.document.getElementById('other');
  const otherTrack = { kind: 'captions', mode: 'showing' };
  Object.defineProperty(other, 'textTracks', { value: [otherTrack] });
  const add = (kind, initialMode, notify = true) => {
    let mode = initialMode;
    const track = { kind, changes: 0 };
    Object.defineProperty(track, 'mode', {
      get: () => mode,
      set: value => {
        mode = value;
        track.changes += 1;
        tracks.dispatchEvent(new window.Event('change'));
      },
    });
    tracks.items.push(track);
    if (notify) tracks.dispatchEvent(new window.Event('addtrack'));
    return track;
  };
  if (metadataLoaded) video.dispatchEvent(new window.Event('loadedmetadata'));
  return { dom, window, video, tracks, otherTrack, add, run: () => window.eval(source) };
}

test('cached metadata cannot leave a second caption layer visible', () => {
  const f = fixture({ metadataLoaded: true });
  try {
    const captions = f.add('captions', 'showing', false);
    const descriptions = f.add('descriptions', 'showing', false);
    f.run();
    assert.equal(captions.mode, 'hidden');
    assert.equal(captions.changes, 1);
    assert.equal(descriptions.mode, 'showing');
    assert.equal(f.otherTrack.mode, 'showing');
    assert.equal(f.video.currentTime, 17.25);
    assert.equal(f.video.playbackRate, .9);
  } finally { f.dom.window.close(); }
});

test('late text tracks and native CC toggles cannot restore duplicate captions', () => {
  const f = fixture();
  try {
    f.run();
    const captions = f.add('captions', 'showing');
    const subtitles = f.add('subtitles', 'showing');
    assert.equal(captions.mode, 'hidden');
    assert.equal(subtitles.mode, 'hidden');
    f.video.dispatchEvent(new f.window.Event('loadedmetadata'));
    assert.equal(captions.changes, 1);
    assert.equal(subtitles.changes, 1);
    captions.mode = 'showing';
    subtitles.mode = 'showing';
    assert.equal(captions.mode, 'hidden');
    assert.equal(subtitles.mode, 'hidden');
    // A second metadata event is harmless and does not trigger a change loop.
    f.video.dispatchEvent(new f.window.Event('loadedmetadata'));
    assert.equal(captions.changes, 3);
    assert.equal(subtitles.changes, 3);
    assert.equal(f.video.currentTime, 17.25);
    assert.equal(f.video.playbackRate, .9);
  } finally { f.dom.window.close(); }
});
