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
    monkeypatch.setattr(gestion, 'load_data', lambda **kwargs: data)
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


def test_public_completion_requires_all_three_objectives_and_follows_reimports(context):
    client, data, trainees, save = context
    for paths, evaluations, duration, rate, complete in [
        (7, 8, '63 heures', '95,8 %', False),
        (8, 7, '63 heures', '95,8 %', False),
        (8, 8, '62 heures', '99,9 %', False),
        (8, 8, '62 heures et 1 seconde', '100 %', True),
        (8, 8, '44 heures, 54 minutes et 51 secondes', '90,8 %', False),
    ]:
        result = upload(client, attendance_pdf(completed_paths=paths, completed_evaluations=evaluations,
                                              connection_total=duration))
        assert result.status_code == 200
        html = client.get('/espace/PUBLIC-TOKEN').text
        section = html.split('id="apsElearningAttendance"', 1)[1].split('</section>', 1)[0]
        paths_tile = section.split('id="apsPathsProgress"', 1)[1].split('</div>', 1)[0]
        evaluations_tile = section.split('id="apsEvaluationsProgress"', 1)[1].split('</div>', 1)[0]
        assert f'<strong>{paths}/8</strong>' in paths_tile
        assert f'<strong>{evaluations}/8</strong>' in evaluations_tile
        assert f'id="apsOverallRate">{rate}</strong>' in section
        assert 'id="apsOverallProgress"' in section
        assert ('E-learning terminé' in section) == complete
        assert ('Bravo !' in section) == complete
        assert ('E-learning en cours' in section) != complete
        admin = client.get('/admin/sessions/S-APS/trainees').text
        assert 'scope="col">Suivi global du e-learning</th>' in admin
        row = admin.split('data-trainee-id="T-APS"', 1)[1].split('</tr>', 1)[0]
        cell = row.split('<td class="col-aps-attendance">', 1)[1].split('</td>', 1)[0]
        assert f'<strong class="aps-followup-rate">{rate}</strong>' in cell
        assert f'value="{float(rate[:-2].replace(",", "."))}"' in cell
        assert f'Parcours : {paths}/8' in cell
        assert f'Évaluations : {evaluations}/8' in cell
        assert ('E-learning terminé' in cell) == complete
        assert ('aps-followup--complete' in cell) == complete
    assert 'Parcours suivis' in section and 'Questionnaires d’évaluation' in section
    assert '44 h 54' in section and '72,4 %' in section


@pytest.mark.parametrize('missing', ['paths_total', 'evaluations_total', 'connection_log_total'])
def test_public_does_not_announce_completion_with_missing_metrics(context, missing):
    client, data, trainees, save = context
    tracking = existing.ApsElearningTests._complete_tracking()
    tracking.pop(missing)
    trainees[0]['aps_elearning_tracking'] = tracking
    html = client.get('/espace/PUBLIC-TOKEN').text
    section = html.split('id="apsElearningAttendance"', 1)[1].split('</section>', 1)[0]
    assert 'id="apsOverallRate">À vérifier</strong>' in section
    assert 'id="apsOverallProgress"' not in section
    assert 'E-learning terminé' not in section and 'Bravo !' not in section
    admin = client.get('/admin/sessions/S-APS/trainees').text
    row = admin.split('data-trainee-id="T-APS"', 1)[1].split('</tr>', 1)[0]
    cell = row.split('<td class="col-aps-attendance">', 1)[1].split('</td>', 1)[0]
    assert 'À vérifier' in cell
    assert '<progress' not in cell
    assert 'E-learning terminé' not in cell and 'aps-followup--complete' not in cell


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


def test_repeated_pdf_replaces_the_stored_files(context):
    client, data, trainees, save = context
    pdf = attendance_pdf()
    assert upload(client, pdf).status_code == 200
    before = copy.deepcopy(trainees[0]['aps_elearning_tracking'])
    response = upload(client, pdf)
    assert response.status_code == 200
    assert response.json['status'] == 'replaced'
    assert save.call_count == 2
    for key in ('file', 'source_file'):
        assert trainees[0]['aps_elearning_tracking'][key] != before[key]
        assert not Path(gestion._detokenize_path(before[key])).exists()
        assert Path(gestion._detokenize_path(trainees[0]['aps_elearning_tracking'][key])).is_file()


