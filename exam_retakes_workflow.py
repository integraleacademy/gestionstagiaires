"""Recoverable Yousign -> Qonto -> notification workflow for retakes."""
import base64
import hashlib
import time
import uuid
from decimal import Decimal
from io import BytesIO

from pypdf import PdfReader

from exam_retakes import (CONVOCATION_VERSION, RetakeError, cents, components, convocation_confirmed, convocation_delivery_key, convocation_requested,
                          discount_label, exam_upcoming, line_items, money, now, today)
from exam_retakes_documents import build_convocation, email_content
from manuals_commerce import read_invoice_link_payments, safe_payment_url


def checkpoint(store, row, **values):
    row.update(values)
    store.save(row)


def mutate(host, store, row, step, method, path, **kwargs):
    checkpoint(store, row, pending=step)
    try:
        result = host._yousign_json(method, path, **kwargs)
    except Exception as exc:
        if getattr(exc, 'status_code', None) in {400,401,403,404,422,429}:
            checkpoint(store,row,pending='')
        raise
    return result


def unique(values, message):
    if len(values) != 1:
        raise RetakeError(message)
    return values[0]


def ensure_signature(host, store, row):
    path = store.document(row['id'],'convention')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['pdf_sha256']:
        raise RetakeError('La convention enregistrée est absente ou a changé. Vérification nécessaire avant envoi.')
    external = 'retake-'+row['id']
    if not row.get('request_id'):
        if row.get('pending') == 'request':
            matches = [r for r in host._list_yousign_signature_requests({'external_id':external},max_pages=10) if r.get('external_id') == external]
            result = unique(matches,'Création Yousign non confirmée. Vérifiez la demande dans Yousign avant toute nouvelle création.')
        else:
            result = mutate(host,store,row,'request','POST','/signature_requests',json={
                'name':('Rattrapage '+row['kind']+' - '+row['person']['first_name']+' '+row['person']['last_name'])[:120],
                'delivery_mode':'none','timezone':'Europe/Paris','external_id':external,'audit_trail_locale':'fr'})
        if not result.get('id'):
            raise RetakeError('Yousign n’a pas renvoyé la référence de signature.')
        checkpoint(store,row,request_id=result['id'],pending='')
    request_path = '/signature_requests/'+row['request_id']
    remote = host._yousign_json('GET',request_path)
    if remote.get('status') in {'canceled','cancelled','expired','declined','rejected','deleted'}:
        checkpoint(store,row,status='stopped',signature_url='')
        return remote
    if remote.get('status') in {'done','completed'}:
        return remote
    if not row.get('document_id'):
        if row.get('pending') == 'document':
            docs = host._yousign_signature_request_items(host._yousign_json('GET',request_path+'/documents'))
            result = unique(docs,'Le dépôt de la convention dans Yousign reste à vérifier.')
        else:
            with path.open('rb') as file:
                result = mutate(host,store,row,'document','POST',request_path+'/documents',files={'file':('convention-rattrapage.pdf',file,'application/pdf')},data={'nature':'signable_document','parse_anchors':'false'})
        if not result.get('id'):
            raise RetakeError('Yousign n’a pas confirmé le document.')
        checkpoint(store,row,document_id=result['id'],pending='')
    if not row.get('signer_id'):
        person = row['person']
        if row.get('pending') == 'signer':
            signers = host._yousign_signature_request_items(host._yousign_json('GET',request_path+'/signers'))
            result = unique([s for s in signers if (s.get('info') or {}).get('email','').lower() == person['email'].lower()], 'La création du signataire reste à vérifier dans Yousign.')
        else:
            result = mutate(host,store,row,'signer','POST',request_path+'/signers',json={
                'info':{'first_name':person['first_name'],'last_name':person['last_name'],'email':person['email'],
                        'phone_number':host._normalize_yousign_sms_phone(person['phone']),'locale':'fr'},
                'signature_level':'electronic_signature','signature_authentication_mode':host.YOUSIGN_SMS_AUTHENTICATION_MODE,
                'fields':[{'document_id':row['document_id'],'type':'signature',**row['signature_field'],
                           'layout':'detailed','date_time_format':'dd/MM/yyyy','show_timezone':False}]})
        if not result.get('id'):
            raise RetakeError('Yousign n’a pas confirmé le signataire.')
        checkpoint(store,row,signer_id=result['id'],pending='')
    if remote.get('status') == 'draft':
        remote = mutate(host,store,row,'activate','POST',request_path+'/activate',json={})
    if remote.get('status') not in {'ongoing','activated','approval','done','completed'}:
        raise RetakeError('La demande de signature n’est pas encore active.')
    signer = host._yousign_json('GET',request_path+'/signers/'+row['signer_id'])
    link = host._extract_yousign_signature_link(signer,row['signer_id']) or host._extract_yousign_signature_link(remote,row['signer_id'])
    checkpoint(store,row,status='signing',signature_url=link,pending='')
    if remote.get('status') not in {'done','completed'}:
        if not link:
            raise RetakeError('Le lien de signature est temporairement indisponible.')
        send_email(host,store,row,'signature',link,[])
    return remote


