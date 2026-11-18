"""The UV read cache must save work without retaining revoked access or state."""
from concurrent.futures import ThreadPoolExecutor
import copy
import datetime as dt
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app
import uv_questionnaire_context as context
import uv_questionnaires as uv


PATH = '/espace/context-token/questionnaires-uv/3'


def payload():
    return {'sessions': [{
        'id': 'SOURCE', 'partner_id': app.INTEGRALE_PARTNER_ID,
        'name': 'APS synthetic context', 'training_type': 'APS',
        'date_start': '2026-10-26', 'aps_in_person_start': '2026-11-09',
        'trainees': [{'id': 'TEST-1', 'first_name': 'Technique',
                      'last_name': 'FICTIF', 'public_token': 'context-token'}],
    }]}


def write_source(path, data, *, replace=True, preserve_mtime=False):
    previous = path.stat() if preserve_mtime else None
    target = path.with_suffix('.new') if replace else path
    target.write_text(json.dumps(data), encoding='utf-8')
    if replace:
        os.replace(target, path)
    if previous:
        os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))


def test_repeated_lookup_keeps_only_independent_small_contexts(tmp_path, monkeypatch):
    data = payload()
    training = data['sessions'][0]
    trainee = training['trainees'][0]
    training['irrelevant_session_history'] = ['x' * 1000] * 100
    trainee['documents'] = [{'description': 'x' * 1000}] * 100
    trainee['uv_questionnaire_attempts'] = {'aps': {'3': {'answers': {'q01': '1'}}}}
    data['billing_lines'] = [{'logs': ['x' * 1000] * 100}]
    source = tmp_path / 'data.json'
    write_source(source, data)
    reader = Mock(wraps=context.json.load)
    monkeypatch.setattr(context.json, 'load', reader)
    index = context.UVContextIndex(source)
    for _ in range(24):
        group, person = index.lookup('context-token')
        assert 'trainees' not in group and 'irrelevant_session_history' not in group
        assert 'documents' not in person and 'billing_lines' not in person
        person['uv_questionnaire_attempts']['aps']['3']['answers']['q01'] = 'changed'
        group['date_start'] = 'changed'
    group, person = index.lookup('context-token')
    assert group['date_start'] == '2026-10-26'
    assert person['uv_questionnaire_attempts']['aps']['3']['answers']['q01'] == '1'
    assert reader.call_count == index.build_count == 1


