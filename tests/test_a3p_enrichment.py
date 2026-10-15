import copy
import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from elearning_native import a3p_v3 as a3p  # immutable v3 regression coverage
from elearning_native.content_audit import audit_course
from elearning_native.paths import project_course
from elearning_native.practice import grade_practice, public_practice
from elearning_native.store import NativeElearningStore
from tests.test_shared_lesson_timing import case


def test_every_distance_lesson_has_specific_content_and_server_graded_cases():
    refs, decisions = set(), 0
    for cid in a3p.curriculum_ids():
        course = a3p.load_bundled_course(cid)
        old = a3p.load_bundled_course(cid, a3p.previous.VERSION)
        assert course['version'] != old['version']
        for section, prior in zip(course['sections'], old['sections']):
            if section['delivery'] != 'distance':
                assert section == prior
                continue
            activities = section['activities']
            refs.add(activities[0]['a3p']['ref'])
            assert len(activities[0]['a3p']['pages']) >= len(prior['activities'][0]['a3p']['pages']) + 2
            assert section['planned_minutes'] == sum(a['planned_minutes'] for a in activities)
            practice = activities[1]['practice']
            answers = {ex['id']: ex['answer'] for ex in practice['exercises']}
            assert grade_practice(practice, answers)['correct']
            for ex in practice['exercises']:
                wrong = dict(answers)
                wrong[ex['id']] = next(o['id'] for o in ex['options'] if o['id'] != ex['answer'])
                assert not grade_practice(practice, wrong)['correct']
                assert ex['context'] and ex['explanation']
            public = public_practice(practice)
            assert all('answer' not in ex and 'explanation' not in ex for ex in public['exercises'])
            assert all(ex['kind'] == 'single' for ex in public['exercises'])
            assert not any(a.get('workbook') or a.get('production') for a in activities)
            decisions += len(practice['exercises'])
    assert refs == set(a3p._bank())
    assert (len(refs), decisions) == (57, 264)
    assert len({d['title'] for d in a3p._bank().values()}) == 57


def test_estimates_do_not_fill_legal_hours_or_award_time():
    reports = []
    for cid in a3p.curriculum_ids():
        course = a3p.load_bundled_course(cid)
        projected = project_course(course, {'required_minutes': course['required_minutes']})
        report = audit_course(projected)
        assert report['missing_plans'] == 0
        assert report['planned_minutes'] == course['planned_minutes']
        assert report['calibration']['measured'] is False
        assert report['gap_minutes'] == max(0, report['required_minutes'] - report['planned_minutes'])
        if report['gap_minutes']:
            assert report['priority'] == 'Enrichissement et calibrage nécessaires'
            assert any('Écart de contenu estimé' in issue for issue in report['issues'])
        assert report['video_minutes'] == 0
        reports.append(report)
    assert sum(r['required_minutes'] for r in reports) == 9450
    assert sum(r['planned_minutes'] for r in reports) < 9450
    assert sum(r['interactive_items'] for r in reports) == 264


def test_previous_editions_are_still_loadable_and_return_independent_copies():
    for cid in a3p.curriculum_ids():
        for version in (a3p.legacy.VERSION, a3p.previous.VERSION):
            assert a3p.load_bundled_course(cid, version) == a3p.previous.load_bundled_course(cid, version)
        copy_of_course = a3p.load_bundled_course(cid)
        copy_of_course['sections'].clear()
        assert a3p.load_bundled_course(cid)['sections']
    assert a3p.load_bundled_course('academy-a3p-02', 'unknown') is None


