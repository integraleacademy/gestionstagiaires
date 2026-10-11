# VTC visual edition — 7 October 2026

## Lesson video edition — 10 October 2026

`20261010-vtc-v10-lecons-video` adds an explanatory video to each of the 96
lessons and retains the eight module syntheses. New assignments require all
104 videos. The preceding v6 edition receives optional lesson videos without
changing activity IDs, required viewing, saved progress or assigned duration.
New administrative VTC people receive a server-written edition marker at
creation. Their session view resolves to v10 even inside a historical session,
while unmarked existing people keep the assigned edition. Historical empty
versions resolve to v6. Session selection, order and required minutes are kept;
transferring an existing person never adds or changes the marker.
The 5,422-minute provisional programme includes the videos within its existing
course slots; measured media duration is reported separately in the manifest.

Reviewed scripts are in `elearning_native/vtc/lesson_video_scripts_v10`.
Each script is bound to the exact lesson source. French uses Henri and English
uses British Ryan, with separate language segments. Word boundaries drive
captions and progressive visual cards. The player starts at 0.85× with pitch
preserved; authored 4–5 second pauses occur in verified silence and can be
extended by the learner. Speech is never compressed to fit a template.

```sh
python scripts/vtc/render_lesson_videos_v10.py --plan-only
python scripts/vtc/render_lesson_videos_v10.py
python scripts/vtc/validate_lesson_videos_v10.py --captures
python scripts/vtc/build_lesson_video_edition.py
python -m pytest tests/test_vtc_lesson_renderer_v10.py tests/test_vtc_lesson_videos_v10.py -q
node --test tests/test_native_elearning_video_ui.cjs
```

The renderer resumes from content-hashed intermediates in `/tmp/vtc-lessons-v10`.
Use `--only A` or `--only E.01` for selected lessons. The edition builder checks
all 96 media records, source hashes and MP4/JPEG/VTT hashes before promoting the
catalogue. It copies the corresponding exam and free-practice banks. Existing
course files and learner records are never rewritten.

`20261007-vtc-v4-visuals` adds 96 topic-specific three-step methods,
32 comparison/calculation tables and 20 inline illustrations from the manual.
The eight videos contain 24 animated scenes each, Henri narration, burned-in
punctuated captions, WebVTT and a complete transcript. Measured video lengths
are 496.87–556.70 seconds (70.1 minutes altogether), with no duration padding.

## Rebuild

Use the same Python, Pillow, Edge TTS, fonts and ffmpeg dependencies as
`scripts/render_aps62_v5.py`.

```sh
python scripts/vtc/render_visual_videos.py
python scripts/vtc/build_visual_edition.py
```

Narration uses the existing public v3 course text. Only narration is sent to
the existing speech provider; student records are not used. Content-hashed
intermediates remain under `/tmp/vtc-v4`, or `VTC_RENDER_WORK` when specified.
`VTC_ONLY=A` can rebuild one module. The edition builder refuses to publish
unless all eight video records are present and every video exceeds 300 seconds.
`--review-only` prepares lesson JSON without switching the curriculum manifest.

## Verification

```sh
python -m unittest tests.test_native_elearning_vtc tests.test_native_elearning_vtc105 tests.test_vtc_visual_edition -q
node --test tests/test_native_elearning_vtc_ui.cjs tests/test_native_elearning_vtc105_ui.cjs
```

The Node suites require `jsdom`. Acceptance checks probe the actual media,
compare every caption character with the narration, render all 96 lessons and
eight video previews, verify assets, and retain access to older editions.

Existing assignments keep their version. The new curriculum retains the same
activity IDs, order and 6,300 planned minutes. Longer videos replace part of
the existing 20-minute module synthesis slot; they do not add artificial time.
The 105-hour programme remains provisional pending learner pilot calibration.

## Quality repair v11 (104 videos)

`render_quality_videos_v11.py` builds the corrected narration, captions and
visuals under the new immutable `media/vtc/v11` namespace. It does not replace
the published v4/v7/v9/v10 files or their manifests. Current lesson authoring
is read from `lesson_video_scripts_v10`; the corrected eight summary scripts
live separately in `video_synthesis_scripts_v11.json`.

The complete `video_quality_v11.json` contains 96 `lessons` and eight `modules`.
Every entry records its previous media URL, hash, duration and chapter IDs,
plus the corrected word timings and inline responsive presentation. Four- or
five-second pauses remain in verified silent tails. The player rate stays
0.85; French Henri and British English Ryan keep their native voice tempo.

Captions are regrouped losslessly using original spoken-word timings. At the
default 0.85 playback rate, every cue lasts at least one second, stays at or
below 20 characters per second and occupies at most two 44-character lines.
These are internal comfort targets. The renderer fails if the words cannot
meet them; it never conceals a failure by reporting invented timing.

```sh
python scripts/vtc/render_quality_videos_v11.py --plan-only
python scripts/vtc/render_quality_videos_v11.py
python scripts/vtc/validate_quality_videos_v11.py --captures
python -m pytest tests/test_vtc_quality_renderer_v11.py -q
```

Speech is cached by exact voice, rate and text in `/tmp/vtc-lessons-v10/speech`.
Fresh video intermediates and the provisional manifest live in
`/tmp/vtc-quality-v11`; publication of the application manifest is atomic and
requires all 104 current signatures. `--only E.07` selects a single lesson;
`--only E` selects its twelve lessons and module summary. A partial build can
be inspected with `validate_quality_videos_v11.py --manifest
/tmp/vtc-quality-v11/manifest.partial.json --only E.07 --captures`.

Validation decodes every H.264 frame and every AAC sample, verifies frame
continuity, duration, media hashes, quiet pauses, source-bound captions,
unclipped card geometry and responsive presentation timings. One full-size
capture per scene and module contact sheets support manual visual review.
