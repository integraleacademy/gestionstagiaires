"""Add reviewed lesson explainers without rewriting historical learner records."""
from __future__ import annotations

import copy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).parent / 'vtc'
COURSE_VERSION = '20261010-vtc-v6-pedagogie'
REQUIRED_VERSION = '20261010-vtc-v10-lecons-video'
LESSON_REFS = frozenset(f'{letter}.{number:02}' for letter in 'ABCDEFGH' for number in range(1, 13))


def source_hash(lesson):
    return hashlib.sha256(json.dumps(lesson, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def lesson_manifest():
    try:
        manifest = json.loads((ROOT / 'lesson_videos_v10.json').read_text())
    except (FileNotFoundError, ValueError):
        return {}
    # Publish the complete collection together, never a partially built batch.
    if manifest.get('revision') != 10 or set(manifest.get('lessons', {})) != LESSON_REFS:
        return {}
    return manifest['lessons']


def valid_video(ref, video):
    if not isinstance(video, dict) or ref not in LESSON_REFS:
        return False
    prefix = 'media/vtc/v10/lesson-' + ref.lower().replace('.', '-')
    if any(video.get(key) != prefix + suffix for key, suffix in
           (('src', '.mp4'), ('poster', '.jpg'), ('captions', '.vtt'))):
        return False
    duration = video.get('duration_seconds')
    if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
            or not math.isfinite(duration) or not 30 < duration < 1200
            or not isinstance(video.get('transcript'), str)
            or len(video['transcript']) < 200
            or not re.fullmatch(r'[0-9a-f]{64}', str(video.get('source_sha256', '')))):
        return False
    chapters = video.get('chapters', [])
    pauses = video.get('learning_pauses', [])
    if (not isinstance(chapters, list) or not isinstance(pauses, list)
            or not 4 <= len(chapters) <= 8 or not 1 <= len(pauses) <= 7):
        return False
    previous = -1
    for chapter in chapters:
        if not isinstance(chapter, dict):
            return False
        start = chapter.get('start_seconds')
        if (not isinstance(start, (int, float)) or isinstance(start, bool)
                or not math.isfinite(start) or start < 0 or not previous < start < duration
                or not isinstance(chapter.get('title'), str)):
            return False
        previous = start
    previous = 0
    for pause in pauses:
        if not isinstance(pause, dict):
            return False
        at = pause.get('at_seconds')
        if (not isinstance(at, (int, float)) or isinstance(at, bool)
                or not math.isfinite(at) or not previous < at < duration
                or pause.get('duration_seconds') not in (4, 5)
                or not isinstance(pause.get('message'), str) or not pause['message']):
            return False
        previous = at
    return all((ROOT / 'assets' / video[key]).is_file() for key in ('src', 'poster', 'captions'))


def enrich_lessons(course):
    if (course.get('version') not in (COURSE_VERSION, REQUIRED_VERSION)
            or not re.fullmatch(r'academy-vtc-[a-h]', str(course.get('id', '')))):
        return course
    manifest = lesson_manifest()
    def unavailable():
        if course['version'] == REQUIRED_VERSION:
            raise ValueError('The required VTC lesson-video edition is incomplete or stale')
        return course
    candidates = []
    for section in course.get('sections', []):
        for activity in section.get('activities', []):
            lesson = activity.get('vtc', {})
            if lesson.get('kind') != 'lesson':
                continue
            ref = lesson.get('ref')
            video = manifest.get(ref)
            if (not valid_video(ref, video) or video['source_sha256'] != source_hash(lesson)
                    or ref[0].lower() != course['id'][-1]):
                return unavailable()
            candidates.append((activity, ref, video))
    if len(candidates) != 12:
        return unavailable()
    for activity, ref, rendered in candidates:
        video_id = 'vtc-' + ref.lower().replace('.', '-') + '-explanation-v10'
        if any(block.get('id') == video_id for block in activity.get('blocks', [])):
            continue
        video = {key: copy.deepcopy(rendered[key]) for key in (
            'src', 'poster', 'captions', 'duration_seconds', 'chapters',
            'transcript', 'learning_pauses')}
        video.update(id=video_id, title='Comprendre en vidéo · ' + activity['title'],
                     required=course['version'] == REQUIRED_VERSION,
                     lesson_explainer=True, render_revision=10,
                     default_playback_rate=.85, allowed_playback_rates=[.85, 1])
        activity.setdefault('blocks', []).insert(0, dict(id=video_id, type='video',
                                                        html='', children=[], video=video))
        for field in ('src', 'poster', 'captions'):
            if video[field] not in course['assets']:
                course['assets'].append(video[field])
    course.setdefault('counts', {}).update(lesson_videos=12, assets=len(course['assets']))
    if course['version'] == REQUIRED_VERSION:
        course['counts']['required_videos'] = 13
    return course