def test_all_new_workshops_render_and_preview_uses_server_correction(case):
    case._admin_login()
    with case.client.session_transaction() as session:
        csrf = session['native_elearning_csrf'] if 'native_elearning_csrf' in session else None
    total = 0
    for cid in a3p.curriculum_ids():
        course = a3p.load_bundled_course(cid)
        for section in course['sections']:
            if section['delivery'] != 'distance':
                continue
            activity = section['activities'][1]
            url = '/admin/elearning/courses/' + cid + '/preview'
            with patch('elearning_native.web.NativeElearningStore', side_effect=AssertionError('preview must not track')):
                page = case.client.get(url, query_string={'version': a3p.VERSION, 'activity': activity['id']})
            assert page.status_code == 200
            assert '<textarea' not in page.text and 'contenteditable=' not in page.text
            public = json.loads(re.search(r'<script id="apsPracticeConfig" type="application/json">(.*?)</script>', page.text, re.S).group(1))
            assert len(public['practice']['exercises']) == len(activity['practice']['exercises'])
            assert all('answer' not in ex and 'explanation' not in ex for ex in public['practice']['exercises'])
            config = json.loads(re.search(r'<script id="nativePreviewConfig" type="application/json">(.*?)</script>', page.text, re.S).group(1))
            with case.client.session_transaction() as session:
                csrf = session['native_elearning_csrf']
            ex = activity['practice']['exercises'][0]
            payload = {'practice_step': ex['id'], 'practice_answers': {ex['id']: ex['answer']}}
            assert case.client.post(config['answerUrl'], json=payload).status_code == 403
            response = case.client.post(config['answerUrl'], json=payload, headers={'X-Elearning-CSRF': csrf})
            assert response.status_code == 200 and response.json['correct']
            total += 1
    assert total == 57
    assert not (case.persist_dir / 'native_elearning/tracking.sqlite3').exists()


def test_learner_cannot_complete_cases_with_wrong_answers_and_resume_is_preserved(case):
    course = a3p.load_bundled_course('academy-a3p-02')
    case.data['sessions'][0].update(training_type='A3P', aps_native_modules=[{
        'course_id': course['id'], 'course_version': course['version'], 'required_minutes': course['required_minutes']}])
    case._public_login()
    store = NativeElearningStore(case.persist_dir / 'native_elearning/tracking.sqlite3')
    access = {'session_id': 'session-aps', 'trainee_id': 'trainee-1', 'course_id': course['id'], 'course_version': course['version']}
    lesson, activity = course['sections'][0]['activities'][:2]
    # Fixture: a reading already completed legitimately, isolate the case API.
    store.complete_activity(access, lesson['id'], activity_order=course['activity_order'], scored_activity_ids=[], mastery_score=80)
    page = case.client.get('/espace/public-token/elearning/' + course['id'], query_string={'activity': activity['id']})
    assert page.status_code == 200
    config = case._player_config(page)
    answers = {ex['id']: ex['answer'] for ex in activity['practice']['exercises']}
    bad = copy.deepcopy(answers)
    ex = activity['practice']['exercises'][0]
    bad[ex['id']] = next(o['id'] for o in ex['options'] if o['id'] != ex['answer'])
    assert case._api_post(config['completeUrl'], config, practice_answers=bad).status_code == 400
    resumed = case.client.get('/espace/public-token/elearning/' + course['id'], query_string={'activity': activity['id']})
    public = json.loads(re.search(r'<script id="apsPracticeConfig" type="application/json">(.*?)</script>', resumed.text, re.S).group(1))
    assert public['savedAnswers'] == bad
    response = case._api_post(config['completeUrl'], config, practice_answers=answers)
    assert response.status_code == 200
    assert activity['id'] in response.json['progress']['completed_activity_ids']
    assert response.json['progress']['active_seconds'] == 0
    assert not response.json['progress']['module_complete']


def test_old_assigned_version_retains_its_resource_route(case):
    course = a3p.load_bundled_course('academy-a3p-02', a3p.previous.VERSION)
    case.data['sessions'][0].update(training_type='A3P', aps_native_modules=[{
        'course_id': course['id'], 'course_version': course['version'], 'required_minutes': course['required_minutes']}])
    case._public_login()
    response = case.client.get('/espace/public-token/elearning/' + course['id'] + '/ressources', query_string={'activity': 'a3p-02-cas'})
    assert response.status_code == 200
    assert 'Ressources complémentaires' in response.text
    assert 'nativeElearningConfig' not in response.text


def test_current_catalog_and_audit_disclose_planned_and_measured_time(case):
    case._admin_login()
    catalog = case.client.get('/admin/elearning/a3p')
    assert catalog.status_code == 200
    assert '157 h 30' in catalog.text
    assert '160 séquences' in catalog.text and 'temps réellement suivi' in catalog.text
    response = case.client.get('/admin/elearning/calibrage/contenus')
    assert response.status_code == 200
    assert 'sans essai apprenant' in response.text
    assert 'minutes' in response.text
