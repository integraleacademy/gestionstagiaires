"""Reviewed VTC media repairs and compatibility with already-earned viewing.

The teaching edition, activity IDs and training-time ledger are unchanged.
Media revisions have immutable URLs. Only exact, bundled predecessor timelines
can map existing viewing positions into the corrected chapter timelines.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).parent / 'vtc'
VERSIONS = frozenset({'20261007-vtc-v4-visuals', '20261007-vtc-v5-annales',
                      '20261010-vtc-v6-pedagogie', '20261010-vtc-v10-lecons-video'})
LESSONS = frozenset(f'{m}.{i:02}' for m in 'ABCDEFGH' for i in range(1, 13))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_entry(ref, row, prior, is_lesson, *, revision=11):
    if not isinstance(row, dict) or row.get('render_revision') != revision:
        return False
    suffix = ref.lower().replace('.', '-')
    prefix = f'media/vtc/v{revision}/lesson-{suffix}'
    if any(row.get(key) != prefix + ext for key, ext in
           [('src', '.mp4'), ('poster', '.jpg'), ('captions', '.vtt')]):
        return False
    if (row.get('previous_src') != prior['src']
            or row.get('previous_duration_seconds') != prior['duration_seconds']
            or row.get('previous_chapters') != prior['chapters']):
        return False
    if is_lesson and row.get('source_sha256') != prior.get('source_sha256'):
        return False
    duration = row.get('duration_seconds')
    chapters = row.get('chapters')
    if (not _number(duration) or not 30 < duration < 1800
            or not isinstance(chapters, list) or len(chapters) != len(prior['chapters'])
            or not isinstance(row.get('transcript'), str) or len(row['transcript']) < 200):
        return False
    previous = 0
    for chapter in chapters:
        if not isinstance(chapter, dict):
            return False
        start, end = chapter.get('start_seconds'), chapter.get('end_seconds')
        if (not _number(start) or not _number(end) or abs(start - previous) > .1
                or not start < end <= duration + .08 or not chapter.get('title')):
            return False
        previous = end
    if abs(previous - duration) > .1:
        return False
    pauses = row.get('learning_pauses')
    if not isinstance(pauses, list) or not pauses:
        return False
    previous = 0
    for pause in pauses:
        at = pause.get('at_seconds') if isinstance(pause, dict) else None
        if (not _number(at) or not previous < at < duration
                or pause.get('duration_seconds') not in (4, 5) or not pause.get('message')):
            return False
        previous = at
    presentation = row.get('presentation')
    if not isinstance(presentation, dict):
        return False
    scenes, cues = presentation.get('scenes'), presentation.get('captions')
    if not isinstance(scenes, list) or len(scenes) != len(chapters) or not isinstance(cues, list) or not cues:
        return False
    for scene, chapter in zip(scenes, chapters):
        if (not isinstance(scene, dict) or scene.get('start') != chapter['start_seconds'] or scene.get('end') != chapter['end_seconds']
                or not scene.get('title') or not isinstance(scene.get('points'), list) or not scene['points']):
            return False
        at = scene['start']
        for point in scene['points']:
            if not isinstance(point, dict):
                return False
            when = point.get('at_seconds')
            if not _number(when) or not at <= when < scene['end'] or not point.get('label') or not point.get('text'):
                return False
            at = when
    previous = 0
    for cue in cues:
        if not isinstance(cue, dict):
            return False
        start, end = cue.get('start'), cue.get('end')
        if (not _number(start) or not _number(end) or not previous <= start < end <= duration + .01
                or not isinstance(cue.get('text'), str) or not cue['text']):
            return False
        previous = end
    return all((ROOT/'assets'/row[key]).is_file() for key in ('src', 'poster', 'captions'))


@lru_cache(maxsize=1)
def quality_manifest():
    path = ROOT/'video_quality_v11.json'
    if not path.exists():
        return {}  # Authoring still uses the complete prior collection.
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or data.get('revision') != 11
            or not isinstance(data.get('lessons'), dict) or set(data['lessons']) != LESSONS
            or not isinstance(data.get('modules'), dict) or set(data['modules']) != set('ABCDEFGH')):
        raise ValueError('The VTC quality collection is incomplete')
    old_lessons = json.loads((ROOT/'lesson_videos_v10.json').read_text())['lessons']
    old_modules = json.loads((ROOT/'video_pacing_v9.json').read_text())['modules']
    for entries, prior, lesson in [(data['lessons'], old_lessons, True), (data['modules'], old_modules, False)]:
        for ref, row in entries.items():
            if not _valid_entry(ref, row, prior[ref], lesson):
                raise ValueError(f'The VTC quality video is invalid: {ref}')
    return data


@lru_cache(maxsize=1)
def approved_voice_updates():
    """Load only reviewed replacements; keep the complete V11 collection intact."""
    path = ROOT/'video_voice_v14.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if (not isinstance(data, dict) or data.get('revision') != 14
            or not isinstance(data.get('lessons'), dict) or not data['lessons']
            or not set(data['lessons']) <= LESSONS):
        raise ValueError('The VTC voice update collection is invalid')
    predecessors = quality_manifest()['lessons']
    for ref, row in data['lessons'].items():
        before = predecessors[ref]
        if (not _valid_entry(ref, row, before, True, revision=14)
                or row.get('preview_only') is not False
                or row.get('voice') != {'fr': 'fr-FR-HenriNeural'}
                or row.get('default_playback_rate') != 1 or row.get('allowed_playback_rates') != [1]
                or row.get('voice_time_stretching') is not False
                or row.get('previous_media_sha256') != before['media_sha256']
                or [c.get('ref') for c in row['chapters']] != [c.get('ref') for c in before['chapters']]
                or (row['duration_seconds'] == before['duration_seconds'] and
                    [(c['start_seconds'], c['end_seconds']) for c in row['chapters']] !=
                    [(c['start_seconds'], c['end_seconds']) for c in before['chapters']])):
            raise ValueError(f'The VTC voice update is invalid: {ref}')
    return data['lessons']


def repair_course(course):
    cid, version = course.get('id', ''), course.get('version')
    if cid not in {f'academy-vtc-{m}' for m in 'abcdefgh'} or version not in VERSIONS:
        return course
    data = quality_manifest()
    if not data:
        return course
    updates = approved_voice_updates()
    letter = cid[-1].upper()
    for section in course.get('sections', []):
        for activity in section.get('activities', []):
            ref = activity.get('vtc', {}).get('ref')
            for block in activity.get('blocks', []):
                video = block.get('video')
                if not isinstance(video, dict):
                    continue
                expected_id = f'vtc-{letter.lower()}-capsule'
                baseline = data['modules'][letter] if video.get('id') == expected_id else data['lessons'].get(ref)
                row = updates.get(ref, baseline) if video.get('id') != expected_id else baseline
                if not row or video.get('src') == row['src']:
                    continue
                predecessors = {(baseline['previous_src'], baseline['previous_duration_seconds'])}
                if row is not baseline:
                    predecessors.add((baseline['src'], baseline['duration_seconds']))
                if (video.get('src'), video.get('duration_seconds')) not in predecessors:
                    raise ValueError('Unexpected VTC predecessor video')
                for key in ('src', 'poster', 'captions', 'duration_seconds', 'chapters', 'transcript',
                            'learning_pauses', 'presentation', 'render_revision'):
                    video[key] = copy.deepcopy(row[key])
                video.update(default_playback_rate=1, allowed_playback_rates=[1])
                if video.get('id') == expected_id:
                    activity.setdefault('vtc', {})['transcript'] = row['transcript']
                for key in ('src', 'poster', 'captions'):
                    if row[key] not in course['assets']:
                        course['assets'].append(row[key])
    course.setdefault('counts', {})['assets'] = len(course['assets'])
    # An open D.02 player must reload before reporting against the new timeline.
    course['vtc_media_revision'] = 14 if any(ref.startswith(letter+'.') for ref in updates) else 13
    return course


def compatible_record(video_id, record, duration):
    """Project a trusted saved record; never award training time or use receipts.

    Completion is grandfathered only for a genuinely complete predecessor.
    An unfinished prefix maps within the same chapter, never into later chapters.
    Unknown durations and unrelated courses retain the normal strict behaviour.
    """
    if not isinstance(record, Mapping) or record.get('duration_seconds') == duration:
        return record
    import re
    match = re.fullmatch(r'vtc-([a-h])-(?:(\d{2})-explanation-v10|capsule)', video_id)
    if not match:
        return record
    data = quality_manifest()
    if not data:
        return record
    letter, number = match.groups()
    row = data['lessons'].get(f'{letter.upper()}.{number}') if number else data['modules'].get(letter.upper())
    update = approved_voice_updates().get(f'{letter.upper()}.{number}') if number else None
    if row and update and duration == update['duration_seconds'] and duration != row['duration_seconds']:
        # Trusted V10 records first project to V11, then to the approved voice.
        # V11 records skip the first hop. Unknown durations remain unchanged.
        record = compatible_record(video_id, record, row['duration_seconds'])
        row = update
    if (not row or duration != row['duration_seconds']
            or record.get('duration_seconds') != row['previous_duration_seconds']):
        return record
    frontier = record.get('watched_seconds', 0)
    if not _number(frontier) or frontier < 0 or frontier > row['previous_duration_seconds'] + .5:
        return record
    completed = record.get('completed') is True and frontier >= row['previous_duration_seconds'] - .25
    if completed:
        mapped = duration
    else:
        mapped = 0.
        for before, after in zip(row['previous_chapters'], row['chapters']):
            start, end = before['start_seconds'], before['end_seconds']
            if frontier < start:
                break
            fraction = min(1., max(0., (frontier-start)/(end-start)))
            mapped = after['start_seconds'] + fraction * (after['end_seconds']-after['start_seconds'])
            if frontier < end:
                break
        # An unfinished old record must never become completed through rounding.
        mapped = min(mapped, duration - .5)
    return {**record, 'duration_seconds': duration, 'watched_seconds': round(mapped, 3),
            'completed': completed, 'completed_at': record.get('completed_at') if completed else None}


def compatible_progress(saved, requirements):
    result = dict(saved)
    for activity_id, videos in requirements.items():
        if activity_id not in saved:
            continue
        records = saved[activity_id]
        if not isinstance(records, Mapping):
            continue
        result[activity_id] = {vid: compatible_record(vid, state, videos[vid]) if vid in videos else state
                               for vid, state in records.items()}
    return result
