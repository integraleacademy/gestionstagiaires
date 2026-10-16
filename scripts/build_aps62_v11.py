"""Publish the calmer APS video edition without rewriting assigned editions.

The spoken content, questions, productions and activity order stay identical to
v10. All 62 new media files must exist before the current catalogue is advanced.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.aps62_v10.video_content import courses as authored_videos

ROOT = REPO / 'elearning_native/aps62'
VERSION = '20261010-aps62-v11'
PREVIOUS = '20261010-aps62-v10'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def historical_digest():
    files = sorted((ROOT/'courses').glob('*/*.json')) + sorted((ROOT/'exams').glob('*/*.json'))
    digest = hashlib.sha256()
    for path in files:
        if VERSION not in str(path):
            digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def collect_assets(value):
    assets = set()
    def collect(item):
        if isinstance(item, str) and item.startswith('media/aps62/'):
            assets.add(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                if key != 'assets':
                    collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)
    collect(value)
    return sorted(assets)


def build():
    if any((ROOT/'courses').glob('*/' + VERSION + '.json')) or (ROOT/'exams'/VERSION).exists():
        raise ValueError('Existing published editions are immutable: ' + VERSION)
    before = historical_digest()
    manifest = read(ROOT/'manifest.json')
    assert manifest['version'] == PREVIOUS, 'Build from the reviewed v10 edition'
    authored = authored_videos()
    videos = read(ROOT/'video_manifest_v9.json')
    assert set(videos) == set(authored) and len(videos) == 62, 'All 62 paced videos are required'
    for sid, video in videos.items():
        assert video['duration_seconds'] >= 300 and video['narration_seconds'] >= 300
        assert video['transcript'] == authored[sid]['transcript'], sid
        assert video['field_demonstrations'] and video['render_revision'] == 9, sid
        assert video.get('pacing'), 'Missing measured pacing metadata: ' + sid
        for key, ext in (('src', 'mp4'), ('captions', 'vtt'), ('poster', 'jpg')):
            assert video[key] == f'media/aps62/v9/{sid}.{ext}'
            assert (ROOT/'assets'/video[key]).is_file()
    staged = {}
    production_count = practice_count = activity_count = minutes = 0
    for module in manifest['modules']:
        course = read(ROOT/'courses'/module['id']/(PREVIOUS + '.json'))
        original_order = copy.deepcopy(course['activity_order'])
        course['version'] = course['interaction_revision'] = VERSION
        for section in course['sections']:
            sid = section['id']
            old_total = sum(a['planned_minutes'] for a in section['activities'])
            for activity in section['activities']:
                activity_count += 1
                if activity.get('practice'):
                    activity['practice']['revision'] = VERSION
                    practice_count += 1
                production_count += bool(activity.get('production'))
                for block in activity.get('blocks', []):
                    if block.get('video'):
                        block['video'].update(copy.deepcopy(videos[sid]))
                        video_minutes = math.ceil(videos[sid]['duration_seconds']/60) + 1
                        difference = video_minutes - activity['planned_minutes']
                        activity['planned_minutes'] = video_minutes
                        section['activities'][0]['planned_minutes'] -= difference
                if activity.get('academy', {}).get('kind') == 'memory':
                    activity['academy'].update(transcript=videos[sid]['transcript'], voice=videos[sid]['voice'])
            assert all(a['planned_minutes'] > 0 for a in section['activities']), sid
            assert sum(a['planned_minutes'] for a in section['activities']) == old_total, sid
            minutes += old_total
            section['activities'][0]['academy']['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
        course['assets'] = collect_assets(course)
        assert all((ROOT/'assets'/p).is_file() for p in course['assets'])
        assert course['activity_order'] == original_order
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']) == course['planned_minutes']
        staged[ROOT/'courses'/module['id']/(VERSION + '.json')] = course
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), PREVIOUS]))
        module['version'] = VERSION
    for path in (ROOT/'exams'/PREVIOUS).glob('*.json'):
        exam = read(path)
        exam['version'] = VERSION
        staged[ROOT/'exams'/VERSION/path.name] = exam
    assert len(staged) == 31
    assert (production_count, practice_count, activity_count, minutes) == (10, 132, 452, 3720)
    manifest.update(version=VERSION, interaction_revision=VERSION)
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    manifest['visual_learning'].update(paced_long_videos=62, pacing_revision=9, authored_on='2026-10-10')
    review = read(ROOT/'regulatory_review.json')
    review['edition'] = VERSION
    for path, value in staged.items():
        write(path, value)
    assert historical_digest() == before
    write(ROOT/'video_scripts_v9.json', authored)
    write(ROOT/'regulatory_review.json', review)
    write(ROOT/'manifest.json', manifest)
    print(VERSION + ': 62 paced videos, unchanged learning content, preserved historical editions')


if __name__ == '__main__':
    build()