def store_pdf(path, content):
    if not content.startswith(b'%PDF-') or not PdfReader(BytesIO(content)).pages:
        raise RetakeError('Le document retourné n’est pas un PDF valide.')
    tmp = path.with_suffix('.tmp')
    tmp.write_bytes(content)
    tmp.replace(path)


def invoice_assert(row, invoice):
    client_id = invoice.get('client_id') or (invoice.get('client') or {}).get('id')
    if (not invoice.get('id') or (row.get('invoice_id') and invoice['id'] != row['invoice_id'])
            or invoice.get('purchase_order') != 'RET-'+row['id'] or client_id != row.get('client_id')):
        raise RetakeError('La référence de facture Qonto ne correspond pas au rattrapage.')
    amount = invoice.get('total_amount') or {}
    if (not isinstance(amount,dict) or (amount.get('currency') or invoice.get('currency')) != 'EUR'
            or invoice.get('currency') not in (None, '', 'EUR') or cents(amount.get('value')) != row['total_cents']):
        raise RetakeError('Le montant Qonto diffère de la convention : vérification nécessaire.')


def recover_invoice(host,row):
    for page in range(1,21):
        result=host.list_qonto_invoices({'filter[created_at_from]':row['submitted_at'],'sort_by':'created_at:desc','per_page':100,'page':page})
        invoices=list(host._iter_qonto_invoice_payloads(result))
        matches=[i for i in invoices if i.get('purchase_order') == 'RET-'+row['id']]
        if matches:
            found=unique(matches,'Plusieurs factures correspondent au rattrapage. Vérifiez Qonto.')
            return host._qonto_invoice_payload(host.get_qonto_invoice(found['id']))
        if not host._qonto_invoice_list_has_next_page(result,page,len(invoices),100):
            break
    raise RetakeError('Création de facture non confirmée. Vérifiez Qonto ; aucune seconde facture ne sera émise automatiquement.')


