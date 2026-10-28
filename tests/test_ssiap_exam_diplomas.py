import io
import json

import pytest
from pypdf import PdfReader

import app as services


BASE = '/api/admin/sessions/S1/ssiap-exam/diplomas'


@pytest.fixture
def case(monkeypatch, tmp_path):
    path = tmp_path / 'data.json'
    trainee = {'id':'T1', 'first_name':'Clément', 'last_name':'Vaillant', 'birth_date':'1993-09-16',
               'birth_city':'Sallanches', 'birth_country':'France', 'birth_department':'74',
               'ssiap_exam_status':'pending_results'}
    training = {'id':'S1', 'training_type':'SSIAP 1', 'name':'SSIAP OCTOBRE', 'exam_date':'2026-10-28', 'ssiap_exam_number':'VAR-2026-042',
                'trainees':[trainee, {**trainee, 'id':'T2','last_name':'ZAUTRE','ssiap_exam_status':'failed'},
                            {**trainee, 'id':'CANCELLED','registration_cancelled':True}]}
    path.write_text(json.dumps({'sessions':[training, {'id':'APS','training_type':'APS','trainees':[]}]}))
    monkeypatch.setattr(services, 'DATA_FILE', str(path))
    monkeypatch.setattr(services, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(services, 'SSIAP_DIPLOMA_LOCK_FILE', str(tmp_path / 'numbers.lock'))
    monkeypatch.setattr(services, 'BACKUP_SNAPSHOT_BEFORE_SAVE', False)
    monkeypatch.setattr(services, '_lookup_birth_department_code', lambda city: {'MAUBEUGE':'59'}.get(city,''))
    client = services.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role='admin')
    client.get(BASE)  # Complete the application's existing data normalization first.
    return client, path


def view(case):
    response = case[0].get(BASE)
    assert response.status_code == 200
    return response.json


def post(case, action, candidates=None, **extra):
    state = view(case)
    return case[0].post(BASE, json={'action':action, 'csrf':state['csrf'],
                                  'candidates':candidates or [], **extra})


def text(response):
    assert response.status_code == 200, response.data[:500]
    return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(response.data)).pages)


def test_review_scope_normalization_and_configured_exam_date(case):
    original = case[1].read_bytes()
    state = view(case)
    assert len(state['candidates']) == 2
    assert state['candidates'][0]['values']['birth_city'] == 'SALLANCHES'
    assert state['candidates'][0]['values']['last_name'] == 'VAILLANT'
    assert not state['candidates'][0]['missing']
    assert case[1].read_bytes() == original
    assert case[0].get(BASE.replace('S1', 'APS')).status_code == 404
    saved = json.loads(original)
    saved['sessions'][0]['ssiap_exam'] = {'config':{'date':'2026-11-02'}}
    case[1].write_text(json.dumps(saved))
    assert view(case)['candidates'][0]['values']['exam_date'] == '2026-11-02'


def test_atomic_save_results_and_birth_overrides(case):
    row = view(case)['candidates'][0]
    row['values'].update(result='certified', birth_city='maubeuge', birth_department='')
    result = post(case, 'save', [row])
    assert result.status_code == 200
    trainee = json.loads(case[1].read_text())['sessions'][0]['trainees'][0]
    assert trainee['ssiap_exam_status'] == 'certified'
    assert trainee['ssiap_diploma_birth_city'] == 'MAUBEUGE'
    assert trainee['ssiap_diploma_birth_department'] == '59'
    assert trainee['birth_city'] == 'Sallanches'
    assert 'ssiap_diploma_number' not in trainee
    # A stale form cannot overwrite a more recent result or corrected birthplace.
    assert post(case, 'save', [row]).status_code == 409


def test_invalid_batch_has_no_partial_changes(case):
    rows = view(case)['candidates']
    rows[0]['values']['result'] = 'certified'
    rows[1]['values']['birth_date'] = '1993-02-31'
    original = json.loads(case[1].read_text())['sessions'][0]['trainees']
    assert post(case, 'save', rows).status_code == 400
    assert json.loads(case[1].read_text())['sessions'][0]['trainees'] == original


def test_preview_uses_drafts_country_and_watermark_without_saving(case):
    original = case[1].read_bytes()
    row = view(case)['candidates'][0]
    row['values'].update(birth_city='Abidjan', birth_country="Côte d'Ivoire", birth_department='74')
    response = post(case, 'preview', [row], trainee_id='T1')
    content = text(response)
    assert "ABIDJAN (Côte d'Ivoire)" in content
    assert '16/09/1993' in content
    assert 'APERÇU - NON VALABLE' in content
    assert 'SALLANCHES' not in content
    assert case[1].read_bytes() == original
    assert 'no-store' in response.headers['Cache-Control']


