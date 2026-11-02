"""Render the real admin/public pages and route verified callbacks to the queue."""
import copy
import io
from unittest.mock import Mock

from lxml import html
from pypdf import PdfReader
import pytest

import app as host
import exam_retakes as retakes
from exam_retakes_documents import build_convention


@pytest.fixture
def real_app(monkeypatch,tmp_path):
    monkeypatch.setattr(host,'PERSIST_DIR',str(tmp_path))
    monkeypatch.setattr(host.app,'testing',True)
    monkeypatch.setattr(retakes,'today',lambda:'2026-10-30')
    person={'id':'T1','first_name':'Camille','last_name':'TEST','email':'test@example.test','phone':'0612345678',
            'address':'1 rue du Test','zip_code':'83480','city':'Puget-sur-Argens','birth_date':'1990-01-01','public_token':'PUB-T1'}
    source={'id':'S1','name':'APS octobre','training_type':'APS','date_start':'2026-09-01','date_end':'2026-10-09','exam_date':'2026-10-12','trainees':[person]}
    target={'id':'S2','name':'APS décembre','training_type':'APS','date_start':'2026-11-03','date_end':'2026-12-08','exam_date':'2026-12-09','trainees':[]}
    data={'sessions':[source,target]}
    monkeypatch.setattr(host,'load_data',lambda **kw:copy.deepcopy(data))
    monkeypatch.setattr(host,'save_data',Mock())
    monkeypatch.setattr(host,'fetch_cnapsv3_tracking_requests',lambda:([],''))
    monkeypatch.setattr(host,'_remember_admin_trainee_consultation',lambda *a:None)
    client=host.app.test_client()
    with client.session_transaction() as s:s.update(admin_logged_in=True,admin_role='admin')
    return client,data


def create(real_app,**changes):
    client,_=real_app
    csrf=client.get('/api/sessions/S1/stagiaires/T1/rattrapages').json['csrf']
    response=client.post('/api/sessions/S1/stagiaires/T1/rattrapages',json={
        'csrf':csrf,'kind':'APS','target_session':'S2','exam_date':'2026-12-09','no_days':True,
        'location':'Intégrale Academy, Puget-sur-Argens','exam_price':'80','day_price':'90',**changes})
    assert response.status_code==200,response.json
    return retakes.Store(host).get(response.json['record']['id'])


def test_button_and_modal_render_in_real_trainee_sheet(real_app):
    client,_=real_app
    response=client.get('/admin/sessions/S1/stagiaires/T1')
    assert response.status_code==200
    page=html.fromstring(response.data)
    assert len(page.xpath('//button[@id="retakeOpen"]'))==1
    assert len(page.xpath('//dialog[@id="retakeDialog"]'))==1
    assert page.xpath('//input[@type="checkbox" and @name="convocation_manual" and not(@checked)]')


def test_preparation_defaults_use_receiving_session(real_app):
    client,_=real_app
    values=client.get('/api/sessions/S1/stagiaires/T1/rattrapages').json
    assert values['location']=='Intégrale Academy 54 chemin du Carreou 83480 PUGET SUR ARGENS'
    assert values['defaults'][0]['sessions'][0]['preparation_days']==[{'date':'2026-12-07'},{'date':'2026-12-08'}]


@pytest.mark.parametrize('end,exam,expected',[
    ('2026-11-16','2026-11-17',['2026-11-13','2026-11-16']),
    ('2026-11-12','2026-11-13',['2026-11-10','2026-11-12']),
    ('2026-12-09','2026-12-09',['2026-12-07','2026-12-08']),
])
def test_preparation_days_exclude_weekends_holidays_and_exam(real_app,end,exam,expected):
    session={'training_type':'APS','date_start':'2026-11-02','date_end':end,'exam_date':exam}
    assert [d['date'] for d in retakes.preparation_days(host,session,'APS')]==expected


