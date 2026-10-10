"""New VTC people use the video edition without touching existing enrolments."""
import copy
import csv
import io
import json
import re
from unittest.mock import patch

import pytest

import app as gestion_app
from elearning_native import vtc
from elearning_native.importer import CourseImportError
from elearning_native.paths import assigned_modules, path_revision
from elearning_native.vtc_enrolments import (
    COURSE_VERSION, REQUIRED_VERSION, MARKER,
    effective_learner_session, mark_new_vtc_enrolment,
)
from tests import test_native_elearning_web as web_tests


@pytest.fixture
def raw_course_loader():
    """Selection mapping is independent of whether media rendering is finished."""
    def load(cid, version=None):
        source = COURSE_VERSION if version == REQUIRED_VERSION else version
        path = vtc.ROOT / 'courses' / cid / (source + '.json')
        if not path.is_file():
            return None
        course = json.loads(path.read_text())
        course['version'] = version
        return course
    with patch.object(vtc, 'load_bundled_course', side_effect=load):
        yield load


def module(version=COURSE_VERSION, **extra):
    return dict(course_id='academy-vtc-a', course_version=version,
                title='Mon module', required_minutes=7, **extra)


def test_old_people_are_unchanged_and_empty_versions_are_frozen():
    for version in (COURSE_VERSION, '20261006-vtc-v1', '20261006-vtc-v2', REQUIRED_VERSION, ''):
        session = {'training_type': 'VTC', 'aps_native_modules': [module(version)]}
        frozen = copy.deepcopy(session)
        result = effective_learner_session(session, {})
        assert assigned_modules(result)[0]['course_version'] == (version or COURSE_VERSION)
        assert session == frozen
        if version:
            assert result is session
    single = {'aps_native_course_id': 'academy-vtc-a', 'aps_native_course_version': ''}
    assert assigned_modules(effective_learner_session(single, {}))[0]['course_version'] == COURSE_VERSION
    assert single['aps_native_course_version'] == ''


def test_marker_is_vtc_only_idempotent_and_does_not_create_an_assignment():
    new = {}
    mark_new_vtc_enrolment({'training_type': 'Chauffeur VTC'}, new)
    assert new == {MARKER: REQUIRED_VERSION}
    untouched = {MARKER: 'historical-marker'}
    mark_new_vtc_enrolment({'training_type': 'VTC'}, untouched)
    assert untouched == {MARKER: 'historical-marker'}
    aps = {}
    mark_new_vtc_enrolment({'training_type': 'APS'}, aps)
    assert aps == {}
    for session in ({'aps_native_modules': []}, {}, {'aps_native_modules': [], 'aps_native_course_id': 'academy-vtc-a'}):
        assert effective_learner_session(session, new) is session
        assert assigned_modules(session) == []


def test_mixed_courses_and_new_order_snapshot_stay_version_pinned():
    session = {'aps_native_modules': [module(), dict(course_id='academy-aps62-01', course_version='old')]}
    result = effective_learner_session(session, {MARKER: REQUIRED_VERSION})
    assert result['aps_native_modules'][0] == {**module(), 'course_version': REQUIRED_VERSION}
    assert result['aps_native_modules'][1] == session['aps_native_modules'][1]
    assert session['aps_native_modules'][0]['course_version'] == COURSE_VERSION
    order = {'id': 'elearning-order', 'aps_native_modules': [module(REQUIRED_VERSION)]}
    assert effective_learner_session(order, {}) is order
    assert path_revision(result) != path_revision(session)


@pytest.mark.parametrize('letter', 'abcdefgh')
@pytest.mark.parametrize('old_version', ['20261006-vtc-v1', '20261006-vtc-v2', COURSE_VERSION])
def test_old_full_and_partial_selections_keep_intent_and_minutes(raw_course_loader, letter, old_version):
    cid = 'academy-vtc-'+letter
    before = raw_course_loader(cid, old_version)
    target = raw_course_loader(cid, REQUIRED_VERSION)
    old_ids = [s['id'] for s in before['sections']]
    new_ids = [s['id'] for s in target['sections']]
    for selected in (old_ids, [old_ids[-1], old_ids[1], old_ids[0]]):
        assignment = {**module(old_version), 'course_id': cid, 'section_ids': selected}
        session = {'aps_native_modules': [assignment]}
        frozen = copy.deepcopy(session)
        result = assigned_modules(effective_learner_session(session, {MARKER: REQUIRED_VERSION}))[0]
        assert result['course_version'] == REQUIRED_VERSION
        assert result['section_ids'] == (new_ids if selected == old_ids else selected)
        assert result['required_minutes'] == 7 and result['title'] == 'Mon module'
        assert session == frozen


@pytest.mark.parametrize('selected', [[], ['unknown'], ['vtc-a-01', 'vtc-a-01'], 'vtc-a-01'])
def test_invalid_historical_selections_are_not_silently_expanded(raw_course_loader, selected):
    session = {'aps_native_modules': [module('20261006-vtc-v1', section_ids=selected)]}
    frozen = copy.deepcopy(session)
    with pytest.raises(CourseImportError, match='sélection'):
        effective_learner_session(session, {MARKER: REQUIRED_VERSION})
    assert session == frozen


@pytest.fixture
def client_case():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    case.data['sessions'][0].update(
        training_type='VTC', aps_native_modules=[module(section_ids=['vtc-a-01'])])
    try:
        yield case
    finally:
        case.tearDown()