def ensure_invoice(host,store,row):
    if not row.get('client_id'):
        # Force the trainee as individual payer even if the initial course was CPF/OPCO funded.
        client = host.build_qonto_client_payload({'financingType':'PERSONNEL'},row['person'],{},financeur='PERSONNEL')
        result=host.get_or_create_qonto_billing_client(client)
        client_id=(result.get('client') or result).get('id')
        if not client_id:
            raise RetakeError('Qonto n’a pas confirmé le client de facturation.')
        checkpoint(store,row,client_id=client_id)
    if row.get('invoice_id'):
        invoice=host._qonto_invoice_payload(host.get_qonto_invoice(row['invoice_id']))
    elif row.get('invoice_started'):
        invoice=recover_invoice(host,row)
    else:
        rate=Decimal(row['vat_rate'])/100
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise RetakeError('Le taux de TVA de la fiche stagiaire est invalide.')
        items=[]
        for item in line_items(row):
            if item['total_cents'] == 0:
                continue
            net=(Decimal(item['unit_cents'])/100/(1+rate)).quantize(Decimal('.000001'))
            description=item['label']
            if item['discount_cents']:
                description+=' · Tarif unitaire de référence TTC : '+money(item['reference_unit_cents'])+' · '+discount_label(item)+' sur cette ligne, déjà déduite du prix facturé.'
            items.append({'title':item['label'],'description':description,'quantity':str(item['quantity']),
                          'unit_price':{'value':str(net),'currency':'EUR'},'vat_rate':str(rate)})
        payload={'client_id':row['client_id'],'status':'draft','currency':'EUR','issue_date':today(),'due_date':today(),
                 'purchase_order':'RET-'+row['id'],'header':'Rattrapage '+row['kind'],
                 'payment_methods':{'iban':host.get_qonto_invoice_iban()},'items':items,
                 'performance_start_date':row['days'][0]['date'] if row['days'] else row['exam_date'],
                 'performance_end_date':row['exam_date'],'terms_and_conditions':'Paiement à réception. Participation confirmée après règlement intégral.'}
        checkpoint(store,row,invoice_started=now())
        try:
            invoice=host._qonto_invoice_payload(host._qonto_request('POST','/v2/client_invoices',payload,idempotency_key='retake-invoice-'+row['id']))
        except Exception as exc:
            if getattr(exc,'status_code',None) in {400,401,403,422,429}:
                checkpoint(store,row,invoice_started='')
            raise
    invoice_assert(row,invoice)
    if not row.get('invoice_id'):
        checkpoint(store,row,invoice_id=invoice['id'])
    if invoice.get('status') == 'draft':
        host.finalize_qonto_invoice(invoice['id'])
        invoice=host._qonto_invoice_payload(host.get_qonto_invoice(invoice['id']))
        invoice_assert(row,invoice)
    if invoice.get('status') in {'canceled','cancelled'}:
        record_payment(store, row, 'canceled', 0)
        raise RetakeError('La facture a été annulée dans Qonto. Le rattrapage ne peut pas être confirmé.')
    if invoice.get('status') not in {'unpaid','paid','overdue','finalized'}:
        raise RetakeError('La facture Qonto n’est pas encore émise.')
    checkpoint(store,row,invoice_number=invoice.get('number') or invoice.get('invoice_number') or '',
               status='confirmed' if row['status']=='confirmed' else 'payment')
    return invoice


def record_payment(store, row, status, paid_cents, url=''):
    confirmed = status == 'paid'
    checkpoint(store, row, status='confirmed' if confirmed else 'payment',
               payment_status=status, paid_cents=paid_cents, payment_url=url,
               confirmed_at=(row.get('confirmed_at') or now()) if confirmed else '')


