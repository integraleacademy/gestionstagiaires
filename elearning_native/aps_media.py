"""Original APS voice, with a reviewed mapping from the former paced timeline."""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).parent / 'aps62'
REVISION = '20261013-aps-natural-voice'


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@lru_cache(maxsize=1)
def natural_manifest():
    path = ROOT / 'natural_voice_v13.json'
    if not path.is_file():
        return {}  # Media preparation can run before the reviewed release exists.
    data = json.loads(path.read_text())
    prior = json.loads((ROOT / 'video_manifest_v9.json').read_text())
    if data.get('revision') != REVISION or set(data.get('videos', {})) != set(prior):
        raise ValueError('Incomplete APS natural voice collection')
    for sid, row in data['videos'].items():
        old = prior[sid]
        duration = row.get('duration_seconds')
        valid = (
            row.get('render_revision') == REVISION
            and row.get('src') == f'media/aps62/v13/{sid}.mp4'
            and row.get('captions') == f'media/aps62/v13/{sid}.vtt'
            and row.get('source_src') == f'media/aps62/v8/{sid}.mp4'
            and row.get('previous_src') == old['src']
            and row.get('previous_duration_seconds') == old['duration_seconds']
            and row.get('voice') == old['voice'] == 'fr-FR-HenriNeural'
            and row.get('original_voice_samples_preserved') is True
            and row.get('voice_time_stretching') is False
            and row.get('timeline_scale') == .87
            and row.get('transcript_sha256') == hashlib.sha256(old['transcript'].encode()).hexdigest()
            and _number(duration) and duration >= 300
            and abs(duration - old['duration_seconds'] * .87) < .15
        )
        chapters = row.get('chapters', [])
        valid = valid and len(chapters) == len(old['chapters'])
        for before, after in zip(old['chapters'], chapters):
            valid = (valid and after.get('title') == before['title']
                     and all(_number(after.get(key)) and abs(after[key] - before[key] * .87) < .15
                             for key in ('start_seconds', 'end_seconds')))
        if not valid:
            raise ValueError(f'Invalid APS natural voice media: {sid}')
    return data['videos']


def restore_course_voice(course):
    manifest = natural_manifest()
    for section in course['sections']:
        row = manifest.get(section['id'])
        if not row:
            continue
        for activity in section['activities']:
            for block in activity.get('blocks', []):
                video = block.get('video', {})
                # Earlier teaching editions may contain different narrations.
                # Only replace the identical reviewed predecessor.
                if video.get('src') != row['previous_src']:
                    continue
                if (video.get('duration_seconds') != row['previous_duration_seconds']
                        or hashlib.sha256(video.get('transcript', '').encode()).hexdigest() != row['transcript_sha256']):
                    raise ValueError('Unexpected APS predecessor video')
                for key in ('src', 'captions', 'duration_seconds', 'narration_seconds',
                            'chapters', 'render_revision', 'voice', 'rate'):
                    video[key] = copy.deepcopy(row[key])
                video['pacing'] = dict(tempo=1, voice_time_stretching=False,
                                       timeline_revision=REVISION)
                for key in ('src', 'captions'):
                    if row[key] not in course['assets']:
                        course['assets'].append(row[key])
    course['aps_media_revision'] = REVISION
    course.setdefault('counts', {})['assets'] = len(course['assets'])
    return course


def compatible_record(video_id, record, duration):
    """Retain earned viewing only for the exact bundled predecessor timeline."""
    if not isinstance(record, Mapping) or record.get('duration_seconds') == duration:
        return record
    if not video_id.startswith('aps62-') or not video_id.endswith('-video'):
        return record
    row = natural_manifest().get(video_id.removesuffix('-video'))
    if (not row or duration != row['duration_seconds']
            or record.get('duration_seconds') != row['previous_duration_seconds']):
        return record
    frontier = record.get('watched_seconds', 0)
    if not _number(frontier) or not 0 <= frontier <= row['previous_duration_seconds'] + .5:
        return record
    completed = record.get('completed') is True and frontier >= row['previous_duration_seconds'] - .25
    mapped = duration if completed else min(frontier * row['timeline_scale'], duration - .5)
    return {**record, 'duration_seconds': duration, 'watched_seconds': round(mapped, 3),
            'completed': completed, 'completed_at': record.get('completed_at') if completed else None}
