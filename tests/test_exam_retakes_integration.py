"""Render the real admin/public pages and route verified callbacks to the queue."""
import copy
from unittest.mock import Mock

from lxml import html
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
    assert not page.xpath('//tr[@data-trainee-id="T1"]')
    assert data['sessions'][1]['trainees']==[]


def test_public_page_displays_only_its_retakes(real_app):
    client,_=real_app
    row=create(real_app,exam_price='60',day_price='70',no_days=False,days=[{'date':'2026-12-07'},{'date':'2026-12-08'}])
    row.update(status='confirmed',signed_at=retakes.now(),payment_status='paid',confirmed_at=retakes.now())
    retakes.Store(host).save(row)
    response=client.get('/espace/PUB-T1')
    assert response.status_code==200
    page=html.fromstring(response.data)
    section=page.xpath('//section[@id="rattrapage"]')[0]
    assert '09/12/2026' in section.text_content()
    assert 'Convention signée' in section.text_content()
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
