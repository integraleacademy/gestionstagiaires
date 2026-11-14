"""Synthetic financial workflow tests; no network or production personal data."""
from copy import deepcopy
from contextlib import closing
import json
from types import SimpleNamespace as NS

import pytest
import cpf_provider
import edof_directory as directory
import edof_invoicing as ledger
import edof_invoice_qonto as qonto
from test_integrale_edof_dashboard import site

FOLDER='123456789'
IBAN='FR7612345000000000000000000'
RAW={'id':FOLDER,'idSuiviFinancement':'funding-test','currentState':'serviceDoneValidated',
     'etatBlocage':'NON_BLOQUE','beginDate':'2026-01-02','endDate':'2026-01-28',
     'attendee':{'firstName':'Anne','lastName':'Exemple'},
     'trainingActionInfo':{'title':'Formation de sécurité complète', 'sessionStartDate':'2026-01-02',
                          'sessionEndDate':'2026-01-30','trainingCompletionRate':80,'indicativeDuration':150,
                          'validatedServiceDone':True,'vat':False}}
BILL={'siret':directory.SIRET,'billId':'bill-test','amountCGU':1260,'contractualLimitAmount':1700,
      'amountPaid':0,'paymentInfo':{'iban':IBAN,'statusCode':'1'}}


def init(path, owner='admin'):
    gate=cpf_provider.ProviderStore(path)
    if gate.state()['provider']!='integrale':gate.switch('integrale',gate.state()['revision'],'admin')
    store=NS(directory=path,directory_enabled=lambda owner:True)
    ledger.discover(store,owner,{'rows':{FOLDER:directory.project(RAW)}})
    return store,ledger.next_job(store,gate.state())


class Portal:
    def __init__(self):
        self.raw=deepcopy(RAW);self.bill=deepcopy(BILL);self.sent=[];self.reads=[];self.timeout=False
    def get(self,url,**kwargs):
        self.reads.append(url)
        if url.endswith('/registration-folders/'+FOLDER):body=self.raw
        elif '/bills?' in url:body=self.bill
        elif url.endswith('/collaborators/me'):body={'company':{'organisms':[{'siret':directory.SIRET,'corporateName':'Organisme test','address':{'streetName':'rue Exemple'}}]}}
        else:pytest.fail('Unexpected EDOF endpoint')
        return NS(url=url,status=200,body=lambda:json.dumps(body).encode(),dispose=lambda:None)
    def post(self,url,**kwargs):
        self.sent.append(kwargs['data'])
        if self.timeout:raise TimeoutError('Synthetic lost response')
        self.raw['currentBillingState']='billed'
        self.bill.update(billNumber=kwargs['data']['billNumber'],amountToInvoice=kwargs['data']['amountToInvoice'])
        return NS(url=url,status=200,dispose=lambda:None)


def run(path,spec,portal):
    root=f'https://of.moncompteformation.gouv.fr/edof-api/v1/api/private/siret/{directory.SIRET}/'
    witness=NS(url=root+'organisms/current/registration-folders',method='GET',all_headers=lambda:{})
    return ledger.perform(NS(request=portal),witness,spec,path,NS(put=lambda *a:None),
                          'of.moncompteformation.gouv.fr',root.split('.fr')[1]+'organisms/current/registration-folders/')


class Qonto:
    def __init__(self):self.invoices={};self.creates=0;self.finals=0;self.timeout=False
    def _qonto_is_configured(self):return True
    def get_qonto_invoice_iban(self):return 'DE89370400440532013000'
    def find_qonto_client_by_tax_identification_number(self,_):return {'id':'cdc-test','tax_identification_number':qonto.CDC_SIRET}
    def list_qonto_invoices(self,params):return {'client_invoices':list(self.invoices.values()),'meta':{'total_pages':1}}
    def get_qonto_invoice(self,id):return {'client_invoice':deepcopy(self.invoices[id])}
    def _qonto_request(self,method,url,body,**kwargs):
        assert method=='POST' and url=='/v2/client_invoices' and kwargs['idempotency_key']
        self.creates+=1
        inv={**deepcopy(body),'id':'invoice-test','total_amount':{'value':'1260.00','currency':'EUR'}}
        self.invoices[inv['id']]=inv
        if self.timeout:raise TimeoutError('Synthetic lost creation response')
        return {'client_invoice':deepcopy(inv)}
    def finalize_qonto_invoice(self,id):
        self.finals+=1;self.invoices[id].update(status='unpaid',number='FL-TEST-001')


