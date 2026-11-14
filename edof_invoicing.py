"""Durable CPF invoices: EDOF amount -> Qonto -> verified EDOF receipt.

The billing DTO follows the official portal's registration-folder bill form.
Every write is fenced on disk; an interrupted write is only reconciled, never replayed.
"""
from contextlib import closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from cpf_provider import ProviderStore
import edof_directory as directory

MODES = {"invoice_prepare", "invoice_send", "invoice_check"}
LABELS = {"queued":"Lecture du montant EDOF", "prepared":"Préparation de la facture Qonto",
          "creating":"Vérification de la création Qonto", "draft":"Finalisation Qonto",
          "ready":"Facture Qonto créée · transmission EDOF en attente",
          "sending":"Vérification de la réception EDOF", "confirmed":"Facture transmise à EDOF",
          "review":"Facturation à vérifier", "external":"Déjà facturé dans EDOF"}
MESSAGES = {"invoice_prepared":"Montant facturable vérifié dans EDOF.",
            "invoice_confirmed":"Numéro et montant de la facture confirmés dans EDOF.",
            "invoice_unavailable":"Lecture de facturation indisponible. Nouvelle vérification prévue.",
            "invoice_review":"Facturation suspendue : vérifiez les informations du dossier.",
            "invoice_external":"Ce dossier est déjà facturé dans EDOF.",
            "invoice_uncertain":"Transmission lancée : réception à vérifier dans EDOF."}


class Review(ValueError):
    """A user-readable, non-secret reason to stop issuing/transmitting an invoice."""


def money(value):
    if value is None or isinstance(value, bool):
        raise Review("Montant EDOF manquant.")
    try:
        n = Decimal(str(value).replace(",", "."))
        if not n.is_finite() or not 0 <= n <= 10000000 or n != n.quantize(Decimal('.01')):
            raise InvalidOperation()
        return format(n, '.2f')
    except (InvalidOperation, ValueError):
        raise Review("Montant EDOF invalide.") from None


