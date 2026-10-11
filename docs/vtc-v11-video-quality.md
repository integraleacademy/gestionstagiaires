# VTC video quality revision 11

This media revision repairs the existing 96 explainers and 8 summaries. It does
not create a new teaching edition or change the activities, enrolment policy,
training minutes, assessments or mandatory-viewing rules.

## Delivery

- `video_quality_v11.json` is published atomically only when all 104 entries have
  been rendered. The runtime rejects incomplete or mismatched collections.
- Media lives at immutable `assets/media/vtc/v11/` URLs. Historical manifests and
  media stay intact. Each entry records its exact predecessor URL, duration and
  chapters.
- Lesson narration corrections remain in the existing authoring directory;
  their raw lesson hashes stay unchanged. Corrected summary scripts have their
  own `video_synthesis_scripts_v11.json` source.
- French uses Henri and English uses British Ryan. Scores and identifiers are
  explicit aloud, and bilingual sentence joins are rewritten for speech.
- Default playback remains 0.85 with pitch preservation. Pauses fall in verified
  silence; card reveals use synthesis word timings. Caption durations are at
  least one second and density at most 20 characters per second at 0.85.

## Readable companion

Only VTC videos with reviewed presentation metadata get the responsive companion.
It reads the same video's current time for both captions and revealed cards,
including backward seeking. It never awards progress or creates a second player.
The expanded view keeps the existing video, pace controls and learning pauses
together; outside content becomes inert until the view closes.

## Existing learner progress

`vtc_video_quality.compatible_record` recognizes only the exact bundled
predecessor timeline and known VTC video IDs. A fully viewed predecessor remains
complete, with its completion timestamp. An unfinished prefix maps proportionally
within the same chapter and cannot become complete through rounding. Training
time is never added by migration. Normal server-validated playback receipts remain
authoritative and persist the projected record when viewing resumes.

Signed tracking tokens include the current VTC media revision. A pre-deployment
tab receives HTTP 409 before its old timeline can be recorded against new media;
the existing player pauses and asks for a reload. Confirmed progress is preserved
and the reloaded player receives the projected resume position. Media access
tokens and other training courses retain their existing authorization policy.

## Validation

Run the v11 renderer and independent validator from the repository root:

```sh
python scripts/vtc/render_quality_videos_v11.py --plan-only
python scripts/vtc/render_quality_videos_v11.py
python scripts/vtc/validate_quality_videos_v11.py --captures
```

The validator checks full audio/video decoding, timestamps, file hashes, captions,
text geometry, card anchors and silence at every learning pause. Focused tests in
`test_vtc_quality_release_v11.py` and `test_vtc_quality_progress_v11.py` exercise
real learner/preview APIs, historical completion, interrupted viewing, stale tabs
and course-scoped asset access. Historical v7/v9 tests explicitly isolate those
immutable repair layers.

Browser checks at phone portrait/landscape and desktop dimensions complement
these automated checks. Speech recognition detects missing or misunderstood
words; it does not certify human-rated accent or prosody.