def prepare(path,app,portal):
    store,spec=init(path)
    assert run(path,spec,portal)['code']=='invoice_prepared'
    qonto.prepare(app,path,ledger.get(path,spec['token']))
    return store,ledger.next_job(store,cpf_provider.ProviderStore(path).state())


def test_full_flow_exact_amount_details_and_receipt(tmp_path):
    app,portal=Qonto(),Portal()
    store,spec=prepare(tmp_path,app,portal)
    inv=app.invoices['invoice-test']
    assert inv['payment_methods']['iban']==portal.bill['paymentInfo']['iban']
    assert inv['total_amount']['value']=='1260.00' # EDOF CGU, not 1700 contractual amount.
    assert inv['items'][0]['quantity']=='1' and inv['items'][0]['vat_rate']=='0'
    assert all(value in inv['items'][0]['description'] for value in [FOLDER,'Anne','Exemple','02/01/2026','30/01/2026',RAW['trainingActionInfo']['title']])
    assert '80 %' in inv['terms_and_conditions'] and '28/01/2026' in inv['terms_and_conditions']
    assert spec['mode']=='invoice_send'
    assert run(tmp_path,spec,portal)['code']=='invoice_confirmed'
    assert portal.sent[0]['amountToInvoice']==1260 and portal.sent[0]['billNumber']=='FL-TEST-001'
    assert portal.sent[0]['iBAN']==inv['payment_methods']['iban']
    assert portal.sent[0]['dateInvoice']==inv['issue_date']
    assert ledger.next_job(store,cpf_provider.ProviderStore(tmp_path).state()) is None
    assert ledger.get(tmp_path,spec['token'])['status']=='confirmed'
    snap={'checked':0,'rows':{FOLDER:directory.project(RAW)}}
    assert ledger.with_receipts(snap,tmp_path,'admin')['rows'][FOLDER]['billing_state']=='billed'


@pytest.mark.parametrize(('course', 'heading'), [
    ("Formation VTC tout inclus : théorie en e-learning + pratique + frais d'examen "
     "+ mise à disposition d'un véhicule doubles commandes", "Formation VTC tout inclus"),
    ("Formation e-learning – préparation à l'examen pratique", "Formation e-learning"),
    ("Agent de Prévention et de Sécurité (APS)", "Agent de Prévention et de Sécurité (APS)"),
    ("Accompagnement individuel à la création et à la reprise d’une entreprise", "Formation professionnelle"),
])
def test_invoice_item_uses_complete_heading_and_keeps_edof_description(course, heading):
    raw = deepcopy(RAW)
    raw['trainingActionInfo']['title'] = course
    terms = ledger.project(raw, BILL, directory.project(raw))
    item = qonto.invoice_body(terms, 'cdc-test')['items'][0]

    assert item['title'] == heading
    assert item['description'] == f"{FOLDER} - Exemple Anne - du 02/01/2026 au 30/01/2026 - {course}"


def test_lost_qonto_response_reconciles_one_invoice(tmp_path):
    store,spec=init(tmp_path);portal=Portal();app=Qonto();app.timeout=True
    run(tmp_path,spec,portal)
    with pytest.raises(TimeoutError):qonto.prepare(app,tmp_path,ledger.get(tmp_path,spec['token']))
    assert ledger.get(tmp_path,spec['token'])['create_started']
    qonto.prepare(app,tmp_path,ledger.get(tmp_path,spec['token']))
    assert app.creates==1 and app.finals==1 and ledger.get(tmp_path,spec['token'])['status']=='ready'


