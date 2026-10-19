import copy
import datetime as dt
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import A4, landscape

import app as gestion
import ssiap_exam as exam


def sample_pdf(path, label, sideways=False):
    c = Canvas(str(path), pagesize=landscape(A4) if sideways else A4)
    c.drawString(70, 250, label)
    c.save()


@pytest.fixture
def case(monkeypatch, tmp_path):
    future = (dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=30)).isoformat()
    for label in ('IDENTITE_RECTO', 'IDENTITE_VERSO', 'SST', 'MEDICAL'):
        sample_pdf(tmp_path / (label + '.pdf'), label, label == 'IDENTITE_RECTO')
    trainee = {'id': 'T1', 'first_name': 'Camille', 'last_name': 'EXEMPLE', 'ssiap_exam_status': 'pending_results',
        'documents': [{'key':'id', 'file':'IDENTITE_RECTO.pdf', 'files':['IDENTITE_RECTO.pdf', 'IDENTITE_VERSO.pdf'], 'status':'CONFORME'},
                      {'key':'certificat_medical_ssiap', 'file':'MEDICAL.pdf', 'status':'CONFORME'}],
        'deliverables': {'carte_sst':'SST.pdf'}, 'convention_signature': {'status':'signed'}, 'cpf_amount':'980'}
    training = {'id':'S1', 'name':'SSIAP OCTOBRE', 'training_type':'SSIAP 1', 'date_start':'2026-10-12',
                'date_end':'2026-10-27', 'exam_date':future,
                'trainees':[trainee, {'id':'CANCELLED', 'last_name':'ANNULE', 'registration_cancelled':True}]}
    data = {'sessions':[training, {'id':'OTHER', 'training_type':'APS', 'trainees':[]}]}
    monkeypatch.setattr(gestion, 'load_data', lambda *a, **k: data)
    monkeypatch.setattr(gestion, 'save_data', Mock())
    monkeypatch.setattr(gestion, '_atomic_update_data', lambda fn: fn(data))
    monkeypatch.setattr(gestion, '_detokenize_path', lambda token: str(tmp_path / token))
    monkeypatch.setattr(gestion, '_partner_can_access_upload_token', lambda token: True)
    send = Mock(return_value={'ok':True, 'message_id':'test-delivery'})
    monkeypatch.setattr(gestion, 'brevo_send_email', send)
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session['admin_logged_in'] = True
        session['admin_role'] = 'admin'
    return client, data, training, trainee, send


BASE = '/api/admin/sessions/S1/ssiap-exam'


def view(case):
    response = case[0].get(BASE)
    assert response.status_code == 200
    return response.json


def configured(case):
    client, _, training, _, _ = case
    state = view(case)
    config = {**state['config'], 'time':'08:30', 'arrival_time':'08:00', 'end_time':'17:00',
              'jury':[{'id':'J1', 'first_name':'Alex', 'last_name':'JURY', 'role':'president',
                       'email':'jury@example.test', 'phone':'0400000000', 'company':'Structure exemple'}]}
    response = client.post(BASE, json={'action':'config', 'revision':state['revision'], 'config':config, 'csrf':state['csrf']})
    assert response.status_code == 200
    return view(case)


def preview(case, kind='invitation'):
    response = case[0].get(BASE + '/jury/J1/' + kind + '/preview')
    assert response.status_code == 200
    return response.json


def test_scope_dates_cancellations_and_files(case):
    data = view(case)
    assert len(data['candidates']) == 1 and data['excluded_count'] == 1
    assert all(d['available'] for d in data['candidates'][0]['documents'])
    assert 'paths' not in str(data['candidates'])
    assert case[0].get(BASE.replace('S1', 'OTHER')).status_code == 404
    assert exam.supported({'training_type':'APS', 'name':'AFC CANNES'})
    assert not exam.supported({'training_type':'APS', 'name':'APS'})
    assert not exam.settings({'training_type':'AFC', 'exam_date':'2026-11-01'})['date']
    assert exam.settings({'training_type':'AFC', 'ssiap_exam_date':'2026-11-02'})['date'] == '2026-11-02'
    case[4].assert_not_called()