def test_roster_is_highlighted_without_a_normal_trainee_row(real_app):
    client,data=real_app
    row=create(real_app);row.update(status='confirmed',signed_at=retakes.now(),confirmed_at=retakes.now())
    retakes.Store(host).save(row)
    response=client.get('/admin/sessions/S2/trainees')
    assert response.status_code==200
    page=html.fromstring(response.data)
    retake_rows=page.xpath('//tr[@class="exam-retake-roster"]')
    assert len(retake_rows)==1 and 'Camille TEST' in retake_rows[0].text_content()
    assert 'Rattrapage examen' in retake_rows[0].text_content()
    links = {a.text_content(): a.get('href') for a in retake_rows[0].xpath('.//a')}
    assert links['Prévisualiser la convocation'] == '/admin/rattrapages/' + row['id'] + '/convocation.pdf'
    assert links['Gérer l’envoi'].endswith('/S1/stagiaires/T1#rattrapage')
    assert not page.xpath('//tr[@data-trainee-id="T1"]')
    assert data['sessions'][1]['trainees']==[]


def test_public_page_displays_only_its_retakes(real_app):
    client,_=real_app
    row=create(real_app,exam_price='60',day_price='70',no_days=False,days=[{'date':'2026-12-07'},{'date':'2026-12-08'}])
    row.update(status='confirmed',signed_at=retakes.now(),payment_status='paid',paid_cents=row['total_cents'],
               confirmed_at=retakes.now(),emails={'convocation':{'sent_at':retakes.now()}})
    retakes.Store(host).save(row)
    response=client.get('/espace/PUB-T1')
    assert response.status_code==200
    page=html.fromstring(response.data)
    section=page.xpath('//section[@id="rattrapage"]')[0]
    assert '09/12/2026' in section.text_content()
    assert 'Convention signée' in section.text_content()
    assert section.xpath('.//a[contains(., "Ma convocation à l’examen")]/@href') == [
        '/espace/PUB-T1/rattrapages/' + row['id'] + '/convocation.pdf']
    assert 'Votre participation au rattrapage est confirmée.' in section.text_content()
    assert '12/10/2026' in section.text_content()
    assert 'Remise de 20,00 € (25 %)' in section.text_content()
    assert 'Remise de 40,00 € (22,22 %)' in section.text_content()
    assert 'Total des remises commerciales : 60,00 €' in section.text_content()


def test_qonto_and_yousign_webhooks_require_auth_and_do_not_trust_paid_payload(real_app,monkeypatch):
    client,_=real_app
    row=create(real_app);row.update(status='payment',invoice_id='invoice-test',request_id='request-test',next_attempt=9999999999)
    store=retakes.Store(host);store.save(row)
    monkeypatch.setattr(host,'_verify_qonto_webhook_signature',lambda raw:True)
    monkeypatch.setattr(host,'_verify_yousign_webhook_signature',lambda raw:True)
    remote=Mock(side_effect=AssertionError('Callback must only enqueue provider verification'))
    monkeypatch.setattr(host,'get_qonto_invoice',remote)
    payload={'event':'v1/client-invoices.updated','data':{'id':'invoice-test','status':'paid'}}
    response=client.post('/api/webhooks/qonto',json=payload)
    assert response.status_code==200 and response.json['queued']
    assert store.get(row['id'])['status']=='payment'
    remote.assert_not_called()
    response=client.post('/webhooks/yousign',json={'event_name':'signature_request.done','data':{'signature_request':{'id':'request-test','status':'done'}}})
    assert response.status_code==200 and response.json['queued']
    monkeypatch.setattr(host,'_verify_yousign_webhook_signature',lambda raw:False)
    assert client.post('/webhooks/yousign',json={}).status_code==401


def test_invalid_merchant_and_amount_cannot_confirm_invoice():
    from exam_retakes_workflow import invoice_assert
    row={'id':'abc','client_id':'client','total_cents':8000}
    valid={'id':'i','client':{'id':'client'},'purchase_order':'RET-abc','total_amount':{'currency':'EUR','value':'80.00'}}
    invoice_assert(row,valid)
    for change in ({'client_id':'other'},{'purchase_order':'other'},{'currency':'USD'},{'total_amount':{'value':'79.00','currency':'EUR'}}):
        with pytest.raises(retakes.RetakeError):invoice_assert(row,{**valid,**change})


@pytest.mark.parametrize('training,kind,exam,day',[
    ('APS','APS','80.00','90.00'),('A3P','A3P','80.00','90.00'),
    ('SSIAP 1','SSIAP 1','80.00',''),('SSIAP 2','SSIAP 2','',''),
    ('DIRIGEANT','DESP','80.00',''),('DESP','DESP','80.00',''),
    ('CHAUFFEUR VTC','VTC pratique','150.00',''),('VTC','VTC théorie','',''),
    ('BTS','BTS','',''),('DIRIGEANT VAE','DIRIGEANT VAE','',''),
])
def test_actual_formation_contract_defaults(training,kind,exam,day):
    values=retakes.prices(host,{'training_type':training},{},kind)
    assert values['exam_price']==exam and values['day_price']==day