def test_rejected_edof_account_can_be_reexamined_after_qonto_accepts_it(tmp_path, monkeypatch):
    app, portal = Qonto(), Portal()
    store, spec = init(tmp_path)
    run(tmp_path, spec, portal)
    refused = RuntimeError('validation refused')
    refused.status_code = 422
    refused.body = '{"errors":[{"source":{"pointer":"/payment_methods/iban"}}]}'

    def reject(method, url, body, **kwargs):
        assert body['payment_methods']['iban'] == IBAN
        raise refused

    with monkeypatch.context() as patch:
        patch.setattr(app, '_qonto_request', reject)
        with pytest.raises(ledger.Review, match='compte de règlement EDOF'):
            qonto.prepare(app, tmp_path, ledger.get(tmp_path, spec['token']))
    record = ledger.get(tmp_path, spec['token'])
    assert record['status'] == 'review' and not record['create_started']
    assert not app.invoices and not portal.sent
    assert ledger.request_review(tmp_path, 'admin', FOLDER)
    assert run(tmp_path, spec, portal)['code'] == 'invoice_prepared'
    qonto.prepare(app, tmp_path, ledger.get(tmp_path, spec['token']))
    assert app.creates == app.finals == 1
    assert app.invoices['invoice-test']['payment_methods']['iban'] == IBAN


def test_lost_qonto_creation_without_visible_invoice_never_posts_again_even_after_review(tmp_path):
    store,spec=init(tmp_path);portal=Portal();run(tmp_path,spec,portal)
    r=ledger.get(tmp_path,spec['token']);assert ledger.fence(tmp_path,r,'prepared','creating')
    ledger.update(tmp_path,r['token'],status='review')
    assert ledger.request_review(tmp_path,'admin',FOLDER)
    app=Qonto()
    with pytest.raises(ledger.Review,match='interrompue'):qonto.prepare(app,tmp_path,ledger.get(tmp_path,r['token']))
    assert app.creates==0


def test_lost_edof_response_is_read_only_after_restart_and_review(tmp_path):
    app,portal=Qonto(),Portal();store,spec=prepare(tmp_path,app,portal);portal.timeout=True
    with pytest.raises(TimeoutError):run(tmp_path,spec,portal)
    spec=ledger.next_job(store,cpf_provider.ProviderStore(tmp_path).state());assert spec['mode']=='invoice_check'
    assert run(tmp_path,spec,portal)['code']=='invoice_uncertain'
    ledger.update(tmp_path,spec['token'],status='review')
    assert ledger.request_review(tmp_path,'admin',FOLDER)
    assert ledger.next_job(store,cpf_provider.ProviderStore(tmp_path).state())['mode']=='invoice_check'
    assert len(portal.sent)==1
    portal.raw['currentBillingState']='billed';portal.bill.update(billNumber='FL-TEST-001',amountToInvoice=1260)
    assert run(tmp_path,spec,portal)['code']=='invoice_confirmed'
    assert len(portal.sent)==1


@pytest.mark.parametrize('change', ['amount','identity','vat','advance','iban','state'])
def test_changed_or_unsupported_dossier_stops_before_transmission(tmp_path,change):
    app,portal=Qonto(),Portal();store,spec=prepare(tmp_path,app,portal)
    if change=='amount':portal.bill['amountCGU']=1300
    elif change=='identity':portal.raw['attendee']['firstName']='Autre'
    elif change=='vat':portal.raw['trainingActionInfo']['vatInclTax20']=50
    elif change=='advance':portal.bill['amountPaid']=100
    elif change=='iban':portal.bill['paymentInfo']['iban']=''
    elif change=='state':portal.raw['currentState']='canceled';portal.raw['trainingActionInfo']['validatedServiceDone']=False
    with pytest.raises(ledger.Review):run(tmp_path,spec,portal)
    assert not portal.sent


def test_hold_and_provider_switch_prevent_writes(tmp_path,monkeypatch):
    app,portal=Qonto(),Portal();store,spec=prepare(tmp_path,app,portal)
    with closing(ledger.database(tmp_path)) as db,db:db.execute('INSERT INTO edof_folder_holds VALUES(?)',(FOLDER,))
    assert ledger.next_job(store,cpf_provider.ProviderStore(tmp_path).state()) is None
    with pytest.raises(ledger.Review):run(tmp_path,spec,portal)
    assert not portal.sent
    monkeypatch.setattr(cpf_provider,'on_production_service',lambda:True)
    with pytest.raises(cpf_provider.ProviderUnavailable,match='facture'):cpf_provider.ProviderStore(tmp_path).switch('wedof',1,'admin')