def ensure_payment(host,store,row,invoice):
    payment = host.normalize_qonto_invoice_payment_data(invoice, {'amount_ttc': row['total_cents'] / 100})
    invoice_paid = payment['qonto_amount_paid_cents']
    if payment['qonto_payment_status'] == 'paid':
        record_payment(store, row, 'paid', invoice_paid)
        return
    if invoice_paid and not (row.get('payment_id') or row.get('payment_started')):
        record_payment(store, row, 'partially_paid', invoice_paid)
        raise RetakeError('Un paiement partiel a été enregistré. Vérifiez le solde dans Qonto avant de transmettre un nouveau lien.')
    authorized=host._qonto_invoice_payload(host._qonto_request('GET','/v2/client_invoices/'+invoice['id'],use_oauth=True))
    invoice_assert(row,authorized)
    if authorized.get('organization_id') != invoice.get('organization_id'):
        raise RetakeError('La connexion de paiement ne correspond pas à l’organisme émetteur de la facture.')
    link=None
    if row.get('payment_id'):
        response=host._qonto_request('GET','/v2/payment_links/'+row['payment_id'])
        link=response.get('payment_link') or response
    elif row.get('payment_started'):
        for page in range(1,21):
            response=host._qonto_request('GET','/v2/payment_links',params={'page':page,'per_page':100})
            links=response.get('payment_links',[])
            matches=[l for l in links if l.get('invoice_id')==invoice['id']]
            if matches:
                link=unique(matches,'Plusieurs liens de paiement correspondent à cette facture.')
                break
            if not host._qonto_invoice_list_has_next_page(response,page,len(links),100):
                break
        if not link:
            raise RetakeError('Création du lien de paiement non confirmée. Vérifiez le lien dans Qonto.')
    if link is None:
        available=host._qonto_request('GET','/v2/payment_links/payment_methods',params={'amount':f"{row['total_cents']/100:.2f}",'currency':'EUR'})
        methods=[m['name'] for m in available.get('payment_link_payment_methods',[]) if m.get('enabled') is True and m.get('name') in {'credit_card','apple_pay'}]
        if 'credit_card' not in methods:
            raise RetakeError('Activez le paiement par carte bancaire dans Qonto. La facture est conservée et le suivi sera réessayé automatiquement.')
        payload={'payment_link':{'invoice_id':invoice['id'],'invoice_number':invoice['number'],
                  'debitor_name':row['person']['first_name']+' '+row['person']['last_name'],
                  'amount':{'value':f"{row['total_cents']/100:.2f}",'currency':'EUR'},'potential_payment_methods':methods}}
        checkpoint(store,row,payment_started=now())
        try:
            response=host._qonto_request('POST','/v2/payment_links',payload,idempotency_key='retake-payment-'+row['id'])
        except Exception as exc:
            if getattr(exc,'status_code',None) in {400,401,403,422,429}:
                checkpoint(store,row,payment_started='')
            raise
        link=response.get('payment_link') or {}
    amount=link.get('amount') or {}
    url=safe_payment_url(link.get('url'))
    if (not link.get('id') or (row.get('payment_id') and link['id'] != row['payment_id'])
            or link.get('invoice_id') != invoice['id'] or link.get('resource_type', 'Invoice') != 'Invoice'
            or link.get('reusable', False) is not False
            or amount.get('currency') != 'EUR' or cents(amount.get('value')) != row['total_cents']):
        raise RetakeError('Le lien de paiement Qonto ne correspond pas à la facture et à son montant.')
    if not row.get('payment_id'):
        checkpoint(store, row, payment_id=link['id'])
    # The invoice balance can lag behind a card capture until the bank payout.
    # These are two views of the same money, so never add them together.
    captures, pending = read_invoice_link_payments(host, link['id'])
    captured = sum(captures.values())
    if captured == row['total_cents']:
        record_payment(store, row, 'paid', captured)
        return
    if captured > row['total_cents']:
        record_payment(store, row, 'review', invoice_paid)
        raise RetakeError('Les paiements du lien dépassent le montant de la convention. Vérifiez la facture dans Qonto.')
    if captured or invoice_paid:
        record_payment(store, row, 'partially_paid', max(captured, invoice_paid))
        raise RetakeError('Un paiement partiel a été enregistré. Vérifiez le solde dans Qonto avant de transmettre un nouveau lien.')
    if link.get('status') in {'canceled','cancelled','expired'}:
        record_payment(store, row, 'canceled', 0)
        raise RetakeError('Le lien de paiement Qonto a expiré ou a été annulé. Vérifiez la facture dans Qonto.')
    if pending or link.get('status') in {'paid', 'processing'}:
        record_payment(store, row, 'processing', 0)
        return
    if link.get('status') != 'open' or not url:
        raise RetakeError('Le lien de paiement Qonto n’est pas disponible.')
    record_payment(store, row, 'unpaid', 0, url)


def send_email(host,store,row,kind,link,paths,*,delivery_key=None):
    state=row.setdefault('emails',{}).setdefault(delivery_key or kind,{'key':str(uuid.uuid4())})
    if state.get('sent_at'):
        return state
    # Brevo deduplication is bounded. Do not retry an ambiguous send after its window.
    if state.get('uncertain_at') and time.time()-state['uncertain_at'] > 600:
        raise RetakeError('L’envoi de l’e-mail reste à vérifier dans l’historique Brevo avant une nouvelle tentative.')
    subject,html,text=email_content(host,row,kind,link)
    attachments=[{'name':name,'content':base64.b64encode(path.read_bytes()).decode()} for name,path in paths]
    state.setdefault('uncertain_at',time.time())
    store.save(row)
    result=host.brevo_send_email(row['person']['email'],subject,html,attachments=attachments,text_content=text,
                                metadata={'purpose':'exam_retake_'+kind,'idempotency_key':state['key']})
    if not isinstance(result,dict) or not result.get('ok'):
        if isinstance(result,dict) and (result.get('not_sent') or result.get('status_code') in {400,401,403,422,429}):
            state.pop('uncertain_at',None)
            store.save(row)
        raise RetakeError('L’e-mail n’a pas été confirmé. Le suivi et les documents sont conservés.')
    state.update(sent_at=now(),message_id=result.get('message_id',''))
    if kind == 'convocation':
        state['document_version'] = CONVOCATION_VERSION
    state.pop('uncertain_at',None)
    store.save(row)
    return state


