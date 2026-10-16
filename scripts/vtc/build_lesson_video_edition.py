"""Publish the complete lesson-video edition; never modify existing assignments."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from elearning_native import vtc
from elearning_native.vtc_lesson_videos import (
    ROOT as DATA, COURSE_VERSION as BASE, REQUIRED_VERSION as VERSION,
    LESSON_REFS, lesson_manifest, enrich_lessons, valid_video,
)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def build():
    lesson_manifest.cache_clear()
    videos = lesson_manifest()
    if set(videos) != LESSON_REFS:
        raise ValueError('All 96 validated videos are required before promoting the edition')
    for ref, video in videos.items():
        if not valid_video(ref, video):
            raise ValueError(f'Invalid video: {ref}')
        for field, checksum in (('src', 'media_sha256'), ('poster', 'poster_sha256'), ('captions', 'captions_sha256')):
            actual = hashlib.sha256((DATA / 'assets' / video[field]).read_bytes()).hexdigest()
            if actual != video[checksum]:
                raise ValueError(f'Video resource mismatch: {ref} / {field}')
    manifest = json.loads((DATA / 'manifest.json').read_text())
    pending = {}
    for module in manifest['modules']:
        cid = module['id']
        course = json.loads((DATA / 'courses' / cid / (BASE + '.json')).read_text())
        course['version'] = VERSION
        course['source']['edition'] = 'lecons-video-v10'
        course['source']['lesson_video_edition_on'] = '2026-10-10'
        # Validate every source hash before writing any edition files.
        checked = enrich_lessons(vtc._repair_video_pacing(vtc._repair_english_listening(
            vtc._repair_english_narration(copy.deepcopy(course)))))
        course['counts']['lesson_videos'] = 12
        course['counts']['required_videos'] = 13
        pending[DATA / 'courses' / cid / (VERSION + '.json')] = course
        module['version'] = VERSION
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), BASE]))
        module['counts'] = checked['counts']
    for folder in ('exams', 'training'):
        for source in sorted((DATA / folder / BASE).glob('*.json')):
            content = json.loads(source.read_text())
            content['version'] = VERSION
            pending[DATA / folder / VERSION / source.name] = content
    if len([p for p in pending if 'exams' in p.parts]) != 9 or len([p for p in pending if 'training' in p.parts]) != 8:
        raise ValueError('The complete exam and free-practice editions are required')
    summaries, summary_pauses = vtc._pacing_manifests()
    all_durations = [v['duration_seconds'] for v in videos.values()] + [v['duration_seconds'] for v in summaries['modules'].values()]
    pause_seconds = sum(p['duration_seconds'] for v in videos.values() for p in v['learning_pauses'])
    pause_seconds += sum(p['duration_seconds'] for v in summary_pauses['modules'].values() for p in v['pauses'])
    manifest.update(version=VERSION, lesson_video_count=96, summary_video_count=8,
                    video_count=104, narrated_video_count=104, animated_video_count=104,
                    video_minutes=round(sum(all_durations) / 60, 1), video_min_seconds=min(all_durations),
                    paced_video_minutes=round((sum(all_durations) / .85 + pause_seconds) / 60, 1),
                    programme_file='programme_lecons_video_v10.json')
    manifest['exam_versions'] = list(dict.fromkeys([*manifest['exam_versions'], VERSION]))
    programme = json.loads((DATA / 'programme_pedagogie.json').read_text())
    programme['version'] = VERSION
    programme['estimation_method'] = programme['estimation_method'].replace('Cours et vidéos inchangés. ', '')
    programme['estimation_method'] += ' Les nouvelles explications vidéo sont intégrées au temps de cours prévu ; aucun temps minimum supplémentaire n’est ajouté.'
    pending[DATA / manifest['programme_file']] = programme
    for path, content in pending.items():
        save(path, content)
    # Publish only after all immutable resources exist.
    save(DATA / 'manifest.json', manifest)
    print(json.dumps({'version': VERSION, 'lesson_videos': 96, 'total_videos': 104,
                      'paced_video_minutes': manifest['paced_video_minutes']}, ensure_ascii=False))


if __name__ == '__main__':
    build()
