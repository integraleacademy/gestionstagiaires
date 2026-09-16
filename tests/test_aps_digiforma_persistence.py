"""Exercise Digiforma replacement against the real JSON persistence layer."""

import copy
import io
import json
from pathlib import Path

import pytest

import app as gestion
from digiforma_fixtures import attendance_pdf
import test_aps_elearning as existing


@pytest.fixture
def storage(monkeypatch, tmp_path):
    for name, value in {
        'PERSIST_DIR': tmp_path,
        'DATA_FILE': tmp_path / 'data.json',
        'UPLOADS_DIR': tmp_path / 'uploads',
        'BACKUP_DIR': tmp_path / 'backups',
    }.items():
        monkeypatch.setattr(gestion, name, str(value))
    monkeypatch.setattr(gestion, '_partner_postgres_active', lambda: False)
    monkeypatch.setattr(gestion, '_partner_postgres_shadow', lambda: False)
    (tmp_path / 'backups').mkdir()
    data = existing.ApsElearningTests._data('2026-09-07')
    data['sessions'][0]['trainees'][0]['aps_elearning_tracking'] = {
        'file': 'uploads/old.pdf', 'uploaded_at': '2026-09-15T08:00:00Z',
        'connection_log_total': '70 heures',
    }
    gestion.save_data(data)
    return Path(gestion.DATA_FILE)


def trainee(data):
    return data['sessions'][0]['trainees'][0]


def test_stale_save_cannot_restore_old_report_or_signature(storage):
    stale = gestion.load_data()
    current = copy.deepcopy(stale)
    trainee(stale)['aps_elearning_signature'] = {'status': 'done', 'signature_request_id': 'OLD'}
    trainee(current)['aps_elearning_tracking'] = {
        'file': 'uploads/new.pdf', 'uploaded_at': '2026-09-16T08:00:00Z',
        'connection_log_total': '44 heures',
    }
    trainee(current)['aps_elearning_signature'] = {}
    trainee(current)['aps_elearning_signature_history'] = [{'signature_request_id': 'OLD'}]
    gestion.append_trainee_history_event(trainee(current), 'Attestation d’assiduité Digiforma remplacée')
    gestion.save_data(current)
    trainee(stale)['comment'] = 'Une autre modification reste enregistrée'
    gestion.save_data(stale)
    persisted = trainee(json.loads(storage.read_text()))
    assert persisted['aps_elearning_tracking'] == trainee(current)['aps_elearning_tracking']
    assert persisted['aps_elearning_signature'] == {}
    assert persisted['aps_elearning_signature_history'] == [{'signature_request_id': 'OLD'}]
    assert persisted['comment'] == trainee(stale)['comment']
    assert persisted['activity_history'][0]['label'] == 'Attestation d’assiduité Digiforma remplacée'


@pytest.mark.parametrize('endpoint', [
    '/admin/sessions/S-APS/aps-elearning/digiforma/bulk-upload',
    '/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/digiforma/upload',
])
def test_reimport_survives_a_stale_save_and_fresh_page_load(storage, endpoint):
    stale = gestion.load_data()
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin', admin_username='admin@example.test')
    pdf = attendance_pdf(connection_total='31 heures')
    result = client.post(endpoint, data={'digiforma_pdf': (io.BytesIO(pdf), 'nouveau.pdf')})
    assert result.status_code == (200 if endpoint.endswith('bulk-upload') else 302)
    imported = copy.deepcopy(trainee(json.loads(storage.read_text()))['aps_elearning_tracking'])
    assert imported['connection_log_total'] == '31 heures'
    gestion.save_data(stale)
    restored = trainee(gestion.load_data())['aps_elearning_tracking']
    assert restored == imported
    assert Path(gestion._detokenize_path(restored['source_file'])).read_bytes() == pdf
    for url in ('/admin/sessions/S-APS/trainees', '/espace/PUBLIC-TOKEN'):
        html = client.get(url).text
        assert '31 h 00' in html and '83,3 %' in html
        if url.endswith('/trainees'):
            assert 'Dernier import' in html


def test_stale_save_preserves_rebuilt_pdf(storage):
    stale = gestion.load_data()
    rebuilt = copy.deepcopy(stale)
    trainee(rebuilt)['aps_elearning_tracking'].update(file='rebuilt.pdf', rebuilt_at='2026-09-16T08:00:00Z')
    gestion.save_data(rebuilt)
    gestion.save_data(stale)
    assert trainee(gestion.load_data())['aps_elearning_tracking']['file'] == 'rebuilt.pdf'


def test_reset_is_persisted_and_cannot_be_undone_by_a_stale_save(storage):
    stale = gestion.load_data()
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin', admin_username='admin@example.test')
    result = client.post('/admin/sessions/S-APS/stagiaires/T-APS/aps-elearning/reset')
    assert result.status_code == 302
    assert 'aps_elearning_tracking' not in trainee(json.loads(storage.read_text()))
    gestion.save_data(stale)
    assert 'aps_elearning_tracking' not in trainee(gestion.load_data())


def test_current_report_signature_changes_are_still_saved(storage):
    current = gestion.load_data()
    trainee(current)['aps_elearning_signature'] = {'status': 'done', 'signature_request_id': 'CURRENT'}
    gestion.save_data(current)
    assert trainee(gestion.load_data())['aps_elearning_signature']['status'] == 'done'


def test_partner_merge_preserves_latest_report_without_crossing_tenants(storage):
    canonical = gestion.load_data()
    canonical['sessions'][0]['partner_id'] = 'PARTNER-A'
    stale = copy.deepcopy(canonical)
    trainee(canonical)['aps_elearning_tracking'].update(file='new.pdf', uploaded_at='2026-09-16T08:00:00Z')
    other = copy.deepcopy(stale['sessions'][0])
    other.update(id='S-OTHER', partner_id='PARTNER-B')
    canonical['sessions'].append(other)
    merged = gestion._merge_partner_scoped_payload(stale, 'PARTNER-A', canonical, global_payload=False)
    own = next(s for s in merged['sessions'] if s['partner_id'] == 'PARTNER-A')
    assert own['trainees'][0]['aps_elearning_tracking']['file'] == 'new.pdf'
    assert next(s for s in merged['sessions'] if s['partner_id'] == 'PARTNER-B') == other