def test_combined_afc_offers_separate_exam_dates():
    source={'training_type':'APS + SSIAP 1','afc_enabled':True,'exam_date':'2026-12-01','ssiap_exam_date':'2026-12-03'}
    assert host.afc_schedule.enabled(source)
    assert set(retakes.components(host,source))=={'APS','SSIAP 1'}
    assert retakes.exam_date(host,source,'APS')=='2026-12-01'
    assert retakes.exam_date(host,source,'SSIAP 1')=='2026-12-03'


@pytest.fixture
def confirmed_ssiap(real_app, monkeypatch):
    client, data = real_app
    source, target = data['sessions']
    source.update(training_type='SSIAP 1', name='SSIAP octobre')
    original = source['trainees'][0]
    original.update(ssiap_exam_status='failed', birth_city='Sallanches', birth_department='74', birth_country='France')
    target.update(training_type='SSIAP 1', name='SSIAP décembre', ssiap_exam_number='VAR-TEST',
                  trainees=[{'id':'REG', 'first_name':'Alex', 'last_name':'ORDINAIRE'},
                            {'id':'ANN', 'first_name':'Dominique', 'last_name':'ANNULE', 'registration_cancelled':True}])
    days = [{'date':'2026-12-07', 'start':'08:30', 'end':'16:30', 'topic':'Révision pratique'},
            {'date':'2026-12-08', 'start':'09:00', 'end':'12:00', 'topic':'Préparation orale'}]
    row = create(real_app, kind='SSIAP 1', no_days=False, days=days, exam_time='08:00',
                 failed_exam_details='Épreuve pratique', notes='Accueil au bâtiment principal.')
    row.update(status='confirmed', signed_at=retakes.now(), payment_status='paid', paid_cents=row['total_cents'],
               confirmed_at=retakes.now(), emails={'convocation':{'sent_at':retakes.now()}})
    retakes.Store(host).save(row)
    monkeypatch.setattr(host, '_atomic_update_data', lambda action:action(data))
    return client, data, row


def pdf_text(response):
    assert response.status_code == 200, response.data[:160]
    return [page.extract_text() for page in PdfReader(io.BytesIO(response.data)).pages]


def test_enriched_invitation_replaces_preview_without_repeating_the_first_send(confirmed_ssiap):
    client, _, row = confirmed_ssiap
    store = retakes.Store(host)
    old = store.root / (row['id'] + '-convocation.pdf')
    old.write_bytes(b'old delivery kept for audit')
    record = client.get('/api/sessions/S1/stagiaires/T1/rattrapages?status=1').json['records'][0]
    assert record['convocation_updated'] and record['convocation_sent_at']
    text = ' '.join(pdf_text(client.get(record['convocation_url'])))
    for field in ('SSIAP octobre', '12/10/2026', 'Épreuve pratique', '09/12/2026', '08:00', '07/12/2026',
                  'Révision pratique', '08/12/2026', '09:00', 'Préparation orale', 'Accueil au bâtiment principal.'):
        assert field in text
    assert old.read_bytes() == b'old delivery kept for audit'
    assert store.get(row['id'])['emails'] == row['emails']


