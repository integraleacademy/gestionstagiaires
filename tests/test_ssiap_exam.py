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


def test_candidate_controls_only_exam_inclusion(case):
    state = configured(case)
    response = case[0].post(BASE, json={'action':'candidate', 'revision':state['revision'], 'trainee_id':'T1',
        'candidate':{'included':False, 'grade':'19', 'independence':False}, 'csrf':state['csrf']})
    assert response.status_code == 200
    assert exam.candidate_settings(case[2], case[3]) == {'included':False}
    assert case[3]['ssiap_exam_status'] == 'pending_results'
    text = PdfReader(io.BytesIO(case[0].get(view(case)['collective_url']).data)).pages[0].extract_text()
    assert 'EXEMPLE' not in text


@pytest.mark.parametrize('value', ['true', None, 1])
def test_invalid_inclusion_is_not_saved(case, value):
    state = configured(case)
    before = copy.deepcopy(case[2])
    response = case[0].post(BASE, json={'action':'candidate', 'revision':state['revision'], 'trainee_id':'T1',
        'candidate':{'included':value}, 'csrf':state['csrf']})
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
    assert all(state['config']['approval'] in page_text for page_text in text)
    assert response.headers['Content-Disposition'].startswith('inline;')
    assert case[0].get(row['dossier_url'] + '?download=1').headers['Content-Disposition'].startswith('attachment;')
    assert 'Dossier examen' in text[0] and 'Camille EXEMPLE' in text[0]
    assert 'FICHE D’EVALUATION' in text[1]
    assert all(label in text[index] for index, label in enumerate(['IDENTITE_RECTO', 'IDENTITE_VERSO', 'SST', 'MEDICAL'], 2))
    assert 'PROJET' not in text[6] and 'PROJET' not in text[7]
    collective = PdfReader(io.BytesIO(case[0].get(state['collective_url']).data))
    assert 'EXEMPLE' in collective.pages[0].extract_text()
    assert 'ANNULE' not in collective.pages[0].extract_text()
    assert 'NON CERTIFIÉ' not in collective.pages[0].extract_text()
    case[4].assert_not_called()


def test_complete_dossier_has_real_stamp_and_signature(case):
    # Signed automatically, including sessions without a jury or candidate validation.
    state = view(case)
    row = state['candidates'][0]
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
    latest = {'ssiap_jury_directory':{'J1':{'email':'jury@example.test'}}, 'sessions':[{'id':'S', 'ssiap_exam':{'revision':3, 'mail_history':[{'status':'sent'}]}}]}
    stale = {'sessions':[{'id':'S', 'ssiap_exam':{'revision':1}, 'name':'Updated name'}]}
    exam.preserve_state(stale, latest)
    assert stale['ssiap_jury_directory'] == latest['ssiap_jury_directory']
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


def test_directory_reusable_across_sessions_and_keeps_snapshots(case):
    first = configured(case)
    assert first['directory'][0]['email'] == 'jury@example.test'
    old_jury = copy.deepcopy(case[2]['ssiap_exam']['config']['jury'])
    other = {'id':'S2','training_type':'AFC','trainees':[], 'ssiap_exam_date':case[2]['exam_date']}
    case[1]['sessions'].append(other)
    response = case[0].get(BASE.replace('S1','S2'))
    state = response.json
    assert state['config']['jury'] == [] and len(state['directory']) == 1
    member = dict(state['directory'][0], phone='0412345678')
    config = dict(state['config'], jury=[member])
    assert case[0].post(BASE.replace('S1','S2'),json={'action':'config','revision':0,'csrf':state['csrf'],'config':config}).status_code == 200
    assert view(case)['directory'][0]['phone'] == '0412345678'
    assert case[2]['ssiap_exam']['config']['jury'] == old_jury
    assert len(view(case)['directory']) == 1
    old_state = view(case)
    case[0].post(BASE, json={'action':'config','revision':old_state['revision'],'csrf':old_state['csrf'],'config':dict(old_state['config'], time='09:00')})
    assert view(case)['directory'][0]['phone'] == '0412345678'
    # Existing exam juries are discoverable even before any directory write.
    case[1].pop('ssiap_jury_directory')
    assert len(view(case)['directory']) == 1
    case[1]['sessions'].append({'id':'FOREIGN','partner_id':'external-centre','ssiap_exam':{'config':{'jury':[dict(member,id='FOREIGN',email='secret@example.test')]}}})
    assert len(view(case)['directory']) == 1


def test_mail_status_each_kind_failure_retry_and_recipient_change(case):
    state = configured(case)
    assert state['mail_status']['J1']['invitation']['status'] == 'not_sent'
    assert state['mail_status']['J1']['reminder']['status'] == 'not_sent'
    for kind in ('invitation', 'reminder'):
        prepared = preview(case,kind)
        case[0].post(BASE+'/mail/send',json={'csrf':state['csrf'],'preview_token':prepared['preview_token']})
        assert view(case)['mail_status']['J1'][kind]['last_sent_at']
    case[4].return_value = {'ok':False}
    prepared = preview(case)
    case[0].post(BASE+'/mail/send',json={'csrf':state['csrf'],'preview_token':prepared['preview_token']})
    status = view(case)['mail_status']['J1']['invitation']
    assert status['status'] == 'failed' and status['last_sent_at'] and status['sent_count'] == 1
    case[2]['ssiap_exam']['config']['jury'][0]['email'] = 'new@example.test'
    assert view(case)['mail_status']['J1']['invitation']['status'] == 'not_sent'
    assert len(view(case)['history']) == 3