def test_authorization_csrf_and_tenant_scope(case):
    client = case[0]
    assert client.post(BASE, json={'action':'config', 'config':{}}).status_code == 403
    with client.session_transaction() as session:
        session['admin_role'] = 'viewer'
    state = view(case)
    assert state['read_only']
    assert client.post(BASE, json={'csrf':state['csrf']}).status_code == 403
    assert client.post(BASE + '/mail/send', json={'csrf':state['csrf']}).status_code == 403
    case[2]['partner_id'] = 'another-centre'
    assert client.get(BASE).status_code == 404
    with client.session_transaction() as session:
        session.clear()
    assert client.get(BASE).status_code in (401, 302)


def test_config_preserves_trainee_data_and_rejects_stale_edits(case):
    before = copy.deepcopy(case[3])
    state = configured(case)
    assert case[3] == before
    assert case[1]['sessions'][1] == {'id':'OTHER', 'training_type':'APS', 'trainees':[]}
    response = case[0].post(BASE, json={'action':'config', 'config':state['config'], 'revision':0, 'csrf':state['csrf']})
    assert response.status_code == 409
    case[4].assert_not_called()


def test_signed_attestations_require_explicit_validation_and_jury_binding(case):
    state = configured(case)
    row = state['candidates'][0]
    candidate = {**row['candidate'], 'independence':True, 'ability':True, 'evaluation_date':'2026-10-19'}
    response = case[0].post(BASE, json={'action':'candidate', 'revision':state['revision'], 'trainee_id':'T1', 'candidate':candidate, 'csrf':state['csrf']})
    assert response.status_code == 200
    assert exam.candidate_settings(case[2], case[3])['independence']
    assert case[3]['ssiap_exam_status'] == 'pending_results'
    case[2]['ssiap_exam']['config']['jury'][0]['company'] = 'Autre structure'
    assert not exam.candidate_settings(case[2], case[3])['independence']
    assert exam.candidate_settings(case[2], case[3])['ability']


@pytest.mark.parametrize('patch', [{'grade':'NaN'}, {'grade':'21'}, {'grade':'-1'}, {'ability':True}, {'included':'true'}])
def test_invalid_evaluation_is_not_saved(case, patch):
    state = configured(case)
    before = copy.deepcopy(case[2])
    response = case[0].post(BASE, json={'action':'candidate', 'revision':state['revision'], 'trainee_id':'T1',
        'candidate':{**state['candidates'][0]['candidate'], **patch}, 'csrf':state['csrf']})
    assert response.status_code == 400 and case[2] == before


def test_pdf_order_multipage_identity_portrait_and_pending_results(case):
    state = configured(case)
    row = state['candidates'][0]
    response = case[0].get(row['dossier_url'])
    assert response.status_code == 200 and response.mimetype == 'application/pdf'
    assert 'no-store' in response.headers['Cache-Control']
    reader = PdfReader(io.BytesIO(response.data))
    assert len(reader.pages) == 8
    assert all(abs(float(p.mediabox.width) - A4[0]) < 1 and abs(float(p.mediabox.height) - A4[1]) < 1 for p in reader.pages)
    text = [page.extract_text() for page in reader.pages]
    assert 'Dossier examen' in text[0] and 'Camille EXEMPLE' in text[0]
    assert 'Fiche d’évaluation' in text[1]
    assert all(label in text[index] for index, label in enumerate(['IDENTITE_RECTO', 'IDENTITE_VERSO', 'SST', 'MEDICAL'], 2))
    assert 'PROJET' in text[6] and 'PROJET' in text[7]
    collective = PdfReader(io.BytesIO(case[0].get(state['collective_url']).data))
    assert 'EXEMPLE' in collective.pages[0].extract_text()
    assert 'ANNULE' not in collective.pages[0].extract_text()
    assert 'NON CERTIFIÉ' not in collective.pages[0].extract_text()
    case[4].assert_not_called()


