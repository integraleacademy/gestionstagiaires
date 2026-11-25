import copy
from io import BytesIO
from unittest.mock import patch

import pytest
from lxml import html
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


@pytest.mark.parametrize("course", ["aps", "a3p"])
def test_submitted_uv_prints_immediately_from_partially_completed_dossiers(aps_case, course):
    training, person, base = setup(aps_case)
    training.update(training_type=course.upper(), name="Session " + course.upper())
    row = uv.unit(course, 2)
    person['uv_questionnaires'] = {course: {'2': {'version': uv.VERSION, 'score': 20,
        'submitted_at': '2026-11-16', 'answers': {q['id']: q['answer'] for q in row['questions']}}}}
    query = {'trainee_id': [person['id'], 'other'], 'uv': '2'}
    index = aps_case.client.get('/api/admin/sessions/session-aps/learning-documents').json
    assert not index['require_all_uv']
    assert next(u for u in index['units'] if u['number'] == 2)['completed'] == 1
    roster = html.fromstring(aps_case.client.get('/admin/sessions/session-aps/trainees').text)
    link, = roster.xpath('//*[@data-report-download]')
    assert link.get('target') == '_blank' and 'noopener' in link.get('rel').split()
    for mode in ('blank', 'correction'):
        assert aps_case.client.get(base + 'questionnaires.pdf', query_string={**query, 'mode': mode}).status_code == 400
    with patch('admin_learning_documents.uv.unit', wraps=uv.unit) as lookup:
        response = aps_case.client.get(base + 'questionnaires.pdf', query_string=query)
        assert any(c.args == (course, 2, uv.VERSION) for c in lookup.call_args_list)
    assert response.status_code == 200 and 'inline' in response.headers['Content-Disposition']
    pages = PdfReader(BytesIO(response.data)).pages
    assert 1 <= len(pages) <= 2
    text = ' '.join(p.extract_text() for p in pages)
    assert 'Alice' in text and 'Bob' not in text and '20/20' in text and 'Votre réponse' in text
    assert all(f'{i:02}.' in text for i in range(1, 21))
    assert aps_case.client.get(base + 'questionnaires.pdf', query_string={**query, 'trainee_id': 'other'}).status_code == 409
    assert aps_case.client.get(base + 'questionnaires.pdf', query_string={**query, 'uv': '999'}).status_code == 400


def test_documents_require_valid_selection_and_same_tenant(aps_case):
    _, person, base = setup(aps_case)
    for ids in ([], ['cancelled'], ['unknown'], [person['id'],'unknown']):
        assert aps_case.client.get(base+'attestations.pdf',query_string={'trainee_id':ids}).status_code == 400
    assert host.app.test_client().get(base+'attestations.pdf').status_code == 302
    with aps_case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='other-school')
    assert aps_case.client.get('/api/admin/sessions/session-aps/learning-documents').status_code == 404
    assert aps_case.client.get(base+'attestations.pdf',query_string={'trainee_id':person['id']}).status_code == 404