def test_official_pv_keeps_jury_assessment_areas_blank_even_with_legacy_values(case):
    import fitz
    state = configured(case)
    case[2]['ssiap_exam']['candidates']={'T1':{'grade':'19.75','written':'valid','practical':'fit','reason':'LEGACY_DECISION'}}
    case[3]['ssiap_exam_status']='certified'
    pdf = case[0].get(state['candidates'][0]['pv_url']).data
    dossier = case[0].get(state['candidates'][0]['dossier_url']).data
    individual = fitz.open(stream=pdf,filetype='pdf')
    combined = fitz.open(stream=dossier,filetype='pdf')
    assert individual[0].get_pixmap().samples == combined[1].get_pixmap().samples
    text=individual[0].get_text()
    assert '19.75' not in text and 'LEGACY_DECISION' not in text
    assert 'BENSAILA' not in text and 'ADEM' not in text and '08/06/2022' not in text
    assert 'EXEMPLE' in text and 'Camille' in text
    assert 'Alex JURY' in text and 'Structure exemple' in text
    assert 'Clément VAILLANT' in text and state['config']['approval'] in text
    # The assessment and appraisal areas remain pixel-identical to the supplied form.
    template=fitz.open(str(Path(gestion.app.root_path)/'templates_word/ssiap_exam/pv_individual_ssiap1.pdf'))
    rect=fitz.Rect(0,365,595,658)
    assert individual[0].get_pixmap(clip=rect).samples == template[0].get_pixmap(clip=rect).samples


def test_collective_repeats_original_14_places_without_changing_table(case):
    import fitz
    from ssiap_exam_pdf import collective
    state = configured(case)
    trainees=[dict(case[3],first_name=f'Personne{i}',last_name=f'NOM{i}',ssiap_exam_status='certified') for i in range(29)]
    doc=fitz.open(stream=collective(case[2],trainees,state['config'],gestion.app.root_path),filetype='pdf')
    assert len(doc)==3
    assert all('PROCES VERBAL' in page.get_text() for page in doc)
    assert 'NOM13' in doc[0].get_text() and 'NOM14' not in doc[0].get_text()
    assert 'NOM28' in doc[2].get_text()
    assert all('GEFFROY' not in page.get_text() and 'BENSAILA' not in page.get_text() for page in doc)
    template=fitz.open(str(Path(gestion.app.root_path)/'templates_word/ssiap_exam/pv_collective_ssiap1.pdf'))
    results_column=fitz.Rect(365,242,570,520)
    assert doc[0].get_pixmap(clip=results_column).samples == template[0].get_pixmap(clip=results_column).samples


def test_pvs_share_contact_approval_and_centre_signatures(case):
    import fitz
    state = configured(case)
    config = case[2]['ssiap_exam']['config']
    config['contact_email'] = 'centre@example.test'
    config['contact_phone'] = '04 11 22 33 44'
    config['jury'].append(dict(config['jury'][0], id='J2', role='member', first_name='Marie', last_name='MEMBRE'))
    for kind, url in [('individual', state['candidates'][0]['pv_url']), ('collective', state['collective_url'])]:
        response = case[0].get(url)
        assert response.headers['Content-Disposition'].startswith('inline;')
        document = fitz.open(stream=response.data, filetype='pdf')
        for page in document:
            text = page.get_text()
            assert config['contact_email'] in text and config['contact_phone'] in text
            assert config['approval'] in text
            assert 'integralesecuriteformations@gmail.com' not in text and 'ecole@integraleacademy.com' not in text
            assert 'Alex JURY' in text and 'Marie MEMBRE' in text
            images = page.get_images(full=True)
            for dimensions in [(1605, 543), (283, 158)]:
                asset = next(image for image in images if image[2:4] == dimensions)
                bounds = page.get_image_rects(asset[0])[0]
                if kind == 'individual':
                    assert bounds.x0 >= 394 and bounds.y0 >= 691 and bounds.y1 <= 794
                else:
                    assert bounds.y0 >= 777 and bounds.y1 <= 821


def test_attestations_have_one_centered_title_and_both_required_texts(case):
    import fitz
    state = configured(case)
    document = fitz.open(stream=case[0].get(state['candidates'][0]['dossier_url']).data, filetype='pdf')
    for page in list(document)[-2:]:
        title = page.search_for('Attestation')
        assert len(title) == 1
        assert abs((title[0].x0 + title[0].x1) / 2 - page.rect.width / 2) < 1
        assert state['config']['approval'] in page.get_text()
        assert 'Clément VAILLANT' in page.get_text()
    assert 'même entreprise ou structure' in document[-2].get_text()
    ability_text = ' '.join(document[-1].get_text().split())
    assert 'main courante' in ability_text and 'alerter les secours' in ability_text


def test_mail_layout_escapes_content_and_preserves_all_exam_details(case):
    state = configured(case)
    case[2]['ssiap_exam']['config']['instructions']='<script>alert(1)</script> & accès parking'
    for kind in ('invitation','reminder'):
        mail=preview(case,kind)
        assert '<script>' not in mail['html'] and '&lt;script&gt;' in mail['html']
        assert 'DATE DE L’EXAMEN' in mail['html'] and 'DÉBUT DES ÉPREUVES' in mail['html']
        assert '08:30' in mail['html'] and '17:00' in mail['html']
        assert 'mailto:' in mail['html'] and 'maps/search/' in mail['html']
        assert 'déjà confirmé' in mail['html'] if kind=='reminder' else 'Confirmer ma présence' in mail['html']
    case[4].assert_not_called()