def test_complete_dossier_has_real_stamp_and_signature(case):
    state = configured(case)
    row = state['candidates'][0]
    response = case[0].post(BASE, json={'action':'candidate', 'revision':state['revision'], 'trainee_id':'T1',
        'candidate':{**row['candidate'], 'independence':True, 'ability':True, 'evaluation_date':'2026-10-19'}, 'csrf':state['csrf']})
    assert response.status_code == 200
    reader = PdfReader(io.BytesIO(case[0].get(row['dossier_url']).data))
    for page in reader.pages[-2:]:
        assert 'PROJET' not in page.extract_text()
        assert 'Clément VAILLANT' in page.extract_text()
        assert len(page.images) >= 3  # logo, original signature and original centre seal


def test_missing_or_corrupt_piece_is_never_silently_omitted(case):
    case[3]['deliverables'] = {}
    state = view(case)
    assert not state['candidates'][0]['documents'][1]['available']
    response = case[0].get(state['candidates'][0]['dossier_url'])
    assert 'Pièce manquante' in ''.join(p.extract_text() for p in PdfReader(io.BytesIO(response.data)).pages)
    path = Path(gestion._detokenize_path('MEDICAL.pdf'))
    path.write_bytes(b'corrupt')
    response = case[0].get(state['candidates'][0]['dossier_url'])
    assert response.status_code == 422
    assert 'Certificat médical' in response.text


@pytest.mark.parametrize('kind', ['invitation', 'reminder'])
def test_mail_preview_send_exact_content_and_duplicate_protection(case, kind):
    state = configured(case)
    prepared = preview(case, kind)
    case[4].assert_not_called()
    assert '08:30' in prepared['text'] and '08:00' in prepared['text']
    assert 'Candidats présentés : 1' in prepared['text']
    payload = {'csrf':state['csrf'], 'preview_token':prepared['preview_token']}
    response = case[0].post(BASE + '/mail/send', json=payload)
    assert response.status_code == 200
    args, kwargs = case[4].call_args
    assert args == (prepared['to'], prepared['subject'], prepared['html'])
    assert kwargs['text_content'] == prepared['text']
    assert case[0].post(BASE + '/mail/send', json=payload).status_code == 409
    assert case[4].call_count == 1
    history = view(case)['history'][0]
    assert history['status'] == 'sent' and history['to'] == 'jury@example.test'


def test_changed_details_forged_preview_and_failure_are_not_marked_sent(case):
    state = configured(case)
    prepared = preview(case)
    case[2]['ssiap_exam']['config']['time'] = '09:00'
    assert case[0].post(BASE + '/mail/send', json={'csrf':state['csrf'], 'preview_token':prepared['preview_token']}).status_code == 409
    assert case[0].post(BASE + '/mail/send', json={'csrf':state['csrf'], 'preview_token':'forged'}).status_code == 409
    case[4].assert_not_called()
    prepared = preview(case)
    case[4].return_value = {'ok':False}
    assert case[0].post(BASE + '/mail/send', json={'csrf':state['csrf'], 'preview_token':prepared['preview_token']}).status_code == 502
    assert view(case)['history'][0]['status'] == 'failed'


def test_stale_legacy_save_retains_exam_state():
    latest = {'sessions':[{'id':'S', 'ssiap_exam':{'revision':3, 'mail_history':[{'status':'sent'}]}}]}
    stale = {'sessions':[{'id':'S', 'ssiap_exam':{'revision':1}, 'name':'Updated name'}]}
    exam.preserve_state(stale, latest)
    assert stale['sessions'][0]['ssiap_exam'] == latest['sessions'][0]['ssiap_exam']
    assert stale['sessions'][0]['name'] == 'Updated name'
    assert stale['sessions'][0]['ssiap_exam'] is not latest['sessions'][0]['ssiap_exam']


def test_session_button_present_only_for_ssiap_and_afc(case):
    response = case[0].get('/admin/sessions/S1/trainees')
    assert response.status_code == 200
    assert 'id="btnSsiapExam"' in response.text and 'ssiap-exam.js' in response.text
    response = case[0].get('/admin/sessions/OTHER/trainees')
    assert response.status_code == 200
    assert 'id="btnSsiapExam"' not in response.text