def send_confirmed_documents(host, store, row, target, portal, documents):
    emails = row.setdefault('emails', {})
    if convocation_confirmed(row) and convocation_requested(row) and exam_upcoming(row) and not target.get('archived'):
        key = convocation_delivery_key(row)
        receipt = emails.get(key, {})
        if not receipt.get('sent_at'):
            path = store.document(row['id'], 'convocation')
            if not path.is_file():
                store_pdf(path, build_convocation(row))
            files = [('Convocation-rattrapage-' + row['exam_date'] + '.pdf', path)]
            if not emails.get('documents', {}).get('sent_at'):
                files.extend(documents)
            receipt = send_email(host, store, row, 'convocation', portal, files, delivery_key=key)
        # Preserve the original confirmation and document checkpoints, including on restart.
        if row['total_cents'] and not emails.get('confirmed', {}).get('sent_at'):
            emails['confirmed'] = dict(receipt)
    else:
        kind = 'confirmed' if row['total_cents'] else 'documents'
        receipt = send_email(host, store, row, kind, portal, documents)
    if not emails.get('documents', {}).get('sent_at'):
        emails['documents'] = dict(receipt)
    store.save(row)


def process(host,store,row):
    if row['status'] in {'draft','cancelled','stopped'}:
        return
    # A deleted/archived target never silently creates an enrolment elsewhere.
    data=host.load_data(run_background_tasks=False)
    source=host.find_session(data,row['source_session'])
    trainee=next((t for t in host._session_trainees_list(source) if t.get('id')==row['trainee_id']),None) if source else None
    target=host.find_session(data,row['target_session'])
    if not source or not trainee or not target:
        raise RetakeError('La fiche d’origine ou la session d’accueil est introuvable.')
    if (row['kind'] not in components(host,target)
            or (target.get('partner_id') or host.INTEGRALE_PARTNER_ID) != (source.get('partner_id') or host.INTEGRALE_PARTNER_ID)):
        raise RetakeError('La session d’accueil a changé de formation ou d’organisme. Vérification nécessaire.')
    if target.get('archived') and row['status'] != 'confirmed':
        raise RetakeError('La session d’accueil est archivée. Vérification nécessaire avant de poursuivre.')
    signed_path=store.document(row['id'],'signed')
    signed_valid=(signed_path.is_file() and hashlib.sha256(signed_path.read_bytes()).hexdigest()==row.get('signed_sha256'))
    if row['status']=='queued':
        remote=ensure_signature(host,store,row)
    elif not row.get('signed_at') or not signed_valid:
        remote=host._yousign_json('GET','/signature_requests/'+row['request_id'])
    else:
        remote={'status':'done'}
    if not row.get('signed_at') or not signed_valid:
        if remote.get('status') in {'canceled','cancelled','expired','declined','rejected','deleted'}:
            checkpoint(store,row,status='stopped',signature_url='')
            return
        if remote.get('status') not in {'done','completed'}:
            if row.get('signature_url'):
                send_email(host,store,row,'signature',row['signature_url'],[])
            return
        response=host._yousign_request('GET','/signature_requests/'+row['request_id']+'/documents/download',
                                      params={'version':'completed','archive':'false'},headers={'Accept':'application/pdf'})
        store_pdf(store.document(row['id'],'signed'),response.content)
        checkpoint(store,row,status='signed',signed_at=row.get('signed_at') or now(),signature_url='',signed_sha256=hashlib.sha256(response.content).hexdigest())
    attachments=[('Convention-rattrapage-signee.pdf',store.document(row['id'],'signed'))]
    portal=host.PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')+'/espace/'+str(trainee.get('public_token') or '')
    if row['total_cents']==0:
        checkpoint(store,row,status='confirmed',payment_status='not_required',confirmed_at=row.get('confirmed_at') or now())
        send_confirmed_documents(host, store, row, target, portal, attachments)
        return
    invoice=ensure_invoice(host,store,row)
    ensure_payment(host,store,row,invoice)
    if not row.get('invoice_pdf') or not store.document(row['id'],'invoice').is_file():
        content,_=host.fetch_qonto_client_invoice_pdf(row['invoice_id'])
        store_pdf(store.document(row['id'],'invoice'),content)
        checkpoint(store,row,invoice_pdf=True)
    attachments.append(('Facture-rattrapage-Qonto.pdf',store.document(row['id'],'invoice')))
    if row['status']=='confirmed':
        send_confirmed_documents(host, store, row, target, portal, attachments)
    elif row.get('payment_url'):
        send_email(host,store,row,'documents',row['payment_url'],attachments)
