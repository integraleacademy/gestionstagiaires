import copy
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader

import app as host
import uv_questionnaires as uv
from test_aps_session_rollout import aps_case


def setup(case):
    case._admin_login()
    training = case.data['sessions'][0]
    first = training['trainees'][0]
    first.update(first_name='Alice', last_name='Martin')
    training['trainees'].extend([{**first, 'id':'other', 'first_name':'Bob'},
                                 {**first, 'id':'cancelled', 'registration_cancelled':True}])
    return training, first, '/admin/sessions/session-aps/learning-documents/'


def test_same_attestations_individual_or_group_without_changing_progress(aps_case):
    training, person, base = setup(aps_case)
    before = copy.deepcopy(aps_case.data)
    index = aps_case.client.get('/api/admin/sessions/session-aps/learning-documents')
    assert index.status_code == 200
    assert len(index.json['people']) == 2
    individual = aps_case.client.get(aps_case.report_url + '/attestation.pdf')
    grouped = aps_case.client.get(base+'attestations.pdf', query_string={'trainee_id':[person['id'],'other']})
    assert grouped.status_code == 200
    pages = PdfReader(BytesIO(grouped.data)).pages
    first_pages = PdfReader(BytesIO(individual.data)).pages
    assert len(pages) == 2 * len(first_pages)
    for expected, actual in zip(first_pages, pages):
        assert expected.extract_text() == actual.extract_text()
    assert aps_case.data == before
    assert not (aps_case.persist_dir / 'native_elearning' / 'tracking.sqlite3').exists()


def test_questionnaires_group_blank_answers_and_versioned_correction(aps_case):
    training, person, base = setup(aps_case)
    row = uv.unit('aps', 2)
    person['uv_questionnaires'] = {'aps': {'2': {'version': uv.VERSION, 'score':20,
        'submitted_at':'2026-11-16', 'answers':{q['id']:q['answer'] for q in row['questions']}}}}
    query = {'trainee_id':[person['id'],'other'], 'uv':'2'}
    for mode in ('blank', 'correction', 'answers'):
        assert aps_case.client.get(base+'questionnaires.pdf',query_string={**query, 'mode':mode}).status_code == 409
    for item in uv.bank()['courses']['aps']['units']:
        number = item['number']
        if uv.unit('aps', number):
            person['uv_questionnaires']['aps'][str(number)] = dict(version=uv.VERSION, score=20, submitted_at='2026-11-16',
                answers={q['id']:q['answer'] for q in item['questions']})
    assert aps_case.client.get(base+'questionnaires.pdf',query_string=query).status_code == 409
    query['trainee_id'] = person['id']
    blank = aps_case.client.get(base+'questionnaires.pdf',query_string=query)
    assert blank.status_code == 200 and 'inline' in blank.headers['Content-Disposition']
    blank_text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(blank.data)).pages)
    assert 'Alice' in blank_text and 'Bob' not in blank_text and 'Bonne réponse' not in blank_text
    answers = aps_case.client.get(base+'questionnaires.pdf',query_string={**query,'mode':'answers'})
    assert answers.status_code == 200
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(answers.data)).pages)
    assert 'Alice' in text and '20/20' in text and 'Bonne réponse' in text
    assert aps_case.client.get(base+'questionnaires.pdf',query_string={**query,'uv':'1'}).status_code == 400
    with patch('admin_learning_documents.uv.unit', wraps=uv.unit) as unit:
        aps_case.client.get(base+'questionnaires.pdf',query_string={**query,'mode':'answers'})
        assert any(c.args == ('aps', 2, uv.VERSION) for c in unit.call_args_list)


def test_documents_require_valid_selection_and_same_tenant(aps_case):
    _, person, base = setup(aps_case)
    for ids in ([], ['cancelled'], ['unknown'], [person['id'],'unknown']):
        assert aps_case.client.get(base+'attestations.pdf',query_string={'trainee_id':ids}).status_code == 400
    assert host.app.test_client().get(base+'attestations.pdf').status_code == 302
    with aps_case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other-school')
    assert aps_case.client.get('/api/admin/sessions/session-aps/learning-documents').status_code == 404
    assert aps_case.client.get(base+'attestations.pdf',query_string={'trainee_id':person['id']}).status_code == 404
