"""Rebuild MAC APS pictures while preserving the original AAC and learner clock.

One-time alignment: --asr-dir DIR (faster-whisper word timestamps on the five
original MP4s). Reviewed semantic anchors live in mac_aps_visual_sync.json.
The compact, source-hashed alignment is retained in mac_aps_visual_timing.json;
subsequent builds need no speech service or recognition model.

    python scripts/resync_mac_aps.py --asr-dir /tmp/macaps-asr --align-only
    python scripts/resync_mac_aps.py --module 02
    python scripts/resync_mac_aps.py --merge --demo

Old media and course snapshots are deliberately retained. duration_seconds is
the canonical tracking duration, not the new container's frame-rounded end.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import re

import render_mac_aps as render
from mac_aps_caption_sync import parse_vtt, reflow_captions

ROOT = render.ROOT
SOURCE = render.RES / "assets/media/mac-aps/v1"
WORK = Path("/tmp/mac-aps-resync-v3")
PLAN = Path(__file__).with_name("mac_aps_visual_sync.json")
TIMING = Path(__file__).with_name("mac_aps_visual_timing.json")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def align_module(module, asr_dir):
    """Match recognized words to authored characters; never replace the prose."""
    source_meta = json.loads((SOURCE / f"module-{module}.json").read_text())
    cues = parse_vtt(SOURCE / f"module-{module}.vtt")
    scenes = render.MODULES[module]["scenes"]
    transcript = "\n\n".join(scene["text"] for scene in scenes)
    reference = render.normalize(transcript)
    assert reference == render.normalize(" ".join(c["text"] for c in cues))
    recognized = json.loads((asr_dir / f"module-{module}-asr.json").read_text())
    words = [word for segment in recognized["segments"] for word in segment["words"]]
    observed, word_at = "", []
    for word in words:
        normalized = render.normalize(word["word"])
        observed += normalized
        word_at.extend([word] * len(normalized))
    mapping = {}
    for block in SequenceMatcher(None, reference, observed, autojunk=False).get_matching_blocks():
        mapping.update((block.a + i, block.b + i) for i in range(block.size))
    coverage = len(mapping) / len(reference)
    assert coverage >= .94, (module, "recognition requires review", coverage)
    cue_spans, cursor = [], 0
    for cue in cues:
        end = cursor + len(render.normalize(cue["text"]))
        cue_spans.append((cursor, end, cue))
        cursor = end

    def located(position, max_skip=10):
        for delta in range(max_skip + 1):
            if position + delta in mapping:
                return word_at[mapping[position + delta]], delta
        raise ValueError(f"Unmatched speech anchor {module}/{position}")

    authored = json.loads(PLAN.read_text())["modules"][module]
    aligned, cursor = [], 0
    for index, (scene, planned, chapter) in enumerate(zip(scenes, authored, source_meta["chapters"])):
        assert scene["title"] == planned["title"]
        events = []
        previous_position, previous_time = -1, chapter["start_seconds"] - .001
        for event in planned["events"]:
            assert scene["text"].count(event["anchor"]) == 1
            char = scene["text"].index(event["anchor"])
            position = cursor + len(render.normalize(scene["text"][:char]))
            word, skipped = located(position)
            cue_left, _, cue = next(row for row in cue_spans if row[0] <= position < row[1])
            # An original cue begins exactly 50 ms before its measured TTS word.
            # Prefer this known boundary over an ASR estimate after a pause.
            at_cue_start = position == cue_left
            start = round(cue["start"] + .05 if at_cue_start else float(word["start"]), 3)
            assert position > previous_position
            assert chapter["start_seconds"] - .12 <= start < chapter["end_seconds"], (module, index, event, word)
            assert cue["start"] - .8 <= start <= cue["end"] + .5, (module, index, event, word, cue)
            assert start >= previous_time, (module, index, "unordered recognized words")
            events.append({"anchor": event["anchor"], "active": event["active"], "start_seconds": start,
                           "timing_source": "original_tts_word_boundary" if at_cue_start else "recognized_word_inside_original_cue",
                           "matched_word": word["word"].strip(), "recognition_probability": round(word["probability"], 3),
                           "matched_character_skip": skipped, "source_cue_start": cue["start"], "source_cue_end": cue["end"]})
            previous_position, previous_time = position, start
        aligned.append({"scene_index": index, "title": scene["title"], "start_seconds": chapter["start_seconds"],
                        "end_seconds": chapter["end_seconds"], "events": events})
        cursor += len(render.normalize(scene["text"]))

    # An independent diagnostic of speech against the original TTS caption cues.
    # ASR itself is not sample-exact; outliers are explicitly retained for review.
    diagnostics, unmatched = [], []
    for left, right, cue in cue_spans:
        try:
            first, skipped = located(left)
        except ValueError:
            unmatched.append(cue)
            continue
        last_position = next((i for i in range(right - 1, max(left - 1, right - 12), -1) if i in mapping), None)
        if last_position is None:
            unmatched.append({**cue, "reason": "ASR did not retain the end of this authored sentence"})
            continue
        last = word_at[mapping[last_position]]
        diagnostics.append({"cue_start": cue["start"], "cue_end": cue["end"],
                            "speech_start": round(first["start"], 3), "speech_end": round(last["end"], 3),
                            "start_delta": round(first["start"] - cue["start"], 3),
                            "end_delta": round(last["end"] - cue["end"], 3), "skipped": skipped})
    deltas = sorted(d["start_delta"] for d in diagnostics)
    audit = {"cue_count": len(cues), "compared_cues": len(diagnostics), "matched_characters_percent": round(coverage * 100, 3),
             "median_speech_start_minus_caption": deltas[len(deltas) // 2],
             "minimum_speech_start_minus_caption": min(deltas), "maximum_speech_start_minus_caption": max(deltas),
             "unmatched_cues": unmatched,
             "outliers": [d for d in diagnostics if abs(d["start_delta"] - .05) > .5 or abs(d["end_delta"] + .18) > .6]}
    return {"source_video_sha256": sha(SOURCE / f"module-{module}.mp4"), "canonical_duration_seconds": source_meta["duration_seconds"],
            "recognition_model": recognized["model"], "audit": audit, "scenes": aligned}


def write_vtt(path, cues):
    body = "".join(f"{render.stamp(c['start'])} --> {render.stamp(c['end'])}\n{c['text']}\n\n" for c in cues)
    path.write_text("WEBVTT\n\n" + body.rstrip() + "\n", encoding="utf-8")


def audio_hash(path):
    return render.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "copy",
                       "-f", "hash", "-hash", "sha256", "-"]).stdout.decode().strip()


def remux(video, audio_source, destination):
    render.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-copyts", "-i", str(video), "-i", str(audio_source),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "copy", "-map_metadata", "-1",
                "-avoid_negative_ts", "disabled", "-movflags", "+faststart", str(destination)])
    assert audio_hash(destination) == audio_hash(audio_source), "Narration packets changed"


def build(module):
    timing = json.loads(TIMING.read_text())
    assert timing["semantic_plan_sha256"] == sha(PLAN), "Semantic plan changed; review alignment again"
    aligned = timing["modules"][module]
    original = SOURCE / f"module-{module}.mp4"
    assert sha(original) == aligned["source_video_sha256"], "Speech source changed"
    source = json.loads((SOURCE / f"module-{module}.json").read_text())
    assert source["transcript"] == "\n\n".join(s["text"] for s in render.MODULES[module]["scenes"])
    folder = WORK / module
    folder.mkdir(parents=True, exist_ok=True)
    render.ASSETS.mkdir(parents=True, exist_ok=True)
    cues = reflow_captions(parse_vtt(SOURCE / f"module-{module}.vtt"), render.FONT)
    frame_count = math.ceil(render.duration(original) * render.FPS)
    target = frame_count / render.FPS
    timeline = []
    for scene in aligned["scenes"]:
        timeline.append({"frame": round(scene["start_seconds"] * render.FPS), "scene_index": scene["scene_index"], "active": []})
        for event in scene["events"]:
            timeline.append({"frame": round(event["start_seconds"] * render.FPS), "scene_index": scene["scene_index"], "active": event["active"]})
    by_frame = {event["frame"]: event for event in timeline}
    timeline = [by_frame[n] for n in sorted(by_frame)]
    assert timeline[0]["frame"] == 0 and timeline[-1]["frame"] < frame_count
    lines, last_path, created = [], None, set()
    for i, event in enumerate(timeline):
        active = "".join(map(str, event["active"])) or "neutral"
        picture = folder / f"scene-{event['scene_index']:02}-{active}.png"
        if picture not in created:
            render.frame(module, event["scene_index"], event["active"]).save(picture)
            created.add(picture)
        end = timeline[i + 1]["frame"] if i + 1 < len(timeline) else frame_count
        lines.append(f"file '{picture}'\nduration {(end - event['frame']) / render.FPS:.8f}\n")
        last_path = picture
    slideshow = folder / "frames.txt"
    slideshow.write_text("".join(lines) + f"file '{last_path}'\n")
    ass = folder / "captions.ass"
    render.ass_file(ass, cues)
    silent = folder / "pictures.mp4"
    render.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-f", "concat", "-safe", "0", "-i", str(slideshow),
                "-vf", f"fps={render.FPS},ass={ass}:fontsdir={render.FONT.parent},format=yuv420p", "-frames:v", str(frame_count),
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-tune", "stillimage", "-threads", "2", str(silent)])
    destination = render.ASSETS / f"module-{module}.mp4"
    remux(silent, original, destination)
    actual = render.duration(destination)
    assert abs(actual - source["duration_seconds"]) < .05, (module, actual, source["duration_seconds"])
    assert actual >= cues[-1]["end"] and abs(actual - target) < .05
    assert re.sub(r"\s+", "", " ".join(c["text"] for c in cues)) == re.sub(r"\s+", "", source["transcript"])
    write_vtt(render.ASSETS / f"module-{module}.vtt", cues)
    render.frame(module, 0, []).save(render.ASSETS / f"module-{module}.jpg", quality=91)
    entry = {**source, "src": f"media/mac-aps/v3/module-{module}.mp4", "poster": f"media/mac-aps/v3/module-{module}.jpg",
             "captions": f"media/mac-aps/v3/module-{module}.vtt", "caption_cues": len(cues), "render_revision": render.REVISION,
             "source_sha256": render.source_signature(module), "video_sha256": sha(destination), "source_video_sha256": sha(original),
             "audio_preserved": True, "audio_packet_sha256": audio_hash(destination).split("=")[-1], "playback_duration_seconds": actual,
             "subtitle_font_pixels": 38, "subtitle_bottom_margin_pixels": 22, "subtitle_band_pixels": 128, "frame_rate": render.FPS,
             "visual_sync": [{"scene_index": s["scene_index"], "events": [{"start_seconds": e["start_seconds"], "active": e["active"], "anchor": e["anchor"]} for e in s["events"]]} for s in aligned["scenes"]]}
    save_json(render.ASSETS / f"module-{module}.json", entry)
    render.verify_entry(module, full_decode=True)
    print(f"Module {module}: {actual:.3f}s, AAC intact, {len(cues)} sous-titres, {sum(len(s['events']) for s in aligned['scenes'])} ancrages", flush=True)
    return entry


def demo():
    demo_root = ROOT / "static/elearning-demo/mac-aps"
    folder = WORK / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    silent = folder / "pictures.mp4"
    original = demo_root / "republique-extrait.mp4"
    render.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-y", "-i", str(render.ASSETS / "module-02.mp4"),
                "-an", "-frames:v", str(86 * render.FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
                "-threads", "2", str(silent)])
    destination = demo_root / "republique-extrait-v3.mp4"
    remux(silent, original, destination)
    assert abs(render.duration(destination) - 86) < .05
    cues = reflow_captions([c for c in parse_vtt(render.ASSETS / "module-02.vtt") if c["end"] <= 86], render.FONT)
    assert render.normalize(" ".join(c["text"] for c in cues)) == render.normalize(" ".join(c["text"] for c in parse_vtt(demo_root / "republique-extrait.vtt")))
    write_vtt(demo_root / "republique-extrait-v3.vtt", cues)
    render.frame("02", 0, []).save(demo_root / "republique-poster-v3.jpg", quality=91)
    render.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(destination), "-f", "null", "-"])
    print("Extrait public : 86 secondes, piste AAC originale préservée", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-dir", type=Path)
    parser.add_argument("--align-only", action="store_true")
    parser.add_argument("--module", choices=sorted(render.MODULES))
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.asr_dir:
        data = {"schema_version": 1, "revision": render.REVISION, "semantic_plan_sha256": sha(PLAN),
                "method": "Recognized speech words matched to the unchanged authored transcript, bounded by original TTS cues; reviewed semantic anchors.",
                "modules": {module: align_module(module, args.asr_dir) for module in render.MODULES}}
        save_json(TIMING, data)
        for module, row in data["modules"].items():
            print(module, json.dumps(row["audit"], ensure_ascii=False), flush=True)
    if args.align_only:
        return
    if not args.merge:
        selected = [args.module] if args.module else list(render.MODULES)
        with ThreadPoolExecutor(max_workers=min(2, len(selected))) as pool:
            list(pool.map(build, selected))
    if args.merge or not args.module:
        render.merge(full_decode=True)
    if args.demo:
        demo()


if __name__ == "__main__":
    main()
