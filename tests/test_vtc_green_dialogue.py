"""E-01-2's neutral booking check stays aligned in audio, text and practice."""
import copy
import hashlib
import html
import json
import re
from unittest.mock import patch

import pytest

from elearning_native import vtc, vtc_training_web
from elearning_native.practice import grade_practice
from elearning_native.store import NativeElearningStore
from elearning_native.videos import course_videos
from tests import test_native_elearning_web as web_tests


COURSE = 'academy-vtc-e'
VERSIONS = ('20261006-vtc-v3-105h', '20261007-vtc-v4-visuals',
            '20261007-vtc-v5-annales', '20261010-vtc-v6-pedagogie')
OLD = 'media/vtc/v3/audio/e-01-2.mp3'
NEW = 'media/vtc/v8/audio/e-01-2.mp3'
ACTIVITY = 'vtc-e-01-dossier'


def original(version, course_id=COURSE):
    return json.loads((vtc.ROOT / 'courses' / course_id / (version + '.json')).read_text())


def activities(course):
    return [a for section in course['sections'] for a in section['activities']]


def dialogues(items, src):
    return [e for a in items for e in a.get('practice', {}).get('exercises', [])
            if e.get('audio') == src]


@pytest.mark.parametrize('version,count', list(zip(VERSIONS, (4, 4, 2, 1))))
def test_only_exact_dialogue_support_changes_and_all_other_47_recordings_stay(version, count):
    path = vtc.ROOT / 'courses' / COURSE / (version + '.json')
    frozen = path.read_bytes()
    before = original(version)
    # The separately tested v7 capsule repair remains exactly as deployed.
    expected = vtc._repair_english_narration(copy.deepcopy(before))
    repaired = vtc.load_bundled_course(COURSE, version)
    old = dialogues(activities(expected), OLD)
    new = dialogues(activities(repaired), NEW)
    assert len(old) == len(new) == count
    assert not dialogues(activities(repaired), OLD)
    correction = vtc._listening_correction()
    for old_ex, new_ex in zip(old, new):
        assert new_ex['transcript'] == correction['turns']
        assert new_ex['translation'] == correction['translation']
        assert new_ex['transcript'][2:] == old_ex['transcript'][2:]
        assert all('voice' not in turn for turn in new_ex['transcript'])
        for field in ('audio', 'transcript', 'translation'):
            old_ex[field] = copy.deepcopy(new_ex[field])
    expected['assets'].append(NEW)
    expected['counts']['assets'] = len(expected['assets'])
    expected = vtc._repair_video_pacing(expected)
    assert repaired == expected
    assert course_videos(repaired) == course_videos(before)
    assert vtc._course(COURSE, version) == before
    assert path.read_bytes() == frozen
    sources = {e['audio'] for a in activities(repaired)
               for e in a.get('practice', {}).get('exercises', []) if e.get('audio')}
    previous_sources = {e['audio'] for a in activities(before)
                        for e in a.get('practice', {}).get('exercises', []) if e.get('audio')}
    assert sources == (previous_sources - {OLD}) | {NEW}
    assert len([asset for asset in before['assets'] if asset.startswith('media/vtc/v3/audio/')]) == 48
    new[0]['transcript'][0]['text'] = 'local mutation'
    assert dialogues(activities(vtc.load_bundled_course(COURSE, version)), NEW)[0]['transcript'][0]['text'] != 'local mutation'


def test_earlier_courses_and_other_modules_are_unchanged():
    for module in vtc.curriculum_manifest()['modules']:
        for version in [module['version'], *module['previous_versions']]:
            if module['id'] == COURSE and version in VERSIONS:
                continue
            expected = vtc._repair_video_pacing(vtc._repair_english_narration(original(version, module['id'])))
            assert vtc.load_bundled_course(module['id'], version) == expected
            assert vtc.bundled_asset(module['id'], version, NEW) is None


@pytest.mark.parametrize('change', ['version', 'course', 'path', 'first_turn', 'last_turn'])
def test_unreviewed_course_or_dialogue_is_never_replaced(change):
    course = original(VERSIONS[-1])
    target = dialogues(activities(course), OLD)[0]
    if change == 'version':
        course['version'] = 'unreviewed'
    elif change == 'course':
        course['id'] = 'academy-vtc-a'
    elif change == 'path':
        target['audio'] = 'media/vtc/v3/audio/e-01-1.mp3'
    elif change == 'first_turn':
        target['transcript'][0]['text'] += ' Extra content.'
    else:
        target['transcript'][-1]['text'] += ' Extra content.'
    expected = copy.deepcopy(course)
    assert vtc._repair_english_listening(course) == expected


@pytest.mark.parametrize('change', ['src', 'original', 'new_turn', 'remaining_turn'])
def test_manifest_must_match_reviewed_source_and_replacement(change):
    manifest = json.loads((vtc.ROOT / 'listening_corrections_v8.json').read_text())
    replacement = manifest['dialogues']['e-01-2']
    if change == 'src':
        replacement['src'] = 'media/vtc/v8/other.mp3'
    elif change == 'original':
        replacement['original_turns'][0]['text'] = 'Different original text.'
    else:
        replacement['turns'][0 if change == 'new_turn' else 4]['text'] = 'Different replacement text.'
    with patch.object(vtc.json, 'loads', return_value=manifest):
        assert vtc._listening_correction.__wrapped__() is None