def test_cold_index_has_one_builder_for_24_simultaneous_readers(tmp_path, monkeypatch):
    source = tmp_path / 'data.json'
    write_source(source, payload())
    index = context.UVContextIndex(source)
    entered, release = threading.Event(), threading.Event()
    original = context.json.load
    calls = []

    def held_read(handle):
        calls.append(1)
        entered.set()
        assert release.wait(5), 'The test must release the single builder.'
        return original(handle)

    monkeypatch.setattr(context.json, 'load', held_read)
    with ThreadPoolExecutor(max_workers=24) as executor:
        futures = [executor.submit(index.lookup, 'context-token') for _ in range(24)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert len(calls) == index.build_count == 1
    assert all(person['id'] == 'TEST-1' for _, person in results)


@pytest.mark.parametrize('replace', [False, True])
def test_token_revocation_invalidates_even_with_same_length_and_mtime(tmp_path, replace):
    source = tmp_path / 'data.json'
    data = payload()
    write_source(source, data)
    index = context.UVContextIndex(source)
    assert index.lookup('context-token')[1]['id'] == 'TEST-1'
    before = source.stat()
    data['sessions'][0]['trainees'][0]['public_token'] = 'changed-token'
    write_source(source, data, replace=replace, preserve_mtime=True)
    after = source.stat()
    assert before.st_mtime_ns == after.st_mtime_ns and before.st_size == after.st_size
    if not replace:
        assert before.st_ino == after.st_ino
        assert before.st_ctime_ns != after.st_ctime_ns
    assert index.lookup('context-token') == (None, None)
    assert index.lookup('changed-token')[1]['id'] == 'TEST-1'
    assert index.build_count == 2


@pytest.mark.parametrize('damage', ['missing', 'invalid'])
def test_changed_source_never_falls_back_to_a_previously_authorized_token(tmp_path, damage):
    source = tmp_path / 'data.json'
    write_source(source, payload())
    index = context.UVContextIndex(source)
    assert index.lookup('context-token')[1]
    if damage == 'missing':
        source.unlink()
    else:
        source.write_text('{truncated', encoding='utf-8')
    with pytest.raises((OSError, ValueError)):
        index.lookup('context-token')


def test_replace_during_projection_rebuilds_before_publishing(tmp_path, monkeypatch):
    source = tmp_path / 'data.json'
    data = payload()
    write_source(source, data)
    original = context._project
    projected = []

    def replace_while_building(value):
        projected.append(1)
        if len(projected) == 1:
            data['sessions'][0]['trainees'][0]['registration_cancelled'] = True
            write_source(source, data)
        return original(value)

    monkeypatch.setattr(context, '_project', replace_while_building)
    index = context.UVContextIndex(source)
    assert index.lookup('context-token')[1]['registration_cancelled'] is True
    assert len(projected) == 2 and index.build_count == 1


def test_canonical_duplicate_and_both_token_aliases_are_preserved(tmp_path):
    data = payload()
    person = data['sessions'][0]['trainees'][0]
    person.update(created_at='2026-11-18', token='legacy-alias', registration_cancelled=True)
    duplicate = copy.deepcopy(person)
    duplicate['registration_cancelled'] = False
    data['sessions'][0]['trainees'].append(duplicate)
    source = tmp_path / 'data.json'
    write_source(source, data)
    index = context.UVContextIndex(source)
    assert index.lookup('context-token')[1]['registration_cancelled'] is True
    assert index.lookup('legacy-alias')[1]['registration_cancelled'] is True


def test_legacy_roster_names_and_cancelled_alias_are_kept(tmp_path):
    data = payload()
    training = data['sessions'][0]
    training.pop('trainees')
    training['stagiaires'] = [{'id': 'LEGACY', 'nom': 'FICTIF', 'prenom': 'Technique',
                              'token': 'old-link', 'inscription_annulee': 'oui'}]
    source = tmp_path / 'data.json'
    write_source(source, data)
    _, person = context.UVContextIndex(source).lookup('old-link')
    assert person['last_name'] == 'FICTIF' and person['first_name'] == 'Technique'
    assert app._trainee_registration_is_cancelled(person)


def test_two_legacy_tokens_without_ids_use_distinct_legacy_contexts(tmp_path):
    data = payload()
    training = data['sessions'][0]
    training.pop('trainees')
    training['stagiaires'] = [{'public_token': token, 'nom': token} for token in ('legacy-a', 'legacy-b')]
    source = tmp_path / 'data.json'
    write_source(source, data)
    index = context.UVContextIndex(source)
    for token in ('legacy-a', 'legacy-b'):
        with pytest.raises(context.UnversionedSource):
            index.lookup(token)

    def legacy_loader(**_kwargs):
        normalized = copy.deepcopy(data)
        app.normalize_sessions_schema(normalized, archive_duplicates=False)
        return normalized

    services = SimpleNamespace(DATA_FILE=str(source), load_data=legacy_loader,
                               find_session_and_trainee_by_token=app.find_session_and_trainee_by_token)
    pairs = [uv._public_pair(services, token, original_loader=legacy_loader)
             for token in ('legacy-a', 'legacy-b')]
    assert all(person['id'].startswith('TRN-') for _, person in pairs)
    assert pairs[0][1]['id'] != pairs[1][1]['id']


@pytest.mark.parametrize('source_kind', ['injected', 'postgres', 'scoped'])
def test_sources_without_a_global_json_revision_keep_the_authorized_loader(tmp_path, source_kind):
    data = payload()
    loader = Mock(return_value=data)
    services = SimpleNamespace(DATA_FILE=str(tmp_path / 'must-not-read.json'), load_data=loader,
                               find_session_and_trainee_by_token=app.find_session_and_trainee_by_token,
                               _partner_postgres_active=lambda: source_kind == 'postgres',
                               _is_partner_data_scope_session=lambda: source_kind == 'scoped')
    original = (lambda: None) if source_kind == 'injected' else loader
    assert uv._public_pair(services, 'context-token', original_loader=original)[1]['id'] == 'TEST-1'
    loader.assert_called_once_with(run_background_tasks=False, persist_normalization=False)


@pytest.fixture
def disk_case(tmp_path, monkeypatch):
    data = payload()
    source = tmp_path / 'data.json'
    write_source(source, data)
    monkeypatch.setattr(app, 'DATA_FILE', str(source))
    monkeypatch.setattr(app, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(app, '_partner_postgres_active', lambda: False)
    monkeypatch.setitem(app.app.config, 'UV_QUESTIONNAIRE_DB_PATH', str(tmp_path / 'uv.sqlite3'))
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 11, 9))
    monkeypatch.setattr(uv, 'clock', lambda: 1000.0)
    client = app.app.test_client()
    with client.session_transaction() as cookie:
        cookie['public_auth_context-token'] = True
        cookie['uv_questionnaire_csrf'] = 'context-csrf'
    return client, data, source


def post(client, action='sync', *, path=PATH, **kwargs):
    return client.post(path, json={'csrf': 'context-csrf', 'action': action, **kwargs})


def test_real_http_posts_reuse_index_without_global_reader_normalizer_or_billing_copy(disk_case, monkeypatch):
    client, data, source = disk_case
    blocked = Mock(side_effect=AssertionError('UV must not load the general administrative document.'))
    monkeypatch.setattr(app, '_load_valid_json_payload', blocked)
    monkeypatch.setattr(app, 'normalize_sessions_schema', blocked)
    monkeypatch.setattr(app.billing_persistence, 'track_payload', blocked)
    unchanged = source.read_bytes()
    state = post(client, 'start', in_class='yes').json
    for question in uv.unit('aps', 3)['questions']:
        assert state['question']['id'] == question['id']
        response = post(client, 'answer', question_id=question['id'], answer=question['answer'])
        assert response.status_code == 200
        state = response.json
    assert state == {'completed': True, 'score': 20}
    blocked.assert_not_called()
    assert context.index_for(source).build_count == 1
    assert source.read_bytes() == unchanged
    training = data['sessions'][0]
    result = uv.stored_trainee(app, training, training['trainees'][0])['uv_questionnaires']['aps']['3']
    assert len(result['answers']) == 20 and all(result['answers'].values())


