# VTC English narration repair — 10 October 2026

The English lesson video previously used the French Henri voice for every word,
including English examples. Its 24 scenes now alternate French explanations
(fr-FR-HenriNeural) and explicitly marked English examples/grammar terms
(en-GB-RyanNeural, speech rate −6%). The existing 48 listening dialogues already
use British voices and are unchanged.

The new MP4 and VTT are `media/vtc/v7/lesson-e.*`. The v7 media revision is not a
new course edition. `vtc.load_bundled_course` applies the correction to copied
module E content for v4, v5 and v6 only, after checking the original media, ID,
duration and all 24 chapters. The original course JSON, other modules and earlier
editions remain unchanged. The poster remains the original v4 asset.

Learner progress retains the same course version, activity/video IDs, 498.15-second
duration and chapter boundaries. No assignments, tracking records or completed
viewing proofs are migrated. Tests cover partial progress at 120 seconds,
subsequent playback and already completed viewing for all three editions.

Captions are rebuilt from speech word timings and burned into the video; a VTT
track and visible transcript use the same text. Two spoken-text adjustments are
documented in the renderer: `he/she is` becomes `he is, she is`, and the French
linking prose in the times/dates scene is shortened while retaining all examples
and teaching points. English audio is never sped up. French timing adjustments
are at most 6.6%, with pitch preserved.

## Reproduction

Run `scripts/vtc/render_bilingual_english.py` with the existing renderer's Python
dependencies plus `edge-tts`, `imageio-ffmpeg` and `av`. Set
`VTC_BILINGUAL_WORK` to a scratch folder. The generator sends authored course text
only to the same speech provider used previously; no learner data are read.
Cached segments are keyed by voice, rate and text, with per-key concurrency locks.
The generator writes `video_english_bilingual_v7.json` with source provenance,
language partitions, word-timed captions and scene timing measurements. Historical
media and manifests are not overwritten.

## Validation

- Preview and authenticated range requests serve the new MP4; unauthenticated
  asset access is rejected.
- The frozen course files, asset permissions, copy isolation, lesson checkpoints
  and existing viewing evidence are covered by automated tests.
- Media streams and caption text/timing are checked against the generated
  manifest; a six-frame visual review checks subtitle layout.
- Voice selection and technical checks do not substitute for the learner's
  subjective listening assessment. A short excerpt is provided for listening.
