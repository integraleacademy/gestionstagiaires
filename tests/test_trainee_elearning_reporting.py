"""Session trainee reports use the real owner, pinned path and read-only history."""
import copy
import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

import app as host
import trainee_elearning_reporting as reporting
from elearning_native.exams import ExamStore, grade_exam
from test_elearning_exam_exports import exam
from test_elearning_reporting import tracked, database_dump
from test_vtc_elearning_activation import case


@pytest.fixture
def followup(case):
    training = case.data['sessions'][0]
    training.update(id='session-vtc', name='VTC novembre', partner_id=host.INTEGRALE_PARTNER_ID)
    person = training['trainees'][0]
    root = Path(host.PERSIST_DIR) / 'native_elearning'
    course = {'id': 'report-fixture', 'title': 'Réglementation VTC', 'mock_exam_id': 'vtc-a',
              'settings': {'mastery_score': 80}, 'sections': [
                  {'id': 'selected', 'title': 'Séquence attribuée', 'activities': [
                      {'id': 'read', 'title': 'Découvrir la réglementation', 'type': 'content', 'blocks': []},
                      {'id': 'question', 'title': 'Vérifier ses acquis', 'type': 'question', 'scored': True}]},
                  {'id': 'excluded', 'title': 'Autre sélection', 'activities': [
                      {'id': 'excluded-activity', 'title': 'NE PAS AFFICHER', 'type': 'content', 'blocks': []}]}]}
    for version in ('v1', 'v2'):
        directory = root / 'courses' / course['id'] / version
        directory.mkdir(parents=True)
        (directory / 'course.json').write_text(json.dumps({**course, 'version': version}))
    (root / 'courses' / course['id'] / 'current.json').write_text(json.dumps({'version': 'v2'}))
    person['vtc_elearning_auto']['modules'] = [{'course_id': course['id'], 'course_version': 'v1',
        'title': 'Réglementation VTC', 'section_ids': ['selected'], 'required_minutes': 1}]
    case.data['partners'] = [host._integrale_partner()]
    with case.client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role='admin')
    case.report_root = root
    case.report_order = {'id': training['id'], 'learners': [person]}
    case.report_url = f"/admin/sessions/{training['id']}/stagiaires/{person['id']}/e-learning/suivi"
    return case


def pdf_text(response):
    return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(response.data)).pages)


def test_pending_report_and_trainee_card_do_not_activate_access_or_create_tracking(followup):
    before = copy.deepcopy(followup.data)
    page = followup.client.get(followup.report_url)
    assert page.status_code == 200
    for text in ('Non commencé', '0 %', 'Retour à la fiche stagiaire', 'n’est pas encore activé',
                 'Progression par module', 'Historique des connexions', 'conditions réelles'):
        assert text in page.text
    assert followup.report_url + '/attestation.pdf' in page.text
    assert 'data-el-live-url="' + followup.report_url + '"' in page.text
    assert '/admin/organisme/e-learning/commandes/' not in page.text
    assert 'public-token' not in page.text and 'NE PAS AFFICHER' not in page.text
    assert followup.data == before
    assert not (followup.report_root / 'tracking.sqlite3').exists()
    sheet = followup.client.get(followup.report_url.removesuffix('/e-learning/suivi'))
    assert sheet.status_code == 200
    assert 'Consulter le suivi détaillé' in sheet.text and followup.report_url in sheet.text
    assert 'Modules terminés' in sheet.text and '00 h 00 min 00 s' in sheet.text
    assert not followup.data['sessions'][0]['trainees'][0]['vtc_elearning_auto']['activated_at']
    with followup.client.session_transaction() as auth:
        assert not auth.get('public_auth_public-token')