def test_bulk_generation_only_certified_reuses_numbers_and_previews_do_not_allocate(case):
    rows = view(case)['candidates']
    rows[0]['values']['result'] = 'certified'
    assert post(case, 'save', rows).status_code == 200
    preview = post(case, 'preview')
    assert len(PdfReader(io.BytesIO(preview.data)).pages) == 1
    assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')
    first = post(case, 'generate')
    assert 'SALLANCHES (74)' in text(first)
    assert 'APERÇU - NON VALABLE' not in text(first)
    numbers = json.loads(first.headers['X-SSIAP-Diploma-Numbers'])
    assert set(numbers) == {'T1'}
    assert post(case, 'generate').headers['X-SSIAP-Diploma-Numbers'] == first.headers['X-SSIAP-Diploma-Numbers']
    assert post(case, 'generate', trainee_id='T2').status_code == 400


def test_incomplete_draft_saves_but_generation_is_blocked(case):
    row = view(case)['candidates'][0]
    row['values'].update(result='certified', birth_city='INCONNUE', birth_department='')
    assert post(case, 'save', [row]).status_code == 200
    assert 'département de naissance' in view(case)['candidates'][0]['missing']
    assert post(case, 'generate').status_code == 400
    assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')


def test_clearing_a_field_does_not_silently_restore_old_birth_data(case):
    row = view(case)['candidates'][0]
    row['values'].update(result='certified', birth_city='', birth_department='', birth_date='', exam_date='')
    assert post(case, 'save', [row]).status_code == 200
    stored = view(case)['candidates'][0]['values']
    assert stored['birth_city'] == stored['birth_date'] == stored['exam_date'] == ''
    assert post(case, 'generate').status_code == 400
    content = text(post(case, 'preview', trainee_id='T1'))
    assert 'SALLANCHES' not in content
    assert 'À renseigner' in content


def test_authentication_csrf_readonly_and_partner_scope(case):
    assert case[0].post(BASE, json={'action':'save'}).status_code == 403
    state = view(case)
    with case[0].session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert view(case)['read_only']
    assert post(case, 'save', state['candidates']).status_code == 403
    assert post(case, 'generate').status_code == 403
    assert case[0].get(BASE + '/preview?trainee_id=T1').status_code == 200
    stored = json.loads(case[1].read_text())
    stored['sessions'][0]['partner_id'] = 'other-centre'
    case[1].write_text(json.dumps(stored))
    assert case[0].get(BASE).status_code == 404
    with case[0].session_transaction() as session:
        session.clear()
    assert case[0].get(BASE).status_code in (302, 401)


def test_cancelled_and_nonpresented_candidates_are_excluded(case):
    assert post(case, 'preview', trainee_id='CANCELLED').status_code == 404
    assert post(case, 'generate', trainee_id='CANCELLED').status_code == 404
    stored = json.loads(case[1].read_text())
    stored['sessions'][0]['trainees'][0]['ssiap_exam_status'] = 'certified'
    stored['sessions'][0]['ssiap_exam'] = {'candidates':{'T1':{'included':False}}}
    case[1].write_text(json.dumps(stored))
    assert post(case, 'generate').status_code == 400
    assert post(case, 'generate', trainee_id='T1').status_code == 400


def test_foreign_country_precedes_even_stale_department_and_repeated_suffix():
    for city in ('Abidjan', 'Abidjan (74)', "Abidjan (Côte d'Ivoire)"):
        assert services._ssiap_birth_place_label({'birth_city':city, 'birth_country':"Côte d'Ivoire", 'birth_department':'74'}) == "ABIDJAN (Côte d'Ivoire)"


def test_afc_uses_its_ssiap_exam_date_for_diplomas(case):
    stored = json.loads(case[1].read_text())
    training = stored['sessions'][0]
    training.update(training_type='AFC', name='AFC OCTOBRE', ssiap_exam_date='2026-11-12')
    training['trainees'][0]['ssiap_exam_status'] = 'certified'
    case[1].write_text(json.dumps(stored))
    assert view(case)['candidates'][0]['values']['exam_date'] == '2026-11-12'
    assert '12/11/2026' in text(post(case, 'generate'))


def test_tab_is_present_only_in_ssiap_examination(case):
    assert 'data-exam-tab="diplomas"' in case[0].get('/admin/sessions/S1/trainees').text
    assert 'data-exam-tab="diplomas"' not in case[0].get('/admin/sessions/APS/trainees').text


