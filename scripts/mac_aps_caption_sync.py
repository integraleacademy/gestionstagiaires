"""Reflow authored MAC APS captions without inventing speech timestamps.

The only timing operation is a merge of adjacent, complete source cues: its
start is the first cue's start and its end is the last cue's end. Other cue
boundaries remain unchanged. Whitespace may be reflowed; words, punctuation,
case and order are preserved. This module never writes a media or subtitle file.
"""

from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import re

from PIL import ImageFont


class CaptionReflowError(ValueError):
    """A cue needs real word timestamps, a wider area or a smaller font.

    ``issues`` contains zero-based source cue indexes and original timestamps,
    so a caller can resolve the specific cues without estimating word timings.
    """

    def __init__(self, issues):
        self.issues = issues
        descriptions = [
            f"cue {issue['index']} at {issue['start']:.3f}s: {issue['reason']}"
            for issue in issues
        ]
        super().__init__("Caption reflow requires review: " + "; ".join(descriptions))


def _timestamp(value):
    match = re.fullmatch(r"(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})", value)
    if not match:
        raise ValueError(f"Invalid WebVTT timestamp: {value!r}")
    hours, minutes, seconds, millis = (int(part or 0) for part in match.groups())
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid WebVTT timestamp: {value!r}")
    return ((hours * 3600 + minutes * 60 + seconds) * 1000 + millis) / 1000


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Caption text must be a nonempty string")
    return " ".join(value.split())


def _validated(cues):
    result = []
    previous_end = 0.0
    for index, cue in enumerate(cues):
        start, end = float(cue["start"]), float(cue["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"Invalid caption interval at cue {index}: {start}..{end}")
        if start < previous_end:
            raise ValueError(f"Overlapping or unordered captions at cue {index}")
        result.append({"start": start, "end": end, "text": _text(cue["text"])})
        previous_end = end
    return result


def parse_vtt(path):
    """Read plain-text WebVTT cues, retaining their original timed boundaries.

    A UTF-8 BOM, cue identifiers, cue settings and NOTE/STYLE/REGION blocks are
    accepted. Nonpositive intervals, overlaps and malformed cues are rejected.
    The return value is a list of ``{start, end, text}`` dictionaries in seconds.
    """
    source = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", source.strip())
    if not blocks or not re.match(r"^WEBVTT(?:[ \t\n]|$)", blocks[0]):
        raise ValueError("Missing WEBVTT header")
    cues = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        if re.match(r"^NOTE(?:[ \t]|$)", lines[0]) or lines[0] in {"STYLE", "REGION"}:
            continue
        timing_index = 0 if "-->" in lines[0] else 1
        if timing_index >= len(lines):
            raise ValueError(f"Missing timing line in WebVTT block: {lines[0]!r}")
        match = re.fullmatch(r"(\S+)[ \t]+-->[ \t]+(\S+)(?:[ \t]+.*)?", lines[timing_index])
        if not match:
            raise ValueError(f"Malformed WebVTT timing line: {lines[timing_index]!r}")
        cues.append({
            "start": _timestamp(match.group(1)),
            "end": _timestamp(match.group(2)),
            "text": "\n".join(lines[timing_index + 1:]),
        })
    return _validated(cues)


def reflow_captions(cues, font_path, font_size=38, max_width=1170):
    """Balance captions on at most two measured lines and merge problem cues.

    A problem cue contains one word or lasts less than one second. Only adjacent
    whole cues may be merged. The partition removes as few source boundaries as
    possible, then prefers joining an isolated word to its preceding sentence.
    If that does not fit, joining it to the next cue is permitted. No cue is
    split, truncated, paraphrased, retimed individually or silently omitted.

    Font measurements include both glyph advance and the actual ink bounds.
    ``CaptionReflowError`` exposes unresolved cases; callers must obtain real
    word timings to split those cases rather than estimate new boundaries.
    """
    if font_size <= 0 or not math.isfinite(float(max_width)) or max_width <= 0:
        raise ValueError("font_size and max_width must be positive")
    source = _validated(cues)
    if not source:
        return []
    font = ImageFont.truetype(str(font_path), font_size)

    @lru_cache(maxsize=None)
    def width(text):
        left, _, right, _ = font.getbbox(text)
        return max(float(font.getlength(text)), float(right - left))

    @lru_cache(maxsize=None)
    def wrap(text):
        if width(text) <= max_width:
            return text
        words = text.split()
        candidates = []
        for split in range(1, len(words)):
            first, second = " ".join(words[:split]), " ".join(words[split:])
            first_width, second_width = width(first), width(second)
            if max(first_width, second_width) <= max_width:
                score = (
                    min(split, len(words) - split) == 1,
                    abs(first_width - second_width),
                    max(first_width, second_width),
                    split,
                )
                candidates.append((score, first + "\n" + second))
        return min(candidates, default=(None, None), key=lambda item: item[0])[1]

    def issue(index, reason):
        return {"index": index, **source[index], "reason": reason}

    oversized = [
        issue(index, f"the original cue cannot fit two lines at {font_size}px / {max_width}px")
        for index, cue in enumerate(source) if wrap(cue["text"]) is None
    ]
    if oversized:
        raise CaptionReflowError(oversized)

    problem = [
        len(cue["text"].split()) == 1 or cue["end"] - cue["start"] < 1.0 - 1e-9
        for cue in source
    ]
    count = len(source)
    # Dynamic programming avoids a greedy merge consuming the only usable
    # neighbour of a later short cue. A state is (removed bounds, forward joins,
    # merged silent gaps); all three costs are minimised in this order.
    best = [None] * (count + 1)
    choice = [None] * count
    best[count] = (0, 0, 0.0)
    for first in range(count - 1, -1, -1):
        text, contains_problem, gap = "", False, 0.0
        for last in range(first, count):
            text = (text + " " + source[last]["text"]).strip()
            wrapped = wrap(text)
            if wrapped is None:
                break
            contains_problem = contains_problem or problem[last]
            if last > first:
                gap += source[last]["start"] - source[last - 1]["end"]
            duration = source[last]["end"] - source[first]["start"]
            if duration < 1.0 - 1e-9 or len(text.split()) == 1:
                continue
            if last > first and not contains_problem:
                continue
            tail = best[last + 1]
            if tail is None:
                continue
            cost = (
                last - first + tail[0],
                int(last > first and problem[first]) + tail[1],
                gap + tail[2],
            )
            if best[first] is None or cost < best[first]:
                best[first], choice[first] = cost, (last, wrapped)

    if best[0] is None:
        unresolved = []
        for index, cue in enumerate(source):
            if not problem[index]:
                continue
            item = issue(index, "no complete, fitting partition can remove this short or isolated cue")
            item["adjacent_merges"] = []
            for neighbour in (index - 1, index + 1):
                if 0 <= neighbour < count:
                    first, last = sorted((index, neighbour))
                    text = source[first]["text"] + " " + source[last]["text"]
                    item["adjacent_merges"].append({
                        "neighbour_index": neighbour,
                        "start": source[first]["start"],
                        "end": source[last]["end"],
                        "text": text,
                        "fits": wrap(text) is not None,
                    })
            unresolved.append(item)
        raise CaptionReflowError(unresolved)

    output, index = [], 0
    while index < count:
        last, wrapped = choice[index]
        output.append({"start": source[index]["start"], "end": source[last]["end"], "text": wrapped})
        index = last + 1
    if " ".join(_text(cue["text"]) for cue in output) != " ".join(cue["text"] for cue in source):
        raise AssertionError("Authored caption text changed during reflow")
    return output