def test_existing_progress_connections_exam_copies_and_exports_use_real_session(followup):
    training = followup.data['sessions'][0]
    person = training['trainees'][0]
    person['vtc_elearning_auto']['activated_at'] = '2026-10-21T12:10:00+00:00'
    _, access, _ = tracked(followup.report_root, followup.report_order, session_id=training['id'])
    # A purchase with the same id, a different person and a different edition
    # must never be combined with the administrative trainee's history.
    tracked(followup.report_root, followup.report_order)
    tracked(followup.report_root, followup.report_order, session_id=training['id'], learner_id='other-person')
    tracked(followup.report_root, followup.report_order, session_id=training['id'], version='v2')
    exam_store = ExamStore(followup.report_root / 'tracking.sqlite3')
    for version in ('v1', 'v2'):
        paper = exam('vtc-a', version)
        result = grade_exam(paper, {q['id']: 'a' for q in paper['questions']})
        exam_store.save(training['id'], person['id'], paper, 'a' * 32, result)
    before, json_before = database_dump(followup.report_root), copy.deepcopy(followup.data)
    source, effective = reporting.source_for(training, person)
    report = reporting.ProgressReader(host).report(source, person, session_obj=effective)
    assert report['active_seconds'] == 30 and report['progress_percent'] == 100
    assert not report['complete'] and report['total_modules'] == 1
    assert len(report['connections']) == len(report['exams']) == 1
    assert report['modules'][0]['version'] == 'v1'
    copy_url = followup.report_url + '/examens/vtc-a/v1/' + 'a' * 32 + '.pdf'
    html = followup.client.get(followup.report_url)
    assert html.status_code == 200 and copy_url in html.text
    for suffix in ('/attestation.pdf', '/connexions.csv', '/examens/vtc-a/v1/' + 'a' * 32 + '.pdf'):
        response = followup.client.get(followup.report_url + suffix)
        assert response.status_code == 200
        assert 'no-store' in response.headers['Cache-Control']
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        if suffix == '/attestation.pdf':
            text = pdf_text(response)
            assert 'Référence de session : session-vtc' in text
            assert 'Référence de commande' not in text
            assert '00 h 00 min 30 s' in text and 'parcours non terminé' in text
        elif suffix == '/connexions.csv':
            assert response.text.count('Réglementation VTC') == 1
        else:
            text = pdf_text(response)
            assert 'Question archivée numéro 3' in text and '100 %' in text
            assert 'Session : session-vtc' in text and 'Commande :' not in text
    for suffix in ('/examens/vtc-a/v2/' + 'a' * 32 + '.pdf', '/examens/vtc-a/v1/' + 'b' * 32 + '.pdf'):
        assert followup.client.get(followup.report_url + suffix).status_code == 404
    assert database_dump(followup.report_root) == before and followup.data == json_before


@pytest.mark.parametrize('suffix', ['', '/attestation.pdf', '/connexions.csv', '/examens/vtc-a/v1/' + 'a' * 32 + '.pdf'])
def test_reports_and_exports_require_login_and_matching_tenant(followup, suffix):
    url = followup.report_url + suffix
    anonymous = host.app.test_client()
    assert anonymous.get(url).status_code == 302
    for values in ({'admin_role': 'partner_admin', 'partner_id': 'other-partner'},
                   {'admin_role': 'admin', 'assist_partner_id': 'other-partner'}):
        other = host.app.test_client()
        with other.session_transaction() as auth:
            auth.update(admin_logged_in=True, **values)
        assert other.get(url).status_code == 404
    assert followup.client.get(url.replace('/trainee-1/', '/unknown/')).status_code == 404


def test_historical_assignment_can_be_reviewed_after_cancellation_without_reassignment(followup):
    training = followup.data['sessions'][0]
    person = training['trainees'][0]
    training['aps_native_modules'] = person.pop('vtc_elearning_auto')['modules']
    training.update(archived=True)
    person.update(registration_cancelled=True)
    before = copy.deepcopy(followup.data)
    with followup.client.session_transaction() as auth:
        auth['admin_role'] = 'viewer'
    assert followup.client.get(followup.report_url).status_code == 200
    assert followup.data == before
    training['aps_native_modules'] = []
    assert followup.client.get(followup.report_url).status_code == 404