def test_existing_qonto_invoice_is_reused_and_incomplete_search_never_creates(tmp_path):
    app,portal=Qonto(),Portal();store,spec=init(tmp_path);run(tmp_path,spec,portal)
    r=ledger.get(tmp_path,spec['token']);existing=qonto.invoice_body(r['terms'],'cdc-test')
    existing['payment_methods']=[{'type':'transfer','iban':IBAN.lower()}]
    app.invoices['existing']={**existing,'id':'existing','total_amount':{'value':'1260.00','currency':'EUR'},'status':'unpaid','number':'FL-EXISTING'}
    qonto.prepare(app,tmp_path,r)
    assert app.creates==0 and app.finals==0
    assert ledger.get(tmp_path,r['token'])['invoice_number']=='FL-EXISTING'
    with pytest.raises(ledger.Review,match='incomplète'):
        qonto.find_existing(NS(list_qonto_invoices=lambda _: {'client_invoices':[]}),r['terms'],'cdc-test')


@pytest.mark.parametrize('methods', [[], [{'type': 'transfer', 'iban': 'DE89370400440532013000'}]])
def test_existing_draft_needs_the_edof_transfer_account(tmp_path, methods):
    app, portal = Qonto(), Portal()
    store, spec = init(tmp_path)
    run(tmp_path, spec, portal)
    record = ledger.get(tmp_path, spec['token'])
    existing = qonto.invoice_body(record['terms'], 'cdc-test')
    app.invoices['existing'] = {
        **existing, 'id': 'existing', 'payment_methods': methods,
        'total_amount': {'value': '1260.00', 'currency': 'EUR'},
    }
    with pytest.raises(ledger.Review, match='compte de virement'):
        qonto.prepare(app, tmp_path, record)
    assert app.creates == app.finals == 0
    assert ledger.get(tmp_path, spec['token'])['qonto_id'] == 'existing'


def test_existing_edof_bill_creates_no_qonto_invoice(tmp_path):
    store,spec=init(tmp_path);portal=Portal();portal.raw['currentBillingState']='billed';portal.bill.update(billNumber='OLD-001',amountToInvoice=1260)
    assert run(tmp_path,spec,portal)['code']=='invoice_external'
    assert ledger.get(tmp_path,spec['token'])['status']=='external'
    assert not portal.sent


def test_invoice_status_and_review_route_respect_csrf_and_hold(site):
    store,spec=init(site.store.directory,site.owner)
    site.vault.put(directory.record_key(site.owner),{'checked':1,'rows':{FOLDER:directory.project(RAW)}})
    ledger.update(store.directory,spec['token'],status='review',message='Montant à vérifier.')
    url='/admin/edof-test/dossiers/'+FOLDER+'/facturation/verifier'
    page=site.client.get('/admin/edof-test?folder='+FOLDER)
    assert page.status_code==200 and 'Facturation Caisse des Dépôts' in page.text and 'Montant à vérifier.' in page.text
    assert site.client.post(url,data={}).status_code==403
    assert site.client.post(url,data={'csrf':site.csrf}).status_code==303
    assert ledger.get(store.directory,spec['token'])['status']=='queued'


def test_billing_watch_uses_newer_source_and_preserves_newer_receipts(tmp_path):
    from edof_gmail import Vault
    import base64
    vault=Vault(tmp_path,base64.urlsafe_b64encode(b'a'*32).decode())
    original={'checked':100,'rows':{FOLDER:directory.project(RAW)}}
    vault.put('billing-watch:admin',{'checked':200,'rows':{FOLDER:{**directory.project(RAW),'billing_state':'billed'}}})
    assert ledger.watched(original,vault,'admin')['rows'][FOLDER]['billing_state']=='billed'
    newer={'checked':300,'rows':{FOLDER:{**directory.project(RAW),'payment_state':'Issued'}}}
    assert ledger.watched(newer,vault,'admin')==newer


def test_test_service_cannot_create_or_transmit_invoices(tmp_path,monkeypatch):
    store,spec=init(tmp_path)
    monkeypatch.setattr(cpf_provider,'on_test_service',lambda:True)
    with pytest.raises(ledger.Review,match='production'):run(tmp_path,spec,Portal())
    app=Qonto()
    with pytest.raises(ledger.Review,match='production'):qonto.prepare(app,tmp_path,ledger.get(tmp_path,spec['token']))
    assert app.creates==0
