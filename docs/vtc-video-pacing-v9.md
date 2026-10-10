# VTC video pacing v9 — 10 October 2026

The eight mandatory VTC capsules now open at **0.85×**, with pitch preservation,
an available 1× setting, short reflection breaks, and cards that match the spoken
examples. This is a media/player repair for these existing course editions:

- `20261007-vtc-v4-visuals`
- `20261007-vtc-v5-annales`
- `20261010-vtc-v6-pedagogie`

`vtc.load_bundled_course` applies the repair to a copied course after the existing
English pronunciation and listening corrections. It checks the capsule ID,
source path and provenance, transcript, captions, duration and all 24 chapter
boundaries before replacing media. Historical course JSON, earlier editions,
assignments and learner records are not rewritten. The 48 listening exercises
are outside this video revision.

## Assets and authoring contract

The audio source is v4 for A–D/F–H and the bilingual v7 video for E.
`scripts/vtc/render_paced_videos.py` rebuilds only the visual track and copies the
original AAC packets with `-c:a copy`; it makes no speech-service request.
The output is eight MP4 files and eight posters under `media/vtc/v9/`, using
1280 × 720 H.264 at 20 frames/s. Existing VTT paths are retained and the same
captions are burned into the rebuilt visuals. Historical assets remain intact.

The three reviewed JSON files have separate purposes:

| File under `elearning_native/vtc/` | Contract |
| --- | --- |
| `video_visuals_v9.json` | Source transcript hashes; 24 ordered scenes per module; three cards per scene, each with a unique verbatim `anchor_text`. |
| `video_pacing_v9.json` | Generated media paths, source/output hashes, unchanged checkpoints, copied-audio fingerprint, and the actual `visual_reveals` times. |
| `video_learning_pauses_v9.json` | Source media/transcript hashes, pause times, durations, learner prompts, and measured silent intervals. |

Cards in A–D/F–H appear at the start of the existing subtitle cue containing
their anchor. This is cue-level alignment: the cited word may occur later in
the same cue. E uses the retained v7 synthesis word timings, adjusted for its
original trimmed and joined language segments. All 72 English reveals in the
delivered media use `original-synthesis-word`. If that local build cache is
absent, the renderer explicitly falls back to `caption-cue`; retain the cache
to reproduce the delivered English timing precision. No speech is recognized
or regenerated to establish either timing method.

The reviewed cards include the spoken thirty-minute English example, the same
French grammar examples as the narration, the VAT formulas in their explanatory
scene, and the commission calculation `60 ÷ 0.80 = 75`.

## Pauses, speed and progress

`scripts/vtc/build_learning_pauses.py` finds silent intervals in the original
audio with FFmpeg (`-35 dB`, at least 0.15 s). It places each pause inside the
silent tail before a chapter cut, without interrupting the last spoken word.
There are 11 four-second reflection pauses per module after completed themes,
two additional concept pauses in B, three in D, and 12 five-second repetition
pauses in E. The final scene has no completion-blocking pause.

`static/js/native-video-pacing.js` freezes the existing frame, shows a countdown
and resumes playback; the learner can resume early or stay paused. Losing
visibility/focus cancels timed resumption. The same controls serve learner
playback and administrator previews. Pauses and 0.85× playback are implemented
by the player, not baked into the MP4 timeline.

Video/activity IDs, course versions, durations and chapter boundaries remain
unchanged, preserving saved positions and completed viewing. The server accepts
only the reviewed 0.85×/1× policy for these VTC editions, validates continuous
media advancement against elapsed time and the active rate, and does not credit
the frozen pause as watched media. Existing seeking and presence requirements
remain enforced.

## Reproduction

Run from the repository root in the existing Python environment, with Pillow,
`av`, `imageio-ffmpeg` and `edge-tts` installed. The latter is imported by the
shared renderer; this workflow does not call it. Keep the bundled Manrope fonts.
Set the bilingual cache path to the retained v7 build directory containing
`speech/*.json` and the joined scene-piece WAV files under `E/`.

```sh
export VTC_PACING_WORK=/tmp/vtc-pacing-v9
export VTC_BILINGUAL_WORK=/path/to/retained/vtc-bilingual-v7
python scripts/vtc/render_paced_videos.py --plan-only
python scripts/vtc/render_paced_videos.py --jobs 2
python scripts/vtc/build_learning_pauses.py
```

`--only F` renders one module; `VTC_ONLY=F` is also supported. The renderer
checks layout and narration anchors before encoding, then verifies copied AAC
packet hashes and duration. Scratch cache signatures include the source
manifest, reviewed module plan and renderer source. After editing a module's
cards, regenerate that module and commit its media and manifest together.
Do not run separate writers against the same output manifest concurrently.

```sh
python -m pytest -q tests/test_vtc_video_visuals_v9.py \
  tests/test_vtc_pacing_integration.py tests/test_native_elearning_pacing.py
node --test tests/test_native_elearning_video_ui.cjs
```

Encoding/library versions can change output bytes on a future rebuild; compare
the generated manifest hashes and checkpoints rather than assuming byte-identical
MP4 containers. Changes to spoken text or the source timeline require a separate
review, not an update to this preservation-only repair.

## Measured validation of the delivered media

| Module | Unchanged media duration (s) | Pauses |
| --- | ---: | ---: |
| A | 556.700 | 11 |
| B | 532.450 | 13 |
| C | 535.872 | 11 |
| D | 496.872 | 14 |
| E | 498.150 | 23 |
| F | 535.950 | 11 |
| G | 530.750 | 11 |
| H | 522.072 | 11 |
| **Total** | **4,208.816** | **105** |

- All eight actual container durations equal the source durations exactly;
  the renderer's acceptance limit is 0.05 s.
- Encoded AAC payload hashes and every packet's PTS, DTS, duration and size
  match the corresponding source. Narration and subtitle timing are preserved.
- All 192 scenes and 576 cards pass verbatim-anchor/order and font-width checks.
  Captures of all 192 scenes were reviewed in contact sheets, with enlarged
  checks of method cards and the corrected English thirty-minute example.
- The eight MP4 files total **67,773,402 bytes**. File, poster, caption and audio
  fingerprints are recorded in the generated media manifest.
- Automated coverage checks all 24 module/edition combinations, partial and
  completed progress, source mismatch rejection, copied-course isolation,
  authenticated range requests, rate changes, all 105 pause points and hidden
  page behavior. Technical media checks do not claim a new listening assessment
  of the unchanged narration.