@pytest.mark.parametrize('version', VERSIONS)
def test_corrected_asset_is_authorized_without_path_or_edition_escape(version):
    assert vtc.bundled_asset(COURSE, version, NEW) == (vtc.ROOT / 'assets' / NEW).resolve()
    for name in ('media/vtc/v8/../v8/audio/e-01-2.mp3', NEW + '.other', '/'+NEW):
        assert vtc.bundled_asset(COURSE, version, name) is None
    assert vtc.bundled_asset(COURSE, 'unknown', NEW) is None
    assert vtc.bundled_asset('academy-vtc-a', version, NEW) is None


def test_asset_checksum_and_british_voices_match_correction_manifest():
    manifest = json.loads((vtc.ROOT / 'listening_corrections_v8.json').read_text())['dialogues']['e-01-2']
    assert hashlib.sha256((vtc.ROOT / 'assets' / NEW).read_bytes()).hexdigest() == manifest['sha256']
    assert [t['voice'] for t in manifest['turns']] == ['en-GB-RyanNeural', 'en-GB-SoniaNeural'] * 3
    assert 'Ms ' not in json.dumps(manifest['turns'])


@pytest.mark.parametrize('version', VERSIONS)
def test_course_and_free_training_grade_existing_answers_identically(version, tmp_path):
    before = original(version)
    repaired = vtc.load_bundled_course(COURSE, version)
    old_activity = next(a for a in activities(before) if a['id'] == ACTIVITY)
    new_activity = next(a for a in activities(repaired) if a['id'] == ACTIVITY)
    target = dialogues([old_activity], OLD)[0]
    answers = {target['id']: target['answer']}
    old_result = grade_practice(old_activity['practice'], answers, step=target['id'])
    assert grade_practice(new_activity['practice'], answers, step=target['id']) == old_result
    access = {'session_id': 's', 'trainee_id': 't', 'course_id': COURSE, 'course_version': version}
    store = NativeElearningStore(tmp_path / 'tracking.sqlite3')
    options = dict(activity_order=before['activity_order'], scored_activity_ids=[], mastery_score=80,
                   video_requirements=course_videos(before))
    store.record_practice_result(access, ACTIVITY, old_result)
    prior = store.get_progress(access, **options)
    options.update(activity_order=repaired['activity_order'], video_requirements=course_videos(repaired))
    assert store.get_progress(access, **options) == prior
    assert prior['answers'][ACTIVITY]['practice_diagnostics'][target['id']]['first_correct'] is True
    bank_path = vtc_training_web.ROOT / VERSIONS[-1] / (COURSE + '.json')
    frozen_bank = bank_path.read_bytes()
    raw_bank = json.loads(frozen_bank)
    bank = vtc_training_web._bank(repaired)
    replacements = dialogues(bank['activities'], NEW)
    assert len(replacements) == 3
    assert not dialogues(bank['activities'], OLD)
    for raw_activity in raw_bank['activities']:
        new_activity = next((a for a in bank['activities'] if a['id'] == raw_activity['id']), None)
        if not new_activity:
            continue
        for exercise in dialogues([raw_activity], OLD):
            answer = {exercise['id']: exercise['answer']}
            assert grade_practice(new_activity['practice'], answer, step=exercise['id']) == grade_practice(raw_activity['practice'], answer, step=exercise['id'])
    assert bank_path.read_bytes() == frozen_bank


def test_preview_free_training_and_authenticated_media_use_same_repaired_dialogue():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    try:
        case._admin_login()
        urls = [f'/admin/elearning/courses/{COURSE}/preview?version={VERSIONS[-1]}&activity={ACTIVITY}',
                f'/admin/elearning/vtc/entrainement/{COURSE}/{ACTIVITY}?version={VERSIONS[-1]}']
        for url in urls:
            response = case.client.get(url)
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            config = json.loads(re.search(r'<script id="vtcJourneyConfig" type="application/json">(.*?)</script>', body, re.S)[1])
            exercises = config['practice']['exercises']
            repaired = next(e for e in exercises if '/media/vtc/v8/audio/e-01-2.mp3' in e.get('audio', ''))
            assert repaired['transcript'][0]['text'].endswith('Is your booking under the name Green?')
            assert repaired['transcript'][1]['text'].startswith('Yes, it is.')
            assert 'Ms Green' not in body
            assert all('answer' not in e for e in exercises)
            audio_url = html.unescape(repaired['audio'])
            response = case.client.get(audio_url, headers={'Range': 'bytes=0-31'})
            assert response.status_code == 206 and len(response.data) == 32
            assert response.mimetype == 'audio/mpeg'
        with case.client.session_transaction() as session:
            session.pop('admin_logged_in')
        assert case.client.get(audio_url).status_code == 401
    finally:
        case.tearDown()