def test_sdis_preview_uses_certified_drafts_and_does_not_reserve_numbers(case):
    row = view(case)['candidates'][0]
    row['values'].update(result='certified', birth_city='Abidjan', birth_country="Côte d'Ivoire")
    before = case[1].read_bytes()
    response = post(case, 'letter_preview', [row])
    content = text(response)
    for expected in ['DDSIS du Var', 'Groupement Prévention - Secrétariat', 'Allée de Vaugrenier',
                     '83490 LE MUY', '54 chemin du Carreou', '8323', '29/05/2026',
                     'VAR-2026-042', '28/10/2026', '16/09/1993', 'ABIDJAN', "Côte d'Ivoire",
                     'Clément VAILLANT', 'À générer', 'APERÇU']:
        assert expected in content
    assert 'ZAUTRE' not in content
    assert case[1].read_bytes() == before
    assert 'X-SSIAP-Diploma-Numbers' not in response.headers


def test_sdis_preview_without_certified_candidates_is_available_but_final_is_blocked(case):
    before = case[1].read_bytes()
    content = text(post(case, 'letter_preview'))
    assert 'Aucun candidat certifié renseigné' in content
    assert '28/10/2026' in content
    assert 'VAR-2026-042' in content
    assert 'VAILLANT' not in content.replace('Clément VAILLANT', '')
    assert 'APERÇU' in content
    assert case[1].read_bytes() == before
    assert post(case, 'letter').status_code == 400
    assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')


def test_sdis_final_letter_numbers_match_diplomas_and_repeated_letters(case):
    row = view(case)['candidates'][0]
    row['values']['result'] = 'certified'
    assert post(case, 'save', [row]).status_code == 200
    letter = post(case, 'letter')
    content = text(letter)
    assert 'APERÇU' not in content
    numbers = json.loads(letter.headers['X-SSIAP-Diploma-Numbers'])
    assert set(numbers) == {'T1'}
    assert numbers['T1'] in content
    assert post(case, 'letter').headers['X-SSIAP-Diploma-Numbers'] == letter.headers['X-SSIAP-Diploma-Numbers']
    diploma = post(case, 'generate')
    assert diploma.headers['X-SSIAP-Diploma-Numbers'] == letter.headers['X-SSIAP-Diploma-Numbers']
    assert 'VAR-2026-042' in text(diploma)
    assert len(PdfReader(io.BytesIO(letter.data)).pages[-1].images) >= 2  # real signature and stamp


def test_missing_exam_number_blocks_final_documents_without_allocating(case):
    stored = json.loads(case[1].read_text())
    stored['sessions'][0].pop('ssiap_exam_number')
    stored['sessions'][0]['trainees'][0]['ssiap_exam_status'] = 'certified'
    case[1].write_text(json.dumps(stored))
    assert view(case)['exam_number'] == ''
    for action in ('generate', 'letter'):
        response = post(case, action)
        assert response.status_code == 400
        assert 'numéro' in response.json['error']
        assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')
    assert 'À renseigner' in text(post(case, 'preview'))


def test_sdis_rejects_mismatched_dates_single_candidate_and_unauthorized_generation(case):
    row = view(case)['candidates'][0]
    row['values'].update(result='certified', exam_date='2026-11-01')
    assert post(case, 'save', [row]).status_code == 200
    assert post(case, 'letter').status_code == 400
    assert post(case, 'letter_preview', trainee_id='T1').status_code == 400
    assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')
    with case[0].session_transaction() as session:
        session['admin_role'] = 'viewer'
    assert post(case, 'letter').status_code == 403
    assert case[0].get(BASE + '/preview?document=letter').status_code == 200


def test_sdis_multipage_table_repeats_headings_and_preserves_all_names():
    from ssiap_diploma_documents import sdis_letter
    rows = [{'name':f'Madame Camille EXEMPLE-{i:02}', 'birth_date':'16/09/1993',
             'birth_place':"ABIDJAN (Côte d'Ivoire)", 'exam_date':'28/10/2026',
             'number':f'083-8323-1-2026-{i:05}'} for i in range(1,31)]
    pdf = PdfReader(sdis_letter(rows, {'exam_number':'VAR-2026-042'}, services.app.root_path))
    assert len(pdf.pages) >= 2
    content = '\n'.join(page.extract_text() for page in pdf.pages)
    for i in range(1,31):
        assert f'EXEMPLE-{i:02}' in content
        assert f'083-8323-1-2026-{i:05}' in content
    for page in pdf.pages:
        if 'EXEMPLE-' in page.extract_text():
            assert 'Candidat certifié' in page.extract_text()
    assert 'Clément VAILLANT' in pdf.pages[-1].extract_text()


def test_missing_letter_signature_cannot_allocate_numbers(case, monkeypatch):
    import ssiap_exam_pdf
    row = view(case)['candidates'][0]
    row['values']['result'] = 'certified'
    assert post(case, 'save', [row]).status_code == 200
    def unavailable(root):
        raise RuntimeError('Signature introuvable.')
    monkeypatch.setattr(ssiap_exam_pdf, 'signature_assets', unavailable)
    assert post(case, 'letter').status_code == 503
    assert not json.loads(case[1].read_text()).get('ssiap_diploma_sequences')
