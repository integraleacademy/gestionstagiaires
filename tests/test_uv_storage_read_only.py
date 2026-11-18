from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import datetime as dt
import json

import pytest

import app
import uv_questionnaires as uv


@pytest.fixture
def duplicate_roster(tmp_path, monkeypatch):
    person = {'id': 'T1', 'public_token': 'readonly-token',
              'created_at': '2026-11-18T09:00:00Z', 'first_name': 'Original'}
    training = {'id': 'S1', 'training_type': 'APS', 'date_start': '2026-10-26',
                'aps_in_person_start': '2026-11-09',
                'trainees': [person, {**person, 'first_name': 'Divergent'}]}
    data = {'sessions': [training]}
    data_file = tmp_path / 'data.json'
    data_file.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(app, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(app, 'DATA_FILE', str(data_file))
    monkeypatch.setattr(app, 'BACKUP_DIR', str(tmp_path / 'backups'))
    monkeypatch.setitem(app.app.config, 'TESTING', True)
    monkeypatch.setitem(app.app.config, 'UV_QUESTIONNAIRE_DB_PATH',
                        str(tmp_path / 'uv-questionnaires.sqlite3'))
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 11, 18))
    return data_file, data, training, person


@pytest.mark.parametrize('duplicates_from_overlay', [False, True])
def test_uv_answers_finish_while_general_writer_is_locked_with_divergent_duplicates(
        duplicate_roster, monkeypatch, duplicates_from_overlay):
    data_file, data, training, person = duplicate_roster
    before = data_file.read_bytes()
    if duplicates_from_overlay:
        # Partner bundles can reintroduce legacy duplicates after the JSON read.
        # Exercise the later normalization pass as well as the initial reader.
        monkeypatch.setattr(app, '_overlay_partner_postgres_for_platform',
                            lambda _data: deepcopy(data))

    def answer():
        client = app.app.test_client()
        with client.session_transaction() as cookie:
            cookie.update({'public_auth_readonly-token': True,
                           'uv_questionnaire_csrf': 'readonly-csrf'})
        url = '/espace/readonly-token/questionnaires-uv/2'
        first = client.post(url, json={'csrf': 'readonly-csrf', 'action': 'start',
                                       'in_class': 'yes'})
        assert first.status_code == 200
        question = uv.unit('aps', 2)['questions'][0]
        saved = client.post(url, json={'csrf': 'readonly-csrf', 'action': 'answer',
                                       'question_id': question['id'], 'answer': question['answer']})
        assert saved.status_code == 200
        assert saved.json['index'] == 2
        return question

    with ThreadPoolExecutor(max_workers=1) as workers:
        # A different thread owns the real administrative lock. A hidden archive
        # write would wait here and make this test fail instead of being mocked out.
        with app._data_lock:
            pending = workers.submit(answer)
            question = pending.result(timeout=3)
    assert data_file.read_bytes() == before
    assert not (data_file.parent / 'backups' / 'registration-copies').exists()
    state = uv.stored_trainee(app, training, person)
    assert state['uv_questionnaire_attempts']['aps']['2']['answers'] == {
        question['id']: question['answer']}


def test_regular_read_after_read_only_view_still_archives_and_persists_repairs(duplicate_roster):
    data_file, _data, _training, _person = duplicate_roster
    before = data_file.read_bytes()
    with app.app.test_request_context('/'):
        readonly = app.load_data(persist_normalization=False)
        assert len(readonly['sessions'][0]['trainees']) == 1
        assert readonly['sessions'][0]['trainees'][0]['first_name'] == 'Original'
        assert data_file.read_bytes() == before
        assert not (data_file.parent / 'backups' / 'registration-copies').exists()
        normal = app.load_data()
    assert normal is not readonly
    assert len(json.loads(data_file.read_text())['sessions'][0]['trainees']) == 1
    archives = list((data_file.parent / 'backups' / 'registration-copies').glob('*.json'))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())['trainee']['first_name'] == 'Divergent'


def test_regular_schema_normalization_keeps_archival_protection(duplicate_roster):
    data_file, data, _training, _person = duplicate_roster
    assert app.normalize_sessions_schema(data)
    assert len(data['sessions'][0]['trainees']) == 1
    archives = list((data_file.parent / 'backups' / 'registration-copies').glob('*.json'))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())['trainee']['first_name'] == 'Divergent'