@pytest.mark.parametrize('signature_status', ['ongoing', 'done'])
def test_bulk_replaces_signed_or_pending_dossier_and_archives_signature(context, signature_status, monkeypatch, tmp_path):
    client, data, trainees, save = context
    assert upload(client, attendance_pdf(connection_total='31 heures')).status_code == 200
    signed_path = tmp_path / 'previous-signed-dossier.pdf'
    signed_path.write_bytes(b'previous signed evidence')
    state = {'status': signature_status, 'signature_request_id': 'REQUEST', 'signed_pdf_path': str(signed_path)}
    trainees[0]['aps_elearning_signature'] = state
    monkeypatch.setattr(gestion, '_yousign_is_configured', lambda: True)
    cancel = Mock()
    monkeypatch.setattr(gestion, '_yousign_json', cancel)
    calls = Mock()
    calls.attach_mock(save, 'save')
    calls.attach_mock(cancel, 'cancel')
    save.reset_mock()
    result = upload(client, attendance_pdf(connection_total='70 heures'))
    assert result.status_code == 200
    assert result.json['status'] == 'replaced'
    assert result.json['attendance_rate'] == '100 %'
    assert trainees[0]['aps_elearning_signature'] == {}
    archived = trainees[0]['aps_elearning_signature_history'][-1]
    assert archived['archive_reason'] == 'digiforma_report_replaced'
    assert all(archived[key] == value for key, value in state.items())
    assert signed_path.read_bytes() == b'previous signed evidence'
    assert [call[0] for call in calls.mock_calls] == (['save', 'cancel'] if signature_status == 'ongoing' else ['save'])
    if signature_status == 'ongoing':
        assert cancel.call_args.args == ('POST', '/signature_requests/REQUEST/cancel')


def test_last_report_for_same_person_replaces_files_and_updates_both_spaces(context):
    client, data, trainees, save = context
    first = upload(client, attendance_pdf(connection_total='31 heures'), filename='ancien.pdf')
    assert first.json['status'] == 'imported'
    old_tracking = copy.deepcopy(trainees[0]['aps_elearning_tracking'])
    latest_pdf = attendance_pdf(connection_total='44 heures, 54 minutes et 51 secondes')
    response = upload(client, latest_pdf, filename='dernier.pdf', processed=['T-APS'])
    assert response.status_code == 200
    assert response.json['status'] == 'replaced'
    assert response.json['duration'] == '44 h 54'
    assert response.json['attendance_rate'] == '72,4 %'
    tracking = trainees[0]['aps_elearning_tracking']
    assert tracking['original_name'] == 'dernier.pdf'
    assert Path(gestion._detokenize_path(tracking['source_file'])).read_bytes() == latest_pdf
    for key in ('file', 'source_file'):
        assert not Path(gestion._detokenize_path(old_tracking[key])).exists()
    assert save.call_count == 2
    public = client.get('/espace/PUBLIC-TOKEN').text
    section = public.split('id="apsElearningAttendance"', 1)[1].split('</section>', 1)[0]
    admin = client.get('/admin/sessions/S-APS/trainees').text
    row = admin.split('data-trainee-id="T-APS"', 1)[1].split('</tr>', 1)[0]
    cell = row.split('<td class="col-aps-attendance">', 1)[1].split('</td>', 1)[0]
    for view in (section, cell):
        assert '44 h 54' in view and '/ 62 heures' in view and '90,8 %' in view
        assert '31 h 00' not in view
        assert '<progress' in view and 'value="90.8"' in view


def test_invalid_file_or_multiple_files_cannot_replace_tracking(context, tmp_path):
    client, data, trainees, save = context
    assert upload(client).status_code == 200
    before = copy.deepcopy(trainees[0])
    files_before = sorted(p for p in tmp_path.rglob('*') if p.is_file())
    save.reset_mock()
    for pdf, filename in [(b'broken', 'broken.pdf'), (attendance_pdf(complete=False), 'incomplete.pdf'),
                          (attendance_pdf(), 'report.txt')]:
        assert upload(client, pdf, filename).status_code == 400
    result = client.post(URL, data={'digiforma_pdf': [
        (io.BytesIO(attendance_pdf()), 'one.pdf'), (io.BytesIO(attendance_pdf()), 'two.pdf'),
    ]}, headers={'Accept': 'application/json'})
    assert result.status_code == 400
    assert trainees[0] == before
    assert sorted(p for p in tmp_path.rglob('*') if p.is_file()) == files_before
    save.assert_not_called()


def test_failed_save_keeps_old_dossier_and_cleans_new_files(context, tmp_path, monkeypatch):
    client, data, trainees, save = context
    assert upload(client).status_code == 200
    trainees[0]['aps_elearning_signature'] = {'status': 'ongoing', 'signature_request_id': 'REQUEST'}
    monkeypatch.setattr(gestion, '_yousign_is_configured', lambda: True)
    cancel = Mock()
    monkeypatch.setattr(gestion, '_yousign_json', cancel)
    before = copy.deepcopy(trainees[0])
    files_before = sorted(p for p in tmp_path.rglob('*') if p.is_file())
    save.side_effect = OSError('storage unavailable')
    result = upload(client, attendance_pdf(connection_total='70 heures'))
    assert result.status_code == 500
    assert trainees[0] == before
    assert sorted(p for p in tmp_path.rglob('*') if p.is_file()) == files_before
    cancel.assert_not_called()
