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


def submitted(course, number, version, selections=None):
    row = uv.unit(course, number, version)
    answers = {q['id']: q['answer'] for q in row['questions']}
    answers.update(selections or {})
    return {'version': version, 'answers': answers, 'score': uv.grade(row['questions'], answers),
            'submitted_at': '2026-11-23T14:10:00Z'}


def test_unit_report_available_on_first_submission_with_portraits_and_pending_learners(documents_case):
    from PIL import Image

    case, training, person, other, database = documents_case
    report_url = f"/admin/sessions/{training['id']}/questionnaires-uv/2/rapport.pdf"
    assert case.client.get(report_url).status_code == 409
    assert not any(u['report_url'] for u in case.client.get(index_url(training)).json['units'])

    # The genuine local photograph is cropped to a small square; the missing photo uses initials.
    token = 'portrait-test.png'
    Image.new('RGB', (60, 90), '#136963').save(case.persist_dir / token)
    person['identity_photo'] = token
    other['identity_photo'] = 'absent.jpg'
    person_result = submitted('aps', 2, uv.VERSION, {'q01': '', 'q02': ''})
    database.mutate(key(training, person), {'uv_questionnaires': {'aps': {'2': person_result}}}, lambda _: None)
    other['uv_questionnaire_attempts'] = {'aps': {'2': {'version': uv.VERSION, 'index': 3}}}
    inactive = {**person, 'id': 'retired', 'last_name': 'Annulation', 'registration_cancelled': True}
    training['trainees'].append(inactive)

    units = case.client.get(index_url(training)).json['units']
    available = [u for u in units if u['report_url']]
    assert [(u['number'], u['completed'], u['report_url']) for u in available] == [(2, 1, report_url)]

    response = case.client.get(report_url)
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    assert 'attachment' in response.headers['Content-Disposition']
    assert 'no-store' in response.headers['Cache-Control']
    pdf = PdfReader(BytesIO(response.data))
    assert 2 <= len(pdf.pages) <= 5
    assert any(image.image.size == (88, 88) for image in pdf.pages[0].images)
    cover = pdf.pages[0].extract_text()
    for label in ('Alice', 'Bob', 'En cours', '18/20', '18,0/20'):
        assert label in cover
    assert 'Annulation' not in cover
    assert case.client.get(report_url.replace('/2/', '/1/')).status_code == 404
    assert case.client.get(report_url.replace('/2/', '/99/')).status_code == 404

    # A reset hides the link and invalidates a previously copied URL immediately.
    database.mutate(key(training, person), {}, lambda state: state.clear())
    assert case.client.get(report_url).status_code == 409
    assert not any(u['report_url'] for u in case.client.get(index_url(training)).json['units'])


def test_report_splits_revised_questions_pools_identical_ones_and_counts_blank_responses():
    from uv_session_report import summarize

    course, number = 'aps', 2
    current = uv.unit(course, number)['questions']
    previous = uv.unit(course, number, '20261024')['questions']
    changed = next(i for i, pair in enumerate(zip(current, previous)) if pair[0]['prompt'] != pair[1]['prompt'])
    same = next(i for i, pair in enumerate(zip(current, previous)) if pair[0] == pair[1])
    q = current[same]
    wrong = next(o['id'] for o in q['options'] if o['id'] != q['answer'])
    people = [
        {'id': 'current', 'uv_questionnaires': {course: {'2': submitted(course, number, uv.VERSION, {q['id']: wrong})}}},
        {'id': 'archived', 'uv_questionnaires': {course: {'2': submitted(course, number, '20261024', {q['id']: ''})}}},
        {'id': 'all-blank', 'uv_questionnaires': {course: {'2': submitted(course, number, uv.VERSION,
                                                                        {r['id']: '' for r in current})}}},
        {'id': 'pending', 'uv_questionnaire_attempts': {course: {'2': {'index': 4}}}},
        {'id': 'absent'},
    ]
    report = summarize(people, course, number)
    assert report.scores == [19, 19, 0]
    assert [p.status for p in report.participants][-2:] == ['En cours', 'Non commencé']
    joint, = [row for row in report.questions if row.number == same + 1]
    assert (joint.correct, joint.wrong, joint.blank, joint.total) == (0, 1, 2, 3)
    variants = [row for row in report.questions if row.number == changed + 1]
    assert [(row.prompt, row.correct, row.blank, row.versions) for row in variants] == [
        (previous[changed]['prompt'], 1, 0, {'20261024'}),
        (current[changed]['prompt'], 1, 1, {uv.VERSION})]


def test_dense_mixed_edition_report_keeps_every_question_answer_and_name_within_five_pages():
    from uv_session_report import summarize
    from uv_session_report_pdf import build

    # All twenty questions in this unit changed between the two archived banks.
    course, number = 'a3p', 6
    people = []
    for i in range(40):
        version = uv.VERSION if i % 2 else '20261024'
        result = submitted(course, number, version)
        people.append({'id': str(i), 'first_name': f'Camille-{i:02}', 'last_name': 'Desprès',
                       'uv_questionnaires': {course: {str(number): result}}})
    report = summarize(people, course, number)
    assert len(report.questions) == 40
    pdf = PdfReader(build(report, {'id': 'test', 'name': 'Session de démonstration'},
                          course, uv.unit(course, number), brand='Intégrale Academy', host=host))
    assert len(pdf.pages) <= 5
    text = ' '.join(' '.join(p.extract_text() for p in pdf.pages).split())
    assert all(f'Camille-{i:02}' in text for i in range(len(people)))
    for row in report.questions:
        assert ' '.join(row.prompt.split()) in text
        assert ' '.join(row.answer.split()) in text


def test_report_checks_tenant_before_results_and_photos(documents_case, monkeypatch):
    case, training, person, _, _ = documents_case
    route = f"/admin/sessions/{training['id']}/questionnaires-uv/2/rapport.pdf"
    assert host.app.test_client().get(route).status_code == 302
    with case.client.session_transaction() as auth:
        auth.update(admin_role='partner_admin', partner_id='another-partner')
    monkeypatch.setattr(uv, 'stored_trainee', lambda *args: pytest.fail('Unscoped result read'))
    assert case.client.get(route).status_code == 404
