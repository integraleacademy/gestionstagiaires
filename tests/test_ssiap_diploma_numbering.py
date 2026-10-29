import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pypdf import PdfReader

import app as services


BASE = '/api/admin/sessions/S1/ssiap-exam/diplomas'


@pytest.fixture
def numbered(monkeypatch, tmp_path):
    path = tmp_path / 'data.json'
    trainees = [{
        'id': f'T{i}', 'first_name': f'Camille{i}', 'last_name': 'EXEMPLE',
        'birth_date': '1993-09-16', 'birth_city': 'PARIS', 'birth_country': 'France',
        'birth_department': '75', 'ssiap_exam_status': 'certified',
        'ssiap_diploma_number': f'083-8323-1-2026-{i:05d}',
        'ssiap_diploma_issued_at': '2026-10-28T10:00:00Z',
    } for i in range(1, 12)]
    training = {'id': 'S1', 'training_type': 'SSIAP 1', 'name': 'SSIAP',
                'exam_date': '2026-10-28', 'ssiap_exam_number': 'VAR-2026-042',
                'trainees': trainees}
    path.write_text(json.dumps({'sessions': [training], 'ssiap_diploma_sequences': {'2026': 11}}))
    monkeypatch.setattr(services, 'DATA_FILE', str(path))
    monkeypatch.setattr(services, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(services, 'BACKUP_SNAPSHOT_BEFORE_SAVE', False)
    monkeypatch.setattr(services, 'BACKUP_MIN_INTERVAL_SECONDS', 10**9)
    monkeypatch.setattr(services, '_lookup_birth_department_code', lambda city: '75')
    client = services.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin')
    client.get(BASE)
    return client, path


def state(numbered):
    return json.loads(numbered[1].read_text())


def action(numbered, kind, **payload):
    csrf = numbered[0].get(BASE).json['csrf']
    return numbered[0].post(BASE, json={'action': kind, 'csrf': csrf, **payload})


def numbers(data):
    return {t['id']: t.get('ssiap_diploma_number', '') for t in data['sessions'][0]['trainees']}


def assert_ten_consecutive(data):
    actual = numbers(data)
    assert not actual.get('T6')
    assert sorted(value for value in actual.values() if value) == [f'083-8323-1-2026-{i:05d}' for i in range(1, 11)]
    assert actual['T1'].endswith('00001')
    assert actual['T5'].endswith('00005')
    assert actual['T7'].endswith('00006')
    assert actual['T11'].endswith('00010')
    assert data['ssiap_diploma_sequences']['2026'] == 10


@pytest.mark.parametrize('entry', ['diplomas', 'roster', 'excluded', 'cancelled', 'delete_api', 'delete_admin'])
def test_result_and_candidate_changes_close_the_gap(numbered, entry):
    client, _ = numbered
    before = client.get(BASE).json['candidates']
    target = next(row for row in before if row['id'] == 'T6')
    if entry == 'diplomas':
        target['values']['result'] = 'failed'
        response = action(numbered, 'save', candidates=[target])
        assert response.json['numbering_changed']
        assert next(row for row in response.json['candidates'] if row['id'] == 'T7')['number'].endswith('00006')
    elif entry in {'roster', 'cancelled'}:
        payload = {'ssiap_exam_status': 'failed'} if entry == 'roster' else {'registration_cancelled': True}
        response = client.post('/api/sessions/S1/stagiaires/T6/update', json=payload)
    elif entry == 'excluded':
        exam = client.get('/api/admin/sessions/S1/ssiap-exam').json
        response = client.post('/api/admin/sessions/S1/ssiap-exam', json={
            'csrf': exam['csrf'], 'revision': exam['revision'], 'action': 'candidate',
            'trainee_id': 'T6', 'candidate': {'included': False},
        })
    else:
        url = '/api/sessions/S1/trainees/T6/delete' if entry == 'delete_api' else '/admin/sessions/S1/stagiaires/T6/delete'
        response = client.post(url)
    assert response.status_code in (200, 302), response.data[:500]
    saved = state(numbered)
    assert_ten_consecutive(saved)
    assert client.get('/admin/sessions/S1/trainees/T6/ssiap-diploma').status_code == 404
    if not entry.startswith('delete'):
        withdrawn = next(t for t in saved['sessions'][0]['trainees'] if t['id'] == 'T6')
        assert 'ssiap_diploma_issued_at' not in withdrawn
        assert withdrawn['ssiap_diploma_number_history'][-1]['previous_number'].endswith('00006')
    shifted = next(t for t in saved['sessions'][0]['trainees'] if t['id'] == 'T7')
    assert shifted['ssiap_diploma_number_history'][-1]['previous_number'].endswith('00007')
    # A previously opened diploma form cannot restore a superseded number/result.
    stale = next(row for row in before if row['id'] == 'T7')
    assert action(numbered, 'save', candidates=[stale]).status_code == 409


def test_generation_repairs_existing_gap_and_letter_uses_same_numbers(numbered):
    client, path = numbered
    broken = state(numbered)
    broken['sessions'][0]['trainees'][5]['ssiap_exam_status'] = 'failed'
    path.write_text(json.dumps(broken))
    original = path.read_bytes()
    assert action(numbered, 'letter_preview').status_code == 200
    assert path.read_bytes() == original
    generated = action(numbered, 'generate')
    assert generated.status_code == 200
    assert_ten_consecutive(state(numbered))
    assigned = json.loads(generated.headers['X-SSIAP-Diploma-Numbers'])
    assert len(assigned) == 10
    assert len(PdfReader(io.BytesIO(generated.data)).pages) == 10
    for page in PdfReader(io.BytesIO(generated.data)).pages:
        assert '00011' not in page.extract_text()
    repeated = action(numbered, 'generate')
    assert repeated.headers['X-SSIAP-Diploma-Numbers'] == generated.headers['X-SSIAP-Diploma-Numbers']
    letter = action(numbered, 'letter')
    assert letter.status_code == 200
    assert json.loads(letter.headers['X-SSIAP-Diploma-Numbers']) == assigned
    content = ' '.join(page.extract_text() for page in PdfReader(io.BytesIO(letter.data)).pages)
    assert 'Camille6' not in content
    for number in assigned.values():
        assert number in content


def test_stale_unrelated_save_cannot_restore_removed_number_or_old_counter(numbered):
    stale = state(numbered)
    target = next(row for row in numbered[0].get(BASE).json['candidates'] if row['id'] == 'T6')
    target['values']['result'] = 'failed'
    assert action(numbered, 'save', candidates=[target]).status_code == 200
    stale['sessions'][0]['trainees'][0]['comment'] = 'Note ajoutée en parallèle'
    with services.app.test_request_context():
        services.save_data(stale)
    saved = state(numbered)
    assert_ten_consecutive(saved)
    assert saved['sessions'][0]['trainees'][5]['ssiap_exam_status'] == 'failed'
    assert saved['sessions'][0]['trainees'][0]['comment'] == 'Note ajoutée en parallèle'


def test_reconciliation_keeps_other_years_and_partners_separate(numbered):
    data = state(numbered)
    base = data['sessions'][0]
    later = copy.deepcopy(base)
    later.update(id='S2', trainees=[{**base['trainees'][0], 'id': 'LATER', 'ssiap_diploma_number': '083-8323-1-2026-00012'}])
    next_year = copy.deepcopy(later)
    next_year.update(id='S3', exam_date='2027-01-10', trainees=[{**later['trainees'][0], 'id': 'NEXT', 'ssiap_diploma_number': '083-8323-1-2027-00001'}])
    partner = copy.deepcopy(later)
    partner.update(id='OTHER', partner_id='OTHER', trainees=[{**later['trainees'][0], 'id': 'OTHER', 'ssiap_diploma_number': '083-8323-1-2026-00001'}])
    data['sessions'].extend([later, next_year, partner])
    base['trainees'][5]['ssiap_exam_status'] = 'failed'
    services._reconcile_ssiap_diploma_numbers(data, base)
    assert later['trainees'][0]['ssiap_diploma_number'].endswith('00011')
    assert next_year['trainees'][0]['ssiap_diploma_number'] == '083-8323-1-2027-00001'
    assert partner['trainees'][0]['ssiap_diploma_number'] == '083-8323-1-2026-00001'


@pytest.mark.parametrize('withdrawn', ['T1', 'T11'])
def test_first_or_last_number_is_also_released(numbered, withdrawn):
    response = numbered[0].post(f'/api/sessions/S1/stagiaires/{withdrawn}/update', json={'ssiap_exam_status': 'failed'})
    assert response.status_code == 200
    actual = numbers(state(numbered))
    assert not actual[withdrawn]
    assert sorted(n for n in actual.values() if n) == [f'083-8323-1-2026-{i:05d}' for i in range(1, 11)]


def test_new_certification_reuses_next_consecutive_number(numbered):
    client, _ = numbered
    assert client.post('/api/sessions/S1/stagiaires/T6/update', json={'ssiap_exam_status': 'failed'}).status_code == 200
    assert client.post('/api/sessions/S1/stagiaires/T6/update', json={'ssiap_exam_status': 'certified'}).status_code == 200
    assert not numbers(state(numbered))['T6']
    response = action(numbered, 'generate', trainee_id='T6')
    assert response.status_code == 200
    assert json.loads(response.headers['X-SSIAP-Diploma-Numbers'])['T6'].endswith('00011')


def test_exam_year_correction_releases_old_year_number(numbered):
    data = state(numbered)
    data['sessions'][0]['trainees'][5]['ssiap_diploma_exam_date'] = '2027-01-10'
    numbered[1].write_text(json.dumps(data))
    response = action(numbered, 'generate', trainee_id='T6')
    assert response.status_code == 200
    assert json.loads(response.headers['X-SSIAP-Diploma-Numbers'])['T6'] == '083-8323-1-2027-00001'
    saved = state(numbered)
    assert saved['ssiap_diploma_sequences'] == {'2026': 10, '2027': 1}
    assert numbers(saved)['T7'] == '083-8323-1-2026-00006'


def test_invalid_generation_leaves_existing_numbering_unchanged(numbered):
    data = state(numbered)
    data['sessions'][0]['trainees'][5]['ssiap_exam_status'] = 'failed'
    data['sessions'][0]['trainees'][0]['birth_date'] = ''
    numbered[1].write_text(json.dumps(data))
    original = numbers(state(numbered))
    assert action(numbered, 'generate').status_code == 400
    assert numbers(state(numbered)) == original
    assert state(numbered)['ssiap_diploma_sequences']['2026'] == 11


def test_concurrent_generation_does_not_duplicate_or_skip_numbers(numbered, monkeypatch):
    data = state(numbered)
    data['sessions'][0]['trainees'] = data['sessions'][0]['trainees'][:4]
    for trainee in data['sessions'][0]['trainees']:
        trainee.pop('ssiap_diploma_number')
    data['ssiap_diploma_sequences'] = {}
    numbered[1].write_text(json.dumps(data))
    barrier = Barrier(4)
    def generate(i):
        with services.app.test_request_context():
            barrier.wait(timeout=10)
            return services._reserve_ssiap_diploma_numbers('S1', f'T{i}')[1][0]['number']
    with ThreadPoolExecutor(max_workers=4) as pool:
        assigned = list(pool.map(generate, range(1, 5)))
    assert sorted(assigned) == [f'083-8323-1-2026-{i:05d}' for i in range(1, 5)]
    assert state(numbered)['ssiap_diploma_sequences']['2026'] == 4