def database(path):
    db = ProviderStore(path).connect()
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_invoices (
        folder TEXT PRIMARY KEY, owner TEXT NOT NULL, revision INTEGER NOT NULL, token TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL, changed REAL NOT NULL, retry_at REAL NOT NULL DEFAULT 0,
        identity TEXT NOT NULL, terms TEXT NOT NULL DEFAULT '{}', qonto_id TEXT NOT NULL DEFAULT '',
        invoice_number TEXT NOT NULL DEFAULT '', invoice_date TEXT NOT NULL DEFAULT '',
        create_started REAL NOT NULL DEFAULT 0, send_started REAL NOT NULL DEFAULT 0,
        message TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '{}')""")
    db.execute("CREATE TABLE IF NOT EXISTS edof_folder_holds(folder TEXT PRIMARY KEY)")
    return db


def records(path, owner=None):
    with closing(database(path)) as db:
        rows = db.execute('SELECT * FROM cpf_invoices WHERE owner=? ORDER BY changed DESC', (owner,)) if owner else db.execute('SELECT * FROM cpf_invoices ORDER BY changed DESC')
        return [{**dict(r), "identity":json.loads(r['identity']), "terms":json.loads(r['terms']),
                 "receipt":json.loads(r['receipt']), "label":LABELS.get(r['status'],r['status'])} for r in rows]


def get(path, token):
    return next((r for r in records(path) if r['token']==token), None)


def update(path, token, **values):
    allowed = {'status','terms','qonto_id','invoice_number','invoice_date','message','receipt','retry_at'}
    if not values or set(values)-allowed:
        raise ValueError('Invalid invoice update')
    values = {k:json.dumps(v,ensure_ascii=False) if k in {'terms','receipt'} else v for k,v in values.items()}
    values['changed'] = time.time()
    with closing(database(path)) as db, db:
        db.execute('UPDATE cpf_invoices SET '+','.join(k+'=?' for k in values)+' WHERE token=?', (*values.values(),token))


def allowed(db, record):
    state = ProviderStore('.').state(db)
    return (state['provider']=='integrale' and not state['pending'] and state['revision']==record['revision']
            and not db.execute('SELECT 1 FROM edof_folder_holds WHERE folder=?',(record['folder'],)).fetchone())


def fence(path, record, before, after):
    with closing(database(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if not allowed(db,record):
            return False
        marker = ',create_started=unixepoch()' if after=='creating' else ',send_started=unixepoch()' if after=='sending' else ''
        return db.execute('UPDATE cpf_invoices SET status=?,changed=?'+marker+' WHERE token=? AND status=?',
                          (after,time.time(),record['token'],before)).rowcount==1


def record_creation_rejection(path, token, message):
    """Only a definitive validation refusal releases the Qonto creation fence."""
    with closing(database(path)) as db, db:
        db.execute("""UPDATE cpf_invoices SET status='review', message=?, changed=?, create_started=0
                      WHERE token=? AND status='creating' AND qonto_id='' AND send_started=0""",
                   (message, time.time(), token))


def discover(store, owner, snapshot):
    from integrale_edof_dashboard import category
    state = ProviderStore(store.directory).state()
    if state['provider']!='integrale' or state['pending']:
        return
    with closing(database(store.directory)) as db, db:
        for folder,row in snapshot['rows'].items():
            if category(row)!='billable' or not directory.ID_RE.fullmatch(folder):
                continue
            identity = {k:row.get(k,'') for k in ('folder_id','first_name','last_name','title','session_start_date','session_end_date')}
            db.execute("""INSERT OR IGNORE INTO cpf_invoices(folder,owner,revision,token,status,changed,identity)
                          VALUES(?,?,?,?,'queued',?,?)""",
                       (folder,owner,state['revision'],uuid.uuid4().hex,time.time(),json.dumps(identity)))


def next_job(store, selection):
    if selection['provider']!='integrale' or selection['pending']:
        return None
    with closing(database(store.directory)) as db:
        rows = db.execute("""SELECT * FROM cpf_invoices WHERE status IN
              ('queued','prepared','creating','draft','ready','sending') AND revision=? AND retry_at<=?
              ORDER BY CASE WHEN status='sending' THEN 0 ELSE 1 END,changed LIMIT 20""",
                          (selection['revision'],time.time())).fetchall()
        for r in rows:
            if not allowed(db,r) or not store.directory_enabled(r['owner']):
                continue
            # Browser and provider locks in start_job serialize this with declarations.
            mode = 'invoice_check' if r['status']=='sending' else 'invoice_send' if r['status']=='ready' else 'invoice_prepare'
            return {'mode':mode,'owner':r['owner'],'folder_id':r['folder'],'token':r['token'],
                    'revision':r['revision'],'provider':'integrale'}


def fingerprint(terms):
    return hashlib.sha256(json.dumps(terms,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def watched(snapshot,vault,owner):
    recent=vault.get('billing-watch:'+owner)
    if not recent:
        return snapshot
    combined=snapshot or {'rows':{},'checked':0}
    rows=dict(combined['rows'])
    for folder,row in recent['rows'].items():
        if recent['checked']>max(combined.get('checked',0),rows.get(folder,{}).get('observed_at',0)):
            rows[folder]={**row,'observed_at':recent['checked']}
    return {**combined,'rows':rows}


def project(raw, bill, expected):
    row = directory.project(raw)
    for key in ('folder_id','first_name','last_name','session_start_date','session_end_date'):
        if not row.get(key) or directory.normalized(row[key])!=directory.normalized(expected.get(key,'')):
            raise Review("L’identité ou les dates EDOF ont changé. Vérifiez le dossier.")
    if str(bill.get('siret'))!=directory.SIRET:
        raise Review("L’établissement de facturation EDOF ne correspond pas.")
    bill_id = str(bill.get('billId') or '')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,80}',bill_id):
        raise Review("Appel à facture EDOF introuvable.")
    amount = money(bill.get('amountCGU'))
    if Decimal(amount)<=0:
        raise Review("Le montant calculé par EDOF est nul : vérification nécessaire.")
    info = raw.get('trainingActionInfo') or {}
    # This organisation's supplied model is tax exempt. Never silently turn a
    # taxable/mixed dossier into a zero-VAT invoice.
    if (info.get('vat') is True or str(info.get('vat')).casefold()=='true'
        or any(Decimal(money(info.get(k) or 0)) for k in ('vatInclTax5','vatInclTax20','vatExclTax5','vatExclTax20'))
        or any(Decimal(money(bill.get(k) or 0)) for k in ('vatAmount5','vatAmount20'))):
        raise Review("TVA différente du modèle CPF : vérifiez la ventilation de la facture.")
    if Decimal(money(bill.get('amountPaid') or 0)):
        raise Review("Une avance est déjà versée : vérifiez son rapprochement avant la facturation.")
    payment = bill.get('paymentInfo') or {}
    iban = re.sub(r'\s+','',str(payment.get('iban') or '')).upper()
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{11,30}',iban) or str(payment.get('statusCode'))=='3':
        raise Review("Les coordonnées de paiement EDOF doivent être validées.")
    if raw.get('isBlocageOf') or raw.get('etatBlocage') not in (None,'','NON_BLOQUE','DEBLOQUE','UNBLOCKED'):
        raise Review("EDOF signale un blocage du dossier.")
    rate = info.get('trainingCompletionRate')
    try:
        rate = Decimal(str(rate))
        if not rate.is_finite() or not 0<=rate<=100:
            raise InvalidOperation()
    except (InvalidOperation,ValueError):
        raise Review("Le taux de réalisation validé par EDOF est manquant.") from None
    start,end = row['session_start_date'],row['session_end_date']
    actual_end = directory.session_date(raw.get('endDate'))
    actual_start = directory.session_date(raw.get('beginDate'))
    if not actual_start or not actual_end or not start<=actual_start<=actual_end<=end or actual_end>datetime.now(ZoneInfo('Europe/Paris')).date().isoformat():
        raise Review("Les dates effectives d’entrée et de sortie EDOF sont incomplètes.")
    title = info.get('title') or row['title']
    if not isinstance(title,str) or not title.strip() or len(title)>1400:
        raise Review("L’intitulé de la formation est manquant.")
    return {**{k:row[k] for k in expected},'title':title.strip(),'amount':amount,'bill_id':bill_id,'iban':iban,
            'rate':str(rate),'actual_start':actual_start,'actual_end':actual_end,
            'duration':str(info.get('indicativeDuration') or '')}


def perform(context, witness, spec, path, vault, origin, prefix):
    """Only the existing verified same-establishment browser may call these endpoints."""
    record = get(path,spec['token'])
    from cpf_provider import on_test_service
    if on_test_service():
        raise Review('La facturation automatique est réservée au service de production.')
    workspace = f'/edof-api/v1/api/private/siret/{directory.SIRET}/'
    source = urlsplit(witness.url) if witness else None
    if (not record or record['owner']!=spec['owner'] or record['folder']!=spec['folder_id']
        or not source or witness.method!='GET' or source.scheme!='https' or source.netloc!=origin
        or origin!='of.moncompteformation.gouv.fr' or not source.path.startswith(workspace)
        or prefix!=workspace+'organisms/current/registration-folders/'):
        raise Review('Le dossier ne peut pas être vérifié dans cette connexion EDOF.')
    headers = {**directory.private_headers(witness),'Current-Siret':directory.SIRET}
    root = 'https://'+origin+workspace
    def read(url):
        response = context.request.get(url,headers=headers,max_redirects=0,timeout=12000)
        try:
            directory.check_throttling(response)
            if response.status!=200 or response.url!=url:
                return None
            body=response.body()
            return json.loads(body) if len(body)<2_000_000 else None
        finally:
            response.dispose()
    raw = read('https://'+origin+prefix+record['folder'])
    if not isinstance(raw,dict) or str(raw.get('id'))!=record['folder']:
        return {'code':'invoice_unavailable'}
    funding = str(raw.get('idSuiviFinancement') or '')
    if not re.fullmatch(r'[A-Za-z0-9-]{1,80}',funding):
        raise Review('Référence de financement EDOF manquante.')
    bill_url = root+'organisms/current/bills?'+urlencode({'idSuiviFinancement':funding})
    bill = read(bill_url)
    if not isinstance(bill,dict):
        return {'code':'invoice_unavailable'}
    billed = directory.normalized(raw.get('currentBillingState') or '')=='billed' or directory.normalized(bill.get('currentState') or '')=='billed'
    if billed:
        if record['invoice_number'] and bill.get('billNumber')==record['invoice_number'] and money(bill.get('amountToInvoice'))==record['terms'].get('amount'):
            update(path,record['token'],status='confirmed',receipt={'number':bill['billNumber'],'amount':money(bill['amountToInvoice']),
                   'billing_at':directory.dates.first(raw,'billingDate'),'at':time.time()},message='')
            return {'code':'invoice_confirmed'}
        if record['qonto_id']:
            raise Review('Une autre facture est enregistrée dans EDOF. Aucun nouvel envoi effectué.')
        update(path,record['token'],status='external',message='Une facture est déjà enregistrée dans EDOF.')
        return {'code':'invoice_external'}
    if spec['mode']=='invoice_check':
        return {'code':'invoice_uncertain'}
    if directory.normalized(raw.get('currentState') or '') not in {'servicedonevalidated','service done validated','servicedonevalidatedrevisionvsf','service done validated revision vsf'} and (raw.get('trainingActionInfo') or {}).get('validatedServiceDone') is not True:
        raise Review('Le service fait n’est plus validé dans EDOF.')
    terms=project(raw,bill,record['identity'])
    if bill.get('billNumber') and bill['billNumber']!=record['invoice_number']:
        raise Review('Des données de facture sont déjà saisies dans EDOF. Vérifiez le numéro existant.')
    if record['terms'] and fingerprint(terms)!=fingerprint(record['terms']):
        raise Review('Le montant ou les conditions EDOF ont changé depuis la préparation.')
    if spec['mode']=='invoice_prepare':
        if record['status']=='queued':
            update(path,record['token'],status='prepared',terms=terms,message='')
        return {'code':'invoice_prepared'}
    # Reuse the official form's payload. The issuer address is read from EDOF,
    # never copied from a previous learner's invoice.
    me=read(root+'collaborators/me')
    organisms=((me or {}).get('company') or {}).get('organisms') or []
    org=next((x for x in organisms if str(x.get('siret'))==directory.SIRET),None)
    if not org or not isinstance(org.get('address'),dict) or not org.get('corporateName'):
        raise Review('Les coordonnées de l’organisme émetteur EDOF sont incomplètes.')
    value=float(Decimal(terms['amount']))
    if not directory.session_date(record['invoice_date']):
        raise Review('La date de la facture Qonto doit être vérifiée.')
    payload={'siret':directory.SIRET,'id':terms['bill_id'],'dateInvoice':record['invoice_date'],
             'billNumber':record['invoice_number'],'amountTtc':bill.get('contractualLimitAmount'),
             'amountCGU':value,'amountToInvoice':value,'totalAmountExTax':value,'amountHtNet':value,
             'vatAmount5':0,'vatAmount20':0,'vatHtAmount5':0,'vatHtAmount20':0,'totalAmountTva':0,
             'amountDepositReceived':0,'datepayment':bill.get('dateDepositPayment'),'comment':None,
             'iBAN':terms['iban'],'corporateName':org['corporateName'],'billAddress':org['address'],
             'orderNumber':record['folder'],'nameAttendee':terms['first_name']+' '+terms['last_name'],
             'trainingActionInfo':terms['title'],'trainingCompilationRate':terms['rate'],
             'trainingReleaseDate':raw.get('trainingReleaseDate'),
             'beginDate':raw.get('beginDate'),'endDate':raw.get('endDate'),
             'sessionStartDate':terms['session_start_date'],'sessionEndDate':terms['session_end_date']}
    if not record['invoice_number'] or not fence(path,record,'ready','sending'):
        raise Review('La facturation est suspendue ou déjà en cours.')
    vault.put('directory-generation',time.time_ns())
    target=root+'organisms/current/bills/'+terms['bill_id']+'/validate'
    response=context.request.post(target,headers=headers,data=payload,max_redirects=0,timeout=15000)
    try:
        directory.check_throttling(response)
        status=response.status if response.url==target else 0
    finally:
        response.dispose()
    # Never infer success from HTTP 200 alone; read back the saved number and amount.
    result=perform(context,witness,{**spec,'mode':'invoice_check'},path,vault,origin,prefix)
    if result['code']=='invoice_uncertain' and status in {400,401,403,404,409,422}:
        raise Review('EDOF a refusé les données de facture. La facture Qonto est conservée ; aucun doublon ne sera créé.')
    return result


def with_receipts(snapshot,path,owner):
    """Show authoritative receipts immediately, until the next complete EDOF list."""
    if not snapshot:
        return snapshot
    rows=dict(snapshot['rows'])
    for record in records(path,owner):
        row=rows.get(record['folder'])
        receipt=record['receipt']
        if (record['status']!='confirmed' or not row or receipt.get('at',0)<=max(snapshot.get('checked',0),row.get('observed_at',0))
            or any(row.get(k)!=record['identity'].get(k) for k in ('first_name','last_name','session_start_date','session_end_date'))):
            continue
        rows[record['folder']]={**row,'billing_state':'billed','billing_at':receipt.get('billing_at',''),'observed_at':receipt['at']}
    return {**snapshot,'rows':rows}


def request_review(path,owner,folder):
    """A recheck may reconcile interrupted writes, never authorize their replay."""
    with closing(database(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM cpf_invoices WHERE owner=? AND folder=? AND status='review'",(owner,folder)).fetchone()
        if not row or not allowed(db,row):
            return False
        status='sending' if row['send_started'] else 'draft' if row['qonto_id'] else 'creating' if row['create_started'] else 'queued'
        db.execute('UPDATE cpf_invoices SET status=?,retry_at=0,message=? WHERE token=?',(status,'Nouvelle vérification demandée.',row['token']))
        return True


def complete(store,spec,result):
    r=get(store.directory,spec['token'])
    if not r or r['status'] in {'confirmed','external','review'}:
        return
    code=result['code']
    if code=='invoice_prepared':
        from edof_invoice_qonto import prepare
        try:
            with store.legacy.app.app_context():
                prepare(store.legacy,store.directory,r)
        except Review as exc:
            update(store.directory,r['token'],status='review',message=str(exc))
        except Exception:
            # A successful remote create may have lost its response. The durable
            # 'creating' fence prevents a second POST even beyond Qonto's 30min TTL.
            update(store.directory,r['token'],message='Qonto indisponible. Vérification automatique de la facture avant toute reprise.',retry_at=time.time()+900)
    elif code=='invoice_review':
        update(store.directory,r['token'],status='review',message=result.get('invoice_message') or MESSAGES[code])
    elif code not in {'invoice_confirmed','invoice_external'}:
        update(store.directory,r['token'],retry_at=time.time()+900,message=MESSAGES.get(code,'Connexion indisponible : nouvelle vérification prévue.'))
