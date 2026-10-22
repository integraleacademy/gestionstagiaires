"""November APS sessions use one curriculum in the portal, tracking and reports."""
import copy
import datetime as dt
import io
import json
import re
import time
from unittest.mock import patch

import pytest
from pypdf import PdfReader

import app as host
import elearning_orders
import trainee_elearning_reporting as reporting
from elearning_native import aps_enrolments
from elearning_native.academy import load_bundled_course
from elearning_native.exams import ExamStore, grade_exam, load_exam
from elearning_native.paths import assigned_modules
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_enrolments import effective_learner_session
from tests import test_native_elearning_web as web_tests


@pytest.mark.parametrize('changes,eligible', [
    ({}, True), ({'date_start': '2026-11-02'}, False),
    ({'date_start': '2027-01-01'}, True), ({'aps_elearning_enabled': False}, False),
    ({'date_start': ''}, False), ({'date_start': 'invalid'}, False),
    ({'training_type': 'A3P'}, False), ({'training_type': 'VTC'}, False),
    ({'training_type': 'MAC APS'}, False), ({'training_type': 'SSIAP 1'}, False),
    ({'training_type': 'APS + SSIAP 1'}, True), ({'id': 'el-purchase'}, False),
    ({'training_type': '', 'type_formation': 'APS', 'date_start': '', 'date_debut': '2026-11-03'}, True),
])
def test_inclusive_start_date_and_opt_in_without_rewriting_history(changes, eligible):
    training = {'id': 'session', 'training_type': 'APS', 'date_start': '2026-11-03',
                'aps_elearning_enabled': True, 'aps_native_modules': [], **changes}
    before = copy.deepcopy(training)
    effective = effective_learner_session(training, {})
    assert aps_enrolments.is_native_aps_session(training) is eligible
    assert len(assigned_modules(effective)) == (15 if eligible else 0)
    assert training == before
    if eligible:
        assert assigned_modules(effective) == elearning_orders.curriculum('aps')
        assert sum(m['required_minutes'] for m in assigned_modules(effective)) == 62 * 60
        effective['aps_native_modules'][0]['required_minutes'] = 0
        assert aps_enrolments.modules()[0]['required_minutes'] == 240
    else:
        assert effective is training


@pytest.fixture
def aps_case():
    case = web_tests.NativeElearningWebTests(methodName='runTest')
    case.setUp()
    training = case.data['sessions'][0]
    training.update(name='APS novembre', date_start='2026-11-03', partner_id=host.INTEGRALE_PARTNER_ID)
    person = training['trainees'][0]
    person['aps_elearning_login'] = 'https://ancienne-plateforme.example.test'
    person['aps_elearning_tracking'] = {'file': 'old-digiforma.pdf', 'connection_log_total': '70 heures'}
    case.data['partners'] = [host._integrale_partner()]
    case.report_url = f"/admin/sessions/{training['id']}/stagiaires/{person['id']}/e-learning/suivi"
    try:
        yield case
    finally:
        case.tearDown()


