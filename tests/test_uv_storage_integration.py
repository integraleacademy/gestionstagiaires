"""UV storage stays independent from administrative saves and session moves."""
import copy
import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import app as host
import uv_questionnaires as uv
from uv_questionnaire_store import UVQuestionnaireStore


@pytest.fixture
def storage(tmp_path, monkeypatch):
    data_file = tmp_path / 'data.json'
    backup_dir = tmp_path / 'backups'
    backup_dir.mkdir()
    monkeypatch.setattr(host, 'DATA_FILE', str(data_file))
    monkeypatch.setattr(host, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(host, 'BACKUP_DIR', str(backup_dir))
    monkeypatch.setattr(host, 'BACKUP_RETENTION', 2)
    monkeypatch.setattr(host, 'BACKUP_MIN_INTERVAL_SECONDS', 300)
    monkeypatch.setitem(host.app.config, 'UV_QUESTIONNAIRE_DB_PATH', str(tmp_path / 'uv.sqlite3'))
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 11, 18))
    return data_file, backup_dir


def test_read_only_normalization_does_not_write_or_mask_normal_save(storage, monkeypatch):
    data_file, _ = storage
    data_file.write_text(json.dumps({'sessions': []}))
    original = data_file.read_bytes()
    writer = Mock(wraps=host.save_data)
    monkeypatch.setattr(host, 'save_data', writer)
    with host.app.test_request_context('/espace/example/questionnaires-uv/2'):
        read_only = host.load_data(persist_normalization=False)
        assert 'notifications_admin' in read_only
        assert data_file.read_bytes() == original
        writer.assert_not_called()
        # A later caller which expects normalization persistence must not reuse
        # the no-save cache entry and silently omit its required save.
        host.load_data()
        writer.assert_called_once()
    assert 'notifications_admin' in json.loads(data_file.read_text())


def test_session_transfer_and_return_keep_the_same_answers(storage, monkeypatch):
    person = {'id': 'UV-T1', 'public_token': 'uv-transfer-token',
              'first_name': 'Test', 'last_name': 'Transfer'}
    source = {'id': 'UV-SOURCE', 'training_type': 'APS', 'date_start': '2026-10-26',
              'aps_in_person_start': '2026-11-09', 'trainees': [person]}
    target = {**source, 'id': 'UV-TARGET', 'trainees': []}
    data = {'sessions': [source, target]}
    monkeypatch.setattr(host, 'load_data', lambda **kwargs: data)
    monkeypatch.setattr(host, 'save_data', lambda *args, **kwargs: None)
    monkeypatch.setattr(host, 'ensure_documents_schema_for_trainee', lambda *args: None)
    monkeypatch.setattr(host, 'dossier_is_complete_total', lambda *args: False)
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role='admin',
                    public_auth_uv_transfer_token=True, uv_questionnaire_csrf='csrf')
        auth['public_auth_uv-transfer-token'] = True
    path = '/espace/uv-transfer-token/questionnaires-uv/2'

    def submit(action, **kwargs):
        response = client.post(path, json={'csrf': 'csrf', 'action': action, **kwargs})
        assert response.status_code == 200
        return response.json

    questions = uv.unit('aps', 2)['questions']
    submit('start', in_class='yes')
    submit('answer', question_id=questions[0]['id'], answer=questions[0]['answer'])
    before = uv.stored_trainee(host, source, person)['uv_questionnaire_attempts']
    response = client.post('/admin/sessions/UV-SOURCE/stagiaires/UV-T1/transfer',
                           data={'target_session_id': 'UV-TARGET'})
    assert response.status_code == 302
    assert not source['trainees'] and target['trainees'] == [person]
    assert uv.stored_trainee(host, target, person)['uv_questionnaire_attempts'] == before
    assert submit('sync')['index'] == 2
    submit('answer', question_id=questions[1]['id'], answer=questions[1]['answer'])
    response = client.post('/admin/sessions/UV-TARGET/stagiaires/UV-T1/transfer',
                           data={'target_session_id': 'UV-SOURCE'})
    assert response.status_code == 302
    assert source['trainees'] == [person] and not target['trainees']
    assert submit('sync')['index'] == 3
    assert uv.stored_trainee(host, source, person)['uv_questionnaire_attempts']['aps']['2']['answers'] == {
        q['id']: q['answer'] for q in questions[:2]}


def test_sqlite_backup_lifecycle_is_throttled_and_separate_from_json(storage):
    data_file, backup_dir = storage
    data_file.write_text('{"sessions": []}')
    store = uv._store(host)
    key = (host.INTEGRALE_PARTNER_ID, 'SESSION', 'LEARNER')
    state = {'uv_questionnaire_attempts': {'aps': {'2': {'answers': {'q01': '1'}}}}}
    store.mutate(key, state, lambda current: None)
    assert host._force_backup_snapshot(str(data_file), reason='before-save')
    first = list(backup_dir.glob('uv_questionnaires.*.sqlite3'))
    assert len(first) == 1 and UVQuestionnaireStore(first[0]).read(key) == state
    # A second automatic general save does not make another SQLite snapshot.
    host._force_backup_snapshot(str(data_file), reason='before-save')
    assert len(list(backup_dir.glob('uv_questionnaires.*.sqlite3'))) == 1
    # Explicit/manual snapshots bypass the interval and have their own retention.
    host._force_backup_snapshot(str(data_file), reason='pre-trainee-recovery')
    host._force_backup_snapshot(str(data_file), reason='manual')
    assert len(list(backup_dir.glob('uv_questionnaires.*.sqlite3'))) == 2
    assert len(list(backup_dir.glob('data_json.*.json'))) == 2
    # Restoring an old administrative JSON does not restore old/reset UV state.
    store.mutate(key, {}, lambda current: current.clear())
    data_file.write_text('{"sessions": []}')
    assert store.read(key) == {}