def test_creation_uses_server_marker_ignores_payload_and_transfer_preserves_it(client_case):
    case = client_case
    case._admin_login()
    old = copy.deepcopy(case.data['sessions'][0]['trainees'][0])
    # The caller cannot choose a legacy version for a new VTC person.
    with patch.object(gestion_app, 'fetch_cnapsv3_tracking_requests', return_value=([], None)):
        response = case.client.post('/api/sessions/session-aps/trainees/create', json={
            'last_name': 'Nouveau', 'first_name': 'VTC', 'send_access': False,
            MARKER: COURSE_VERSION,
        })
    assert response.status_code == 200, response.text
    created = case.data['sessions'][0]['trainees'][0]
    assert created[MARKER] == REQUIRED_VERSION
    assert case.data['sessions'][0]['trainees'][1] == old
    case.data['sessions'].append(dict(id='target', training_type='VTC', name='Destination',
                                     date_start='2000-01-01', date_end='2099-01-01',
                                     trainees=[], aps_native_modules=[module()]))
    with patch.object(gestion_app, '_force_backup_snapshot'), patch.object(gestion_app, '_transfer_trainee_billing_lines', return_value=0):
        moved = case.client.post(f'/admin/sessions/session-aps/stagiaires/{created["id"]}/transfer', data={'target_session_id':'target'})
    assert moved.status_code == 302
    assert case.data['sessions'][1]['trainees'][0][MARKER] == REQUIRED_VERSION
    with patch.object(gestion_app, '_force_backup_snapshot'), patch.object(gestion_app, '_transfer_trainee_billing_lines', return_value=0):
        moved = case.client.post('/admin/sessions/session-aps/stagiaires/trainee-1/transfer', data={'target_session_id':'target'})
    assert moved.status_code == 302
    assert MARKER not in case.data['sessions'][1]['trainees'][0]
    case.data['sessions'][0]['training_type'] = 'APS'
    with patch.object(gestion_app, 'fetch_cnapsv3_tracking_requests', return_value=([], None)):
        response = case.client.post('/api/sessions/session-aps/trainees/create', json={
            'last_name':'APS', 'first_name':'Nouveau', 'send_access':False, MARKER:REQUIRED_VERSION})
    assert response.status_code == 200
    assert MARKER not in case.data['sessions'][0]['trainees'][0]


def test_web_new_and_old_people_share_session_but_not_obligations_and_exports(client_case):
    case = client_case
    session = case.data['sessions'][0]
    session['trainees'].append(dict(id='new-person', public_token='new-token', first_name='Nouveau',
                                     last_name='Test', documents=[], **{MARKER:REQUIRED_VERSION}))
    frozen = copy.deepcopy(session)
    with case.client.session_transaction() as browser:
        browser['public_auth_public-token'] = True
        browser['public_auth_new-token'] = True
    for token, required in (('public-token', False), ('new-token', True)):
        response = case.client.get(f'/espace/{token}/elearning/academy-vtc-a')
        assert response.status_code == 200, response.text
        config = case._player_config(response)
        assert bool(config['requiredVideos']) is required
        assert config['initialRemainingSeconds'] == 7*60
        started = case._api_post(config['startUrl'], config, activity_id=config['activityId'], tab_id=token)
        assert started.status_code == 200
        completed = case._api_post(config['completeUrl'], config)
        assert completed.status_code == (409 if required else 200)
        exam = case.client.get(f'/espace/{token}/elearning/exams/vtc-a')
        assert exam.status_code == 200, exam.text
        exam_config = json.loads(re.search(r'id="apsExamConfig">(.*?)</script>', exam.text).group(1))
        assert exam_config['exam']['version'] == (REQUIRED_VERSION if required else COURSE_VERSION)
        page = response.get_data(as_text=True)
        assert 'lesson-a-01.mp4' in page
    assert session == frozen
    case._admin_login()
    live = case.client.get('/api/admin/elearning/courses/academy-vtc-a/live')
    assert live.status_code == 200, live.text
    rows = {row['trainee_id']:row for row in live.json['learners']}
    assert rows['trainee-1']['course_version'] == COURSE_VERSION
    assert rows['new-person']['course_version'] == REQUIRED_VERSION
    assert rows['trainee-1']['required_seconds'] == rows['new-person']['required_seconds'] == 420
    assert rows['trainee-1']['required_video_count'] == 0
    assert rows['new-person']['required_video_count'] == 1
    exported = case.client.get('/admin/elearning/courses/academy-vtc-a/export.csv')
    assert exported.status_code == 200
    csv_rows = list(csv.DictReader(io.StringIO(exported.get_data(as_text=True).lstrip('\ufeff')), delimiter=';'))
    assert {r['Version du cours'] for r in csv_rows} == {COURSE_VERSION, REQUIRED_VERSION}
    assert {r['Durée obligatoire (secondes)'] for r in csv_rows} == {'420'}
    assert session == frozen


def test_invalid_path_in_unrelated_session_does_not_block_other_course_tracking(client_case):
    case = client_case
    case.data['sessions'].append(dict(id='unrelated', training_type='VTC',
        trainees=[dict(id='unrelated-new', **{MARKER:REQUIRED_VERSION})],
        aps_native_modules=[{**module(), 'course_id':'academy-vtc-b', 'section_ids':['unknown']}]))
    case._admin_login()
    for url in ('/api/admin/elearning/courses/academy-vtc-a/live',
                '/admin/elearning/courses/academy-vtc-a/export.csv'):
        response = case.client.get(url)
        assert response.status_code == 200, response.text
