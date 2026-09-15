import copy
import io
from pathlib import Path
from unittest.mock import Mock

import pytest

import app as gestion
import test_aps_elearning as existing
from digiforma_fixtures import attendance_pdf

URL = '/admin/sessions/S-APS/aps-elearning/digiforma/bulk-upload'


@pytest.fixture
def context(monkeypatch, tmp_path):
    data = existing.ApsElearningTests._data('2026-07-23')
    data['sessions'][0]['date_end'] = '2026-09-03'
    trainees = data['sessions'][0]['trainees']
    trainees.append(dict(trainees[0], id='T-BOB', first_name='Bob', last_name='DUPONT',
                         email='bob@example.test', public_token='BOB-TOKEN', documents=[]))
    monkeypatch.setattr(gestion, 'load_data', lambda: data)
    save = Mock()
    monkeypatch.setattr(gestion, 'save_data', save)
    monkeypatch.setattr(gestion, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(gestion, 'UPLOADS_DIR', str(tmp_path / 'uploads'))
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin', admin_username='admin@example.test')
        session['public_auth_PUBLIC-TOKEN'] = True
        session['public_auth_BOB-TOKEN'] = True
    return client, data, trainees, save


def upload(client, pdf=None, filename='releve.pdf', processed=()):
    return client.post(URL, data={
        'digiforma_pdf': (io.BytesIO(pdf if pdf is not None else attendance_pdf()), filename),
        'processed_trainee_ids': list(processed),
    }, headers={'Accept': 'application/json'})


def test_grouped_selection_updates_each_public_space_despite_bad_pdf(context):
    client, data, trainees, save = context
    first = upload(client, attendance_pdf(connection_total='44 heures, 54 minutes et 51 secondes',
                                        effective_duration='67 heures et 19 minutes'))
    assert first.status_code == 200
    assert first.json['duration'] == '44 h 54'
    assert first.json['attendance_rate'] == '72,4 %'
    assert first.json['trainee_id'] == 'T-APS'
    assert upload(client, b'not a pdf', processed=['T-APS']).status_code == 400
    second = upload(client, attendance_pdf(trainee_name='DUPONT BOB', email='bob@example.test',
                                         connection_total='31 heures'), processed=['T-APS'])
    assert second.status_code == 200
    assert second.json['trainee_id'] == 'T-BOB'
    assert second.json['attendance_rate'] == '50 %'
    assert save.call_count == 2
    for trainee in trainees:
        tracking = trainee['aps_elearning_tracking']
        assert Path(gestion._detokenize_path(tracking['source_file'])).is_file()
        assert Path(gestion._require_aps_elearning_report_file(tracking)).is_file()
    public = client.get('/espace/PUBLIC-TOKEN').text
    section = public.split('id="apsElearningAttendance"', 1)[1].split('</section>', 1)[0]
    assert '44 h 54' in section and '/ 62 heures' in section and '72,4 %' in section
    assert '67 heures' not in section and '100 %</strong>' not in section
    assert '31 h 00' in client.get('/espace/BOB-TOKEN').text


@pytest.mark.parametrize('total, rate, duration', [
    ('44h54m51s', '72,4 %', '44 h 54'),
    ('0 seconde', '0 %', '0 h 00'),
    ('62 heures', '99,9 %', '62 h 00'),
    ('62 heures et 1 seconde', '100 %', '62 h 00'),
    ('80 heures', '100 %', '80 h 00'),
    ('', 'Non renseigné', 'Non renseignée'),
])
def test_existing_imports_show_journal_metrics_without_reimport(context, total, rate, duration):
    client, data, trainees, save = context
    trainees[0]['aps_elearning_tracking'] = existing.ApsElearningTests._complete_tracking(
        connection_log_total=total, completion_rate=100, effective_duration='67 heures et 19 minutes')
    response = client.get('/espace/PUBLIC-TOKEN')
    assert response.status_code == 200
    section = response.text.split('id="apsElearningAttendance"', 1)[1].split('</section>', 1)[0]
    assert rate in section and duration in section
    assert '67 heures' not in section
    assert ('<progress' in section) == bool(total)


def test_import_button_is_available_only_for_writable_aps_elearning(context):
    client, data, trainees, save = context
    response = client.get('/admin/sessions/S-APS/trainees')
    assert response.status_code == 200
    assert 'id="btnImportDigiforma"' in response.text
    assert 'accept=".pdf,application/pdf" multiple' in response.text
    assert URL in response.text
    with client.session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert 'id="btnImportDigiforma"' not in client.get('/admin/sessions/S-APS/trainees').text
    assert upload(client).status_code == 403
    with client.session_transaction() as session:
        session.clear()
    unauthorized = upload(client)
    assert unauthorized.status_code == 302
    assert '/admin/login' in unauthorized.location


@pytest.mark.parametrize('training_type, enabled', [('VTC', True), ('APS', False)])
def test_bulk_route_rejects_ineligible_sessions(context, training_type, enabled):
    client, data, trainees, save = context
    data['sessions'][0].update(training_type=training_type, aps_elearning_enabled=enabled)
    assert upload(client).status_code == 404
    save.assert_not_called()


def test_no_relevant_import_means_no_attendance_block(context):
    client, data, trainees, save = context
    assert 'id="apsElearningAttendance"' not in client.get('/espace/PUBLIC-TOKEN').text


@pytest.mark.parametrize('name, email', [
    ('', 'alice.martin@example.test'),
    ('ALICE MARTIN DUPONT', 'alice.martin@example.test'),
    ('ALICE MARTIN', 'bob@example.test'),
    ('PERSONNE INCONNUE', 'unknown@example.test'),
])
def test_missing_conflicting_or_partial_identity_never_writes(context, name, email):
    client, data, trainees, save = context
    before = copy.deepcopy(trainees)
    result = upload(client, attendance_pdf(trainee_name=name, email=email))
    assert result.status_code == 400
    assert trainees == before
    save.assert_not_called()


def test_homonyms_require_unique_email_within_session(context):
    client, data, trainees, save = context
    trainees.append(dict(trainees[0], id='T-OTHER-ALICE', email='other@example.test'))
    assert upload(client, attendance_pdf(email='unknown@example.test')).status_code == 400
    save.assert_not_called()
    accepted = upload(client, attendance_pdf(email='other@example.test'))
    assert accepted.json['trainee_id'] == 'T-OTHER-ALICE'
    assert 'aps_elearning_tracking' not in trainees[0]


def test_matching_is_scoped_to_selected_session(context):
    client, data, trainees, save = context
    bob = trainees.pop()
    data['sessions'].append(dict(data['sessions'][0], id='S-OTHER', trainees=[bob]))
    assert upload(client, attendance_pdf(trainee_name='BOB DUPONT', email='bob@example.test')).status_code == 400
    save.assert_not_called()


def test_repeated_pdf_preserves_tracking_and_signature(context):
    client, data, trainees, save = context
    pdf = attendance_pdf()
    assert upload(client, pdf).status_code == 200
    trainees[0]['aps_elearning_signature'] = {'status': 'done', 'signature_request_id': 'SIGNED'}
    before = copy.deepcopy(trainees[0])
    save.reset_mock()
    response = upload(client, pdf)
    assert response.json['status'] == 'unchanged'
    assert trainees[0] == before
    save.assert_not_called()


@pytest.mark.parametrize('signature_status', ['ongoing', 'done'])
def test_bulk_never_replaces_signed_or_pending_dossier(context, signature_status):
    client, data, trainees, save = context
    trainees[0]['aps_elearning_signature'] = {'status': signature_status, 'signature_request_id': 'REQUEST'}
    before = copy.deepcopy(trainees[0])
    assert upload(client).status_code == 400
    assert trainees[0] == before
    save.assert_not_called()


def test_second_report_for_same_person_in_one_selection_is_rejected(context):
    client, data, trainees, save = context
    assert upload(client, processed=['T-APS']).status_code == 400
    save.assert_not_called()


def test_invalid_file_or_multiple_files_cannot_replace_tracking(context):
    client, data, trainees, save = context
    for pdf, filename in [(b'broken', 'broken.pdf'), (attendance_pdf(complete=False), 'incomplete.pdf'),
                          (attendance_pdf(), 'report.txt')]:
        assert upload(client, pdf, filename).status_code == 400
    result = client.post(URL, data={'digiforma_pdf': [
        (io.BytesIO(attendance_pdf()), 'one.pdf'), (io.BytesIO(attendance_pdf()), 'two.pdf'),
    ]}, headers={'Accept': 'application/json'})
    assert result.status_code == 400
    save.assert_not_called()


def test_failed_save_keeps_old_dossier_and_cleans_new_files(context, tmp_path):
    client, data, trainees, save = context
    assert upload(client).status_code == 200
    before = copy.deepcopy(trainees[0])
    files_before = sorted(p for p in tmp_path.rglob('*') if p.is_file())
    save.side_effect = OSError('storage unavailable')
    result = upload(client, attendance_pdf(connection_total='70 heures'))
    assert result.status_code == 500
    assert trainees[0] == before
    assert sorted(p for p in tmp_path.rglob('*') if p.is_file()) == files_before
