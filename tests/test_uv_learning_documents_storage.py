"""Group UV evidence must read authoritative SQLite state after migration."""

import copy
from io import BytesIO

import pytest
from pypdf import PdfReader

import app as host
import uv_questionnaires as uv
from uv_questionnaire_store import UVQuestionnaireStore
from test_aps_session_rollout import aps_case


@pytest.fixture
def documents_case(aps_case, monkeypatch):
    aps_case._admin_login()
    training = aps_case.data['sessions'][0]
    person = training['trainees'][0]
    person.update(first_name='Alice', last_name='Martin')
    other = {**person, 'id': 'uv-second-person', 'first_name': 'Bob'}
    training['trainees'].append(other)
    path = aps_case.persist_dir / 'uv-questionnaires.sqlite3'
    monkeypatch.setitem(host.app.config, 'UV_QUESTIONNAIRE_DB_PATH', str(path))
    return aps_case, training, person, other, UVQuestionnaireStore(path)


def completed_state(wrong_first_answer=False):
    results = {}
    for candidate in uv.bank()['courses']['aps']['units']:
        row = uv.unit('aps', candidate['number'])
        if not row:
            continue
        answers = {question['id']: question['answer'] for question in row['questions']}
        if wrong_first_answer and row['number'] == 2:
            first = row['questions'][0]
            answers[first['id']] = next(option['id'] for option in first['options'] if option['id'] != first['answer'])
        results[str(row['number'])] = {
            'version': uv.VERSION,
            'score': 19 if wrong_first_answer and row['number'] == 2 else 20,
            'submitted_at': '2026-11-18T10:30:00Z',
            'answers': answers,
        }
    return {'uv_questionnaires': {'aps': results}}


def key(training, person):
    return (training['partner_id'], training['id'], person['id'])


def index_url(training):
    return f"/api/admin/sessions/{training['id']}/learning-documents"


def pdf_url(training):
    return f"/admin/sessions/{training['id']}/learning-documents/questionnaires.pdf"


def test_group_status_and_pdf_use_results_existing_only_in_sqlite(documents_case):
    case, training, person, other, database = documents_case
    database.mutate(key(training, person), completed_state(wrong_first_answer=True), lambda state: None)
    database.mutate(key(training, other), completed_state(), lambda state: None)
    before = copy.deepcopy(case.data)
    assert 'uv_questionnaires' not in person and 'uv_questionnaires' not in other

    index = case.client.get(index_url(training))
    assert index.status_code == 200
    expected_units = sorted(map(int, completed_state()['uv_questionnaires']['aps']))
    for row in index.json['people']:
        assert sorted(row['submitted']) == expected_units

    response = case.client.get(pdf_url(training), query_string={
        'trainee_id': [person['id'], other['id']], 'uv': '2',
    })
    assert response.status_code == 200
    text = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
    assert 'Alice' in text and 'Bob' in text
    assert '19/20' in text and '20/20' in text
    assert 'Votre réponse' in text
    assert case.data == before


@pytest.mark.parametrize('empty_state', [False, True])
def test_reset_in_sqlite_overrides_completed_legacy_json(documents_case, empty_state):
    case, training, person, _, database = documents_case
    person.update(completed_state())
    database.mutate(key(training, person), completed_state(), lambda state: None)

    def reset(state):
        if empty_state:
            state.clear()
        else:
            state['uv_questionnaires']['aps'].pop('2')
            state['uv_questionnaire_resets'] = {'aps': {'2': 'new-generation'}}

    database.mutate(key(training, person), {}, reset)
    before = copy.deepcopy(case.data)
    index = case.client.get(index_url(training))
    assert index.status_code == 200
    row = next(item for item in index.json['people'] if item['id'] == person['id'])
    assert 2 not in row['submitted']
    response = case.client.get(pdf_url(training), query_string={'trainee_id': person['id'], 'uv': '2'})
    assert response.status_code == 409
    assert case.data == before
    assert '2' in person['uv_questionnaires']['aps']  # stale JSON was not modified


def test_same_identifiers_in_another_partner_do_not_expose_results(documents_case):
    case, training, person, _, database = documents_case
    database.mutate(('another-partner', training['id'], person['id']), completed_state(), lambda state: None)
    index = case.client.get(index_url(training))
    assert index.status_code == 200
    row = next(item for item in index.json['people'] if item['id'] == person['id'])
    assert row['submitted'] == []
    assert case.client.get(pdf_url(training), query_string={'trainee_id': person['id'], 'uv': '2'}).status_code == 409


def test_forbidden_partner_is_rejected_before_reading_questionnaire_storage(documents_case, monkeypatch):
    case, training, person, _, _ = documents_case
    with case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='another-partner')

    def unexpected_storage_read(*args, **kwargs):
        pytest.fail('Questionnaire storage must not be read before tenant authorization.')

    monkeypatch.setattr(uv, 'stored_trainee', unexpected_storage_read)
    assert case.client.get(index_url(training)).status_code == 404
    assert case.client.get(pdf_url(training), query_string={'trainee_id': person['id'], 'uv': '2'}).status_code == 404