def today(monkeypatch, value):
    class ClockDate(dt.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(value)
    monkeypatch.setattr(dt, 'date', ClockDate)


def test_portal_and_player_open_on_first_day_and_keep_learner_authentication(aps_case, monkeypatch):
    aps_case._public_login()
    today(monkeypatch, '2026-11-02')
    portal = aps_case.client.get('/espace/public-token')
    assert portal.status_code == 200 and 'Accès disponible le 03/11/2026' in portal.text
    assert 'ancienne-plateforme' not in portal.text
    assert aps_case.client.get('/espace/public-token/elearning').status_code == 403
    today(monkeypatch, '2026-11-03')
    portal = aps_case.client.get('/espace/public-token')
    assert 'Accéder à mon parcours APS' in portal.text
    assert 'apsElearningAttendance' not in portal.text
    path = aps_case.client.get('/espace/public-token/elearning')
    assert path.status_code == 200 and 'Le cadre de la sécurité privée' in path.text
    first = aps_enrolments.modules()[0]
    player = aps_case.client.get('/espace/public-token/elearning/' + first['course_id'])
    config = aps_case._player_config(player)
    assert config['accessToken']
    baseline = time.time()
    with patch('elearning_native.store.time.time', return_value=baseline):
        started = aps_case._api_post(config['startUrl'], config, tab_id='aps-browser', activity_id=config['activityId'])
    assert started.status_code == 200, started.text
    for epoch in (baseline, baseline + 15, baseline + 30):
        with patch('elearning_native.store.time.time', return_value=epoch):
            heartbeat = aps_case._api_post(config['heartbeatUrl'], config,
                tracking_session_id=started.json['tracking_session_id'], activity_id=config['activityId'],
                visible=True, focused=True, recent_activity=True, media_playing=False,
                lesson_page_id=config['lessonPages'][0]['id'])
        assert heartbeat.status_code == 200, heartbeat.text
    source, effective = reporting.source_for(aps_case.data['sessions'][0], aps_case.data['sessions'][0]['trainees'][0])
    report = reporting.ProgressReader(host).report(source, aps_case.data['sessions'][0]['trainees'][0], session_obj=effective)
    assert report['active_seconds'] == 30
    # A second module is still subject to the existing sequential progression.
    assert aps_case.client.get('/espace/public-token/elearning/' + aps_enrolments.modules()[1]['course_id']).status_code == 403
    with aps_case.client.session_transaction() as auth:
        auth.clear()
    assert aps_case.client.get('/espace/public-token/elearning').status_code == 302
    aps_case._public_login()
    aps_case.data['sessions'][0]['aps_elearning_enabled'] = False
    assert aps_case.client.get('/espace/public-token/elearning').status_code == 403


def test_aps_followup_before_start_and_session_editor_show_same_complete_path(aps_case):
    aps_case._admin_login()
    before = copy.deepcopy(aps_case.data)
    report = aps_case.client.get(aps_case.report_url)
    assert report.status_code == 200
    for value in ('Progression par module', 'Historique des connexions', 'Non commencé',
                  '62 h 00 min 00 s', '#apsElearningFollowup', 'Voir l’attestation PDF'):
        assert value in report.text
    assert aps_case.data == before
    assert not (aps_case.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists()
    sheet = aps_case.client.get(aps_case.report_url.removesuffix('/e-learning/suivi'))
    assert sheet.status_code == 200 and 'id="apsElearningFollowup"' in sheet.text
    assert aps_case.report_url in sheet.text and 'Consulter le suivi détaillé' in sheet.text
    assert 'id="editApsElearningLogin"' not in sheet.text and 'id="apsElearningTrackingSection"' not in sheet.text
    builder = aps_case.client.get('/admin/sessions/session-aps/elearning')
    config = json.loads(re.search(r'<script id="nativePathConfig" type="application/json">(.*?)</script>', builder.text, re.S)[1])
    assert config['readOnly'] and len(config['modules']) == 15
    response = aps_case.client.post(config['saveUrl'], json={'modules': [], 'revision': config['revision'], 'title': 'Other'},
                                    headers={'X-Elearning-CSRF': config['csrfToken']})
    assert response.status_code == 409


def test_aps_followup_reports_only_own_actual_time_exams_and_exports(aps_case):
    training, person = aps_case.data['sessions'][0], aps_case.data['sessions'][0]['trainees'][0]
    module = aps_enrolments.modules()[0]
    course = load_bundled_course(module['course_id'], module['course_version'])
    activity = course['activity_order'][0]
    root = aps_case.persist_dir / 'native_elearning'
    store = NativeElearningStore(root / 'tracking.sqlite3')
    for learner in (person['id'], 'other-person'):
        access = {'session_id': training['id'], 'trainee_id': learner,
                  'course_id': course['id'], 'course_version': course['version']}
        tracking = store.start_tracking(access, tab_id='test-tab', activity_id=activity, now_epoch=1000)
        for epoch in (1000, 1015, 1030):
            store.heartbeat(access, tracking['tracking_session_id'], activity_id=activity,
                            visible=True, focused=True, recent_activity=True, media_playing=False, now_epoch=epoch)
    exams = ExamStore(root / 'tracking.sqlite3')
    for version in (module['course_version'], '20261010-aps62-v11'):
        paper = load_exam('module-01', version)
        result = grade_exam(paper, {q['id']: q['answer'] for q in paper['questions']})
        exams.save(training['id'], person['id'], paper, 'a' * 32, result)
    source, effective = reporting.source_for(training, person)
    report = reporting.ProgressReader(host).report(source, person, session_obj=effective)
    assert report['active_seconds'] == 30 and not report['complete']
    assert report['total_modules'] == 15 and report['required_seconds'] == 62 * 3600
    assert len(report['connections']) == len(report['exams']) == 1
    aps_case._admin_login()
    for suffix in ('/attestation.pdf', '/connexions.csv', f"/examens/module-01/{module['course_version']}/{'a' * 32}.pdf"):
        response = aps_case.client.get(aps_case.report_url + suffix)
        assert response.status_code == 200
        if suffix.endswith('.pdf'):
            assert PdfReader(io.BytesIO(response.data)).pages
    assert aps_case.client.get(aps_case.report_url + f"/examens/module-01/20261010-aps62-v11/{'a' * 32}.pdf").status_code == 404
    with aps_case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other-partner')
    assert aps_case.client.get(aps_case.report_url).status_code == 404
