"""Publish reviewed questions, targeted practice and demonstrated long videos.

The previous edition is immutable. This builder requires all real video assets
before updating the catalogue; sessions already pinned to v8 keep that edition.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts.aps62_v9.field_videos import courses as authored_videos
from scripts.aps62_v9.questions import apply_questions, apply_exam
from scripts.aps62_v9.remediation import apply_remediation

ROOT = REPO/'elearning_native/aps62'
VERSION = '20261007-aps62-v9'
PREVIOUS = '20261007-aps62-v8'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def historical_digest():
    files = sorted((ROOT/'courses').glob('*/*.json')) + sorted((ROOT/'exams').glob('*/*.json'))
    h = hashlib.sha256()
    for p in files:
        if VERSION not in str(p):
            h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+p.read_bytes()+b'\0')
    return h.hexdigest()


def build():
    if any((ROOT/'courses').glob('*/'+VERSION+'.json')) or (ROOT/'exams'/VERSION).exists():
        raise ValueError('Existing published editions are immutable: '+VERSION)
    before = historical_digest()
    manifest = read(ROOT/'manifest.json')
    assert manifest['version'] == PREVIOUS, 'Build from the reviewed v8 edition'
    authored = authored_videos()
    videos = read(ROOT/'video_manifest_v7.json')
    assert set(videos) == set(authored) and len(videos) == 62, 'All 62 completed videos are required'
    for sid, video in videos.items():
        assert video['duration_seconds'] >= 300 and video['narration_seconds'] >= 300
        assert video['transcript'] == authored[sid]['transcript']
        assert video['field_demonstrations'] and video['render_revision'] == 7
        for key, ext in (('src','mp4'),('captions','vtt'),('poster','jpg')):
            assert video[key] == f'media/aps62/v7/{sid}.{ext}'
            assert (ROOT/'assets'/video[key]).is_file()
    # Prepare everything in memory. A missing editorial entry cannot result in
    # a partially changed catalogue or a half-published set of course versions.
    staged = {}
    for module in manifest['modules']:
        course = read(ROOT/'courses'/module['id']/(PREVIOUS+'.json'))
        original_order = copy.deepcopy(course['activity_order'])
        course = apply_questions(course)
        course = apply_remediation(course)
        course['version'] = course['interaction_revision'] = VERSION
        course['reading_revision'] = 'field-guided-v3'
        for section in course['sections']:
            sid = section['id']
            old_total = sum(a['planned_minutes'] for a in section['activities'])
            for activity in section['activities']:
                if activity.get('practice'):
                    activity['practice']['revision'] = VERSION
                for block in activity.get('blocks', []):
                    if block.get('video'):
                        block['video'].update(videos[sid])
                        minutes = math.ceil(videos[sid]['duration_seconds']/60)+1
                        difference = minutes-activity['planned_minutes']
                        activity['planned_minutes'] = minutes
                        section['activities'][0]['planned_minutes'] -= difference
                academy = activity.get('academy', {})
                if academy.get('kind') == 'memory':
                    academy.update(transcript=videos[sid]['transcript'], voice=videos[sid]['voice'])
            assert all(a['planned_minutes'] > 0 for a in section['activities']), sid
            assert sum(a['planned_minutes'] for a in section['activities']) == old_total, sid
            lesson = section['activities'][0]['academy']
            lesson['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
        assets = set()
        def collect(value):
            if isinstance(value, str) and value.startswith('media/aps62/'):
                assets.add(value)
            elif isinstance(value, dict):
                for k, child in value.items():
                    if k != 'assets':
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(course)
        course['assets'] = sorted(assets)
        assert all((ROOT/'assets'/p).is_file() for p in assets)
        assert course['activity_order'] == original_order
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']) == course['planned_minutes']
        staged[ROOT/'courses'/module['id']/(VERSION+'.json')] = course
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), PREVIOUS]))
        module['version'] = VERSION
    for path in (ROOT/'exams'/PREVIOUS).glob('*.json'):
        exam = apply_exam(read(path))
        exam['version'] = VERSION
        staged[ROOT/'exams'/VERSION/path.name] = exam
    assert len(staged) == 31
    manifest.update(version=VERSION, interaction_revision=VERSION)
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    manifest['visual_learning'].update(
        long_videos_published=True, field_demonstrations=62, demonstrated_scenes=310,
        targeted_remediation=True, reviewed_questions=True, authored_on='2026-10-07')
    review = read(ROOT/'regulatory_review.json')
    review['edition'] = VERSION
    for path, value in staged.items():
        write(path, value)
    assert historical_digest() == before
    write(ROOT/'video_scripts_v7.json', authored)
    write(ROOT/'regulatory_review.json', review)
    write(ROOT/'manifest.json', manifest)
    print(VERSION+': 15 modules, 62 demonstrated videos, preserved historical content')


if __name__ == '__main__':
    build()