@pytest.mark.parametrize('change,expected', [('cancelled', 403), ('in_person', 403), ('cohort', 404), ('delete', 404)])
def test_committed_access_changes_reject_the_next_answer(disk_case, change, expected):
    client, data, source = disk_case
    question = post(client, 'start', in_class='yes').json['question']
    training = data['sessions'][0]
    person = training['trainees'][0]
    if change == 'cancelled':
        person['registration_cancelled'] = True
    elif change == 'in_person':
        training['aps_in_person_start'] = '2026-12-01'
    elif change == 'cohort':
        training['date_start'] = '2026-10-25'
    else:
        data['sessions'] = []
    write_source(source, data)
    assert post(client, 'answer', question_id=question['id'], answer=question['options'][0]['id']).status_code == expected
    assert uv.stored_trainee(app, training, person)['uv_questionnaire_attempts']['aps']['3']['answers'] == {}


def test_rotated_token_requires_its_own_public_authentication(disk_case):
    client, data, source = disk_case
    assert post(client).status_code == 200
    data['sessions'][0]['trainees'][0]['public_token'] = 'rotated-token'
    write_source(source, data)
    assert post(client).status_code == 404
    rotated = PATH.replace('context-token', 'rotated-token')
    assert post(client, path=rotated).status_code == 302
    with client.session_transaction() as cookie:
        cookie['public_auth_rotated-token'] = True
    assert post(client, path=rotated).json == {'started': False, 'completed': False}


def test_afc_individual_date_and_paris_day_are_rechecked_without_rebuilding(disk_case, monkeypatch):
    client, data, source = disk_case
    training = data['sessions'][0]
    training['afc_enabled'] = True
    training['trainees'][0]['training_date_start'] = '2026-11-10'
    write_source(source, data)
    assert post(client).status_code == 403
    monkeypatch.setattr(uv, 'today', lambda: dt.date(2026, 11, 10))
    assert post(client).status_code == 200
    assert context.index_for(source).build_count == 1


def test_transfer_uses_new_session_context_and_existing_sqlite_alias(disk_case):
    client, data, source = disk_case
    questions = uv.unit('aps', 3)['questions']
    post(client, 'start', in_class='yes')
    assert post(client, 'answer', question_id=questions[0]['id'], answer=questions[0]['answer']).status_code == 200
    old = data['sessions'][0]
    person = old['trainees'][0]
    target = {**old, 'id': 'TARGET', 'partner_id': 'other-partner', 'trainees': [person]}
    uv.transfer_state(app, old, target, person)
    old['trainees'] = []
    data['sessions'].append(target)
    write_source(source, data)
    response = post(client, 'answer', question_id=questions[1]['id'], answer=questions[1]['answer'])
    assert response.status_code == 200 and response.json['index'] == 3
    saved = uv.stored_trainee(app, target, person)['uv_questionnaire_attempts']['aps']['3']['answers']
    assert saved == {q['id']: q['answer'] for q in questions[:2]}
    assert uv.stored_trainee(app, old, person)['uv_questionnaire_attempts']['aps']['3']['answers'] == saved


def test_sqlite_reset_wins_over_cached_legacy_results_without_json_change(disk_case):
    client, data, source = disk_case
    training = data['sessions'][0]
    person = training['trainees'][0]
    person['uv_questionnaires'] = {'aps': {'3': {'version': uv.VERSION, 'score': 20, 'answers': {}}}}
    write_source(source, data)
    assert post(client).json == {'completed': True, 'score': 20}
    before = source.read_bytes()

    def reset(state):
        state.clear()
        state['uv_questionnaire_resets'] = {'aps': {'3': 'new-generation'}}

    uv._store(app).mutate(uv._storage_key(app, training, person), uv._legacy_state(person), reset)
    assert post(client).status_code == 409
    assert post(client, generation='new-generation').json == {'started': False, 'completed': False}
    assert post(client, 'start', generation='new-generation', in_class='yes').json['index'] == 1
    assert source.read_bytes() == before and context.index_for(source).build_count == 1


def test_corrupt_source_returns_retryable_error_without_accepting_an_answer(disk_case):
    client, data, source = disk_case
    question = post(client, 'start', in_class='yes').json['question']
    source.write_text('{truncated', encoding='utf-8')
    assert post(client, 'answer', question_id=question['id'], answer=question['options'][0]['id']).status_code == 503
    training = data['sessions'][0]
    saved = uv.stored_trainee(app, training, training['trainees'][0])
    assert saved['uv_questionnaire_attempts']['aps']['3']['answers'] == {}
