"""Publish the reviewed APS edition while preserving all assigned versions.

All authored media must exist before changing the catalogue. The new practical
productions are coached work with self-review, never automatically marked skills.
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
from scripts.aps62_v10.content_fixes import apply_course as apply_fixes
from scripts.aps62_v10.assessment import apply_course as apply_assessment, apply_exam
from scripts.aps62_v10.practical_cases import apply_practical_cases, PRODUCTIONS

ROOT = REPO/'elearning_native/aps62'
VERSION = '20261010-aps62-v10'
PREVIOUS = '20261007-aps62-v9'


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
    assert manifest['version'] == PREVIOUS, 'Build from the reviewed v9 edition'
    authored = authored_videos()
    videos = read(ROOT/'video_manifest_v8.json')
    assert set(videos) == set(authored) and len(videos) == 62, 'All 62 completed videos are required'
    for sid, video in videos.items():
        assert video['duration_seconds'] >= 300 and video['narration_seconds'] >= 300
        assert video['transcript'] == authored[sid]['transcript']
        assert video['field_demonstrations'] and video['render_revision'] == 8
        for key, ext in (('src','mp4'),('captions','vtt'),('poster','jpg')):
            assert video[key] == f'media/aps62/v8/{sid}.{ext}'
            assert (ROOT/'assets'/video[key]).is_file()
    staged = {}
    practice_count = production_count = 0
    for module in manifest['modules']:
        course = read(ROOT/'courses'/module['id']/(PREVIOUS+'.json'))
        original_order = copy.deepcopy(course['activity_order'])
        course = apply_practical_cases(apply_fixes(apply_assessment(course)))
        course['version'] = course['interaction_revision'] = VERSION
        course['reading_revision'] = 'applied-cases-v4'
        for section in course['sections']:
            sid = section['id']
            old_total = sum(a['planned_minutes'] for a in section['activities'])
            for activity in section['activities']:
                if activity.get('practice'):
                    activity['practice']['revision'] = VERSION
                    practice_count += 1
                if activity.get('production'):
                    production_count += 1
                    activity['academy'] = {'kind':'transfer'}
                    minutes = int(activity['production']['estimated_minutes'])
                    difference = minutes - activity['planned_minutes']
                    activity['planned_minutes'] = minutes
                    section['activities'][0]['planned_minutes'] -= difference
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
            section['activities'][0]['academy']['pacing'] = [dict(label=a['title'], minutes=a['planned_minutes']) for a in section['activities']]
        assets = set()
        def collect(value):
            if isinstance(value, str) and value.startswith('media/aps62/'):
                assets.add(value)
            elif isinstance(value, dict):
                for key, child in value.items():
                    if key != 'assets':
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(course)
        course['assets'] = sorted(assets)
        course['counts']['interactive_workshops'] = sum(bool(a.get('practice')) for s in course['sections'] for a in s['activities'])
        course['counts']['productions'] = sum(bool(a.get('production')) for s in course['sections'] for a in s['activities'])
        assert all((ROOT/'assets'/p).is_file() for p in assets), sorted(p for p in assets if not (ROOT/'assets'/p).is_file())
        assert course['activity_order'] == original_order
        assert sum(a['planned_minutes'] for s in course['sections'] for a in s['activities']) == course['planned_minutes']
        staged[ROOT/'courses'/module['id']/(VERSION+'.json')] = course
        module['previous_versions'] = list(dict.fromkeys([*module.get('previous_versions', []), PREVIOUS]))
        module['version'] = VERSION
    for path in (ROOT/'exams'/PREVIOUS).glob('*.json'):
        exam = apply_exam(read(path))
        exam['version'] = VERSION
        staged[ROOT/'exams'/VERSION/path.name] = exam
    assert len(staged) == 31 and production_count == len(PRODUCTIONS) == 10 and practice_count == 132
    manifest.update(version=VERSION, interaction_revision=VERSION, production_count=production_count,
                    workbook_count=0, interactive_workshop_count=practice_count)
    manifest['exam_versions'] = list(dict.fromkeys([*manifest.get('exam_versions', []), VERSION]))
    manifest['visual_learning'].update(
        long_videos_published=True, field_demonstrations=62, demonstrated_scenes=310,
        targeted_remediation=True, reviewed_questions=True, independent_final_exam=True,
        practical_productions=production_count, authored_on='2026-10-10')
    review = read(ROOT/'regulatory_review.json')
    review['edition'] = VERSION
    for path, value in staged.items():
        write(path, value)
    assert historical_digest() == before
    write(ROOT/'video_scripts_v8.json', authored)
    write(ROOT/'regulatory_review.json', review)
    write(ROOT/'manifest.json', manifest)
    print(VERSION+': 15 modules, 62 demonstrated videos, 10 individual productions, preserved historical content')


if __name__ == '__main__':
    build()
