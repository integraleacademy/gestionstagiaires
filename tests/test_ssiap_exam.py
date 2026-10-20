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
    assert 'Dossier examen' in text[0] and 'Camille EXEMPLE' in ' '.join(text[0].split())
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


def test_portrait_accents_and_official_identity_in_all_generated_pages(case, tmp_path):
    import fitz
    from PIL import Image
    configured(case)
    case[3].update(first_name='Stéphane', identity_photo='portrait.png')
    Image.new('RGB', (350, 450), '#c97850').save(tmp_path / 'portrait.png')
    response = case[0].get(view(case)['candidates'][0]['dossier_url'])
    with fitz.open(stream=response.data, filetype='pdf') as doc:
        assert 'Stéphane' in doc[0].get_text()
        photo = next(im for im in doc[0].get_images() if im[2:4] == (350, 450))
        rect = doc[0].get_image_rects(photo[0])[0]
        assert rect.x0 > 420 and rect.y0 > 290 and rect.y1 < 425
        illustration = next(im for im in doc[0].get_images() if im[2:4] == (1184, 1328))
        illustration_rect = doc[0].get_image_rects(illustration[0])[0]
        assert illustration_rect.x0 > 350 and illustration_rect.y1 < 270
        assert not illustration_rect.intersects(rect)
        for page in doc:
            assert 'Stéphane' in page.get_text() and 'Stephane' not in page.get_text()
        for page in (doc[-1], doc[-2]):
            text = page.get_text()
            assert all(value in text for value in ['840 899 884 00026', '93830600283', '8559A', 'DREETS', 'RCS Fréjus'])
    # Missing photos remain explicit; unreadable files never break the candidate dossier.
    (tmp_path / 'portrait.png').write_bytes(b'not-an-image')
    response = case[0].get(view(case)['candidates'][0]['dossier_url'])
    assert response.status_code == 200
    assert 'Photo' in PdfReader(io.BytesIO(response.data)).pages[0].extract_text()


def test_photo_token_access_is_checked(case, monkeypatch, tmp_path):
    from PIL import Image
    Image.new('RGB', (35, 45)).save(tmp_path / 'portrait.png')
    case[3]['identity_photo'] = 'portrait.png'
    assert exam.photo_path(gestion, case[3])
    monkeypatch.setattr(gestion, '_partner_can_access_upload_token', lambda token: False)
    assert exam.photo_path(gestion, case[3]) == ''


@pytest.mark.parametrize('candidate_count,jury_count', [(12, 1), (12, 3), (15, 2)])
def test_attendance_keeps_candidates_and_jury_on_one_page(case, candidate_count, jury_count):
    import fitz
    state = configured(case)
    case[2]['trainees'] += [{'id':str(i), 'first_name':'Élodie', 'last_name':f'CANDIDAT{i:02d}'}
                           for i in range(candidate_count - 1)]
    jury = case[2]['ssiap_exam']['config']['jury']
    jury.extend({**jury[0], 'id':f'J{i}', 'first_name':'Chloé', 'last_name':f'JURY{i}', 'role':'member'}
                for i in range(2, jury_count + 1))
    response = case[0].get(state['attendance_url'])
    assert response.status_code == 200
    with fitz.open(stream=response.data, filetype='pdf') as document:
        assert len(document) == 1
        page = document[0]
        text = page.get_text()
        assert all(value in text for value in ['Camille EXEMPLE', 'Alex JURY', 'Structure exemple',
                                              'Matin', 'Après-midi', '93830600283'])
        assert 'ANNULE' not in text
        for label in ['Camille EXEMPLE', 'Alex JURY'] + [f'CANDIDAT{i:02d}' for i in range(candidate_count - 1)] + [f'JURY{i}' for i in range(2, jury_count + 1)]:
            assert text.count(label) == 1
            assert page.search_for(label)[0].y1 < float(page.rect.height) - 110
    case[4].assert_not_called()


def test_attendance_paginates_oversized_groups_without_a_separate_jury_page(case):
    state = configured(case)
    case[2]['trainees'] += [{'id':str(i), 'first_name':'Élodie', 'last_name':f'CANDIDAT{i:02d}'} for i in range(25)]
    case[2]['ssiap_exam']['candidates'] = {'T1':{'included':False}}
    url = state['attendance_url']
    response = case[0].get(url)
    assert response.status_code == 200 and response.headers['Content-Disposition'].startswith('inline;')
    assert 'no-store' in response.headers['Cache-Control']
    doc = PdfReader(io.BytesIO(response.data))
    assert len(doc.pages) == 2
    assert 'CANDIDAT24' in doc.pages[-1].extract_text() and 'Alex JURY' in doc.pages[-1].extract_text()
    text = '\n'.join(p.extract_text() for p in doc.pages)
    assert 'ANNULE' not in text and 'Camille' not in text
    assert 'Élodie' in text and 'Alex JURY' in text and 'Structure exemple' in text
    assert 'Matin' in text and 'Après-midi' in text
    for i in range(25):
        assert text.count(f'CANDIDAT{i:02d}') == 1
    assert case[0].get(url+'?download=1').headers['Content-Disposition'].startswith('attachment;')
    case[2]['partner_id'] = 'other-centre'
    assert case[0].get(url).status_code == 404


def test_reminder_language_and_automatic_schedule(case):
    state = configured(case)
    content = preview(case, 'reminder')
    assert 'Jury d’examen' in content['subject'] and 'Jury d’examen' in content['html']
    assert 'rendez-vous' not in (content['html'] + content['text']).lower()
    assert 'rdv' not in (content['html'] + content['text']).lower()
    plan = state['automatic_reminders']
    assert plan['time'] == '09:00' and plan['timezone'] == 'Europe/Paris'
    assert plan['date'] == (dt.date.fromisoformat(state['config']['date'])-dt.timedelta(days=7)).isoformat()
    assert plan['members']['J1']['status'] == 'scheduled'
    case[4].assert_not_called()


def test_manual_send_cannot_race_with_automatic_reservation(case):
    state = configured(case)
    content = preview(case, 'reminder')
    case[2]['ssiap_exam']['mail_history'] = [{'id':'auto', 'kind':'reminder', 'source':'automatic_j7',
        'to':'jury@example.test', 'status':'sending', 'exam_date':state['config']['date']}]
    response = case[0].post(BASE+'/mail/send', json={'csrf':state['csrf'],'preview_token':content['preview_token']})
    assert response.status_code == 409
    case[4].assert_not_called()