def test_confirmed_candidate_on_exam_and_exact_preparation_days(confirmed_ssiap):
    client, data, row = confirmed_ssiap
    source, target = data['sessions']
    extra = {**source['trainees'][0], 'id':'T2','first_name':'Jo','last_name':'AUTREDATE','email':'jo@example.test'}
    source['trainees'].append(extra)
    second = {**row, 'id':'b'*32, 'trainee_id':'T2', 'person':extra, 'days':[row['days'][1]]}
    store = retakes.Store(host)
    store.save(second)
    base = '/api/admin/sessions/S2/ssiap-exam'
    listing = client.get(base).json
    entries = {t['id']:t for t in listing['candidates']}
    cid = 'retake-' + row['id']
    assert set(entries) == {'REG', cid, 'retake-'+second['id']}
    assert entries[cid]['result'] == 'pending_results' and entries[cid]['edit_url'].endswith('/S1/stagiaires/T1')
    assert 'RATTRAPAGE' in ' '.join(pdf_text(client.get(entries[cid]['dossier_url'])))
    assert 'TEST' in ' '.join(pdf_text(client.get(listing['collective_url'])))
    exam = ' '.join(pdf_text(client.get(listing['attendance_url'])))
    assert all(name in exam for name in ('TEST','ORDINAIRE','AUTREDATE')) and 'ANNULE' not in exam
    assert [d['label'] for d in listing['preparation_dates']] == ['07/12/2026','08/12/2026']
    first, last = pdf_text(client.get(listing['preparation_url']))
    assert all(name in first for name in ('07/12/2026','TEST','ORDINAIRE','08:30')) and 'AUTREDATE' not in first
    assert all(name in last for name in ('08/12/2026','TEST','ORDINAIRE','09:00','AUTREDATE'))
    assert 'Membres du jury' not in first and 'ANNULE' not in last
    assert client.get(listing['preparation_dates'][0]['url'].replace('2026-12-07','2026-12-06')).status_code == 404
    printable = html.fromstring(client.get('/admin/sessions/S2/trainees/print').data)
    assert len(printable.xpath('//tr[@data-trainee-row][contains(., "TEST") and contains(., "Rattrapage")]')) == 1
    assert 'retake_results' not in target.get('ssiap_exam', {})
    assert client.post(base, json={'csrf':listing['csrf'],'revision':listing['revision'],'action':'candidate',
                                   'trainee_id':cid,'candidate':{'included':False}}).json['ok']
    assert 'TEST' not in ' '.join(pdf_text(client.get(listing['attendance_url'])))
    assert 'TEST' in ' '.join(pdf_text(client.get(listing['preparation_dates'][0]['url'])))
    assert [t['id'] for t in target['trainees']] == ['REG','ANN']


def test_exam_result_and_diploma_numbers_are_independent_on_retake(confirmed_ssiap):
    client, data, row = confirmed_ssiap
    source, target = data['sessions']
    original = copy.deepcopy(source['trainees'][0])
    route = '/api/admin/sessions/S2/ssiap-exam/diplomas'
    state = client.get(route).json
    cid = 'retake-' + row['id']
    candidate = next(t for t in state['candidates'] if t['id'] == cid)
    assert candidate['values']['result'] == 'pending_results'
    assert candidate['photo_api'].startswith('/api/admin/sessions/S1/') or '/S1/' in candidate['photo_api']
    candidate['values']['result'] = 'certified'
    assert client.post(route, json={'csrf':state['csrf'], 'action':'save', 'candidates':[candidate]}).json['ok']
    candidate = next(t for t in client.get(route).json['candidates'] if t['id'] == cid)
    assert candidate['values']['result'] == 'certified'
    with host.app.test_request_context():
        _, diplomas = host._reserve_ssiap_diploma_numbers(target['id'], cid)
        _, repeat = host._reserve_ssiap_diploma_numbers(target['id'], cid)
        assert repeat[0]['number'] == diplomas[0]['number'] and diplomas[0]['number'].endswith('00001')
        target['trainees'][0].update(ssiap_exam_status='certified', birth_date='1992-01-01', birth_city='PARIS', birth_department='75')
        _, ordinary = host._reserve_ssiap_diploma_numbers(target['id'], 'REG')
        assert ordinary[0]['number'].endswith('00002')
    assert source['trainees'][0] == original and [t['id'] for t in target['trainees']] == ['REG','ANN']


@pytest.mark.parametrize('condition', ['unsigned','partial','wrong_kind','other_exam_date','duplicate','foreign'])
def test_exam_ignores_unrelated_or_duplicate_retake_participants(confirmed_ssiap, condition):
    client, data, row = confirmed_ssiap
    source, target = data['sessions']
    if condition == 'unsigned': row['signed_at'] = ''
    if condition == 'partial': row['paid_cents'] -= 1
    if condition == 'wrong_kind': row['kind'] = 'APS'
    if condition == 'other_exam_date': row['exam_date'] = '2026-12-10'
    if condition == 'foreign': source['partner_id'] = 'external'
    if condition == 'duplicate': target['trainees'][0].update(first_name='Camille', last_name='TEST', email=row['person']['email'])
    retakes.Store(host).save(row)
    listing = client.get('/api/admin/sessions/S2/ssiap-exam').json
    assert [t['id'] for t in listing['candidates']] == ['REG']
    assert not listing['preparation_dates']
