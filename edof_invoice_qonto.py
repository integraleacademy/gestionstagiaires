"""Qonto invoice adapter used only after an authoritative EDOF billing read."""
from datetime import datetime, timedelta
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from edof_directory import normalized
from edof_invoicing import Review, fence, get, money, record_creation_rejection, update

CDC_SIRET='18002002600019'
QONTO_ITEM_TITLE_LIMIT = 40

# The full EDOF offer distinguishes initial training, renewals, VAE and packs.
CATALOGUE_ITEM_TITLES = {normalized(offer): label for offer, label in (
    ("Formation Agent de Protection rapprochée (APR) - Agent de protection physique des personnes (A3P) "
     "- Garde du corps (bodyguard)", "Agent de protection rapprochée (A3P/APR)"),
    ("Formation Agent de Sécurité - CQP Agent de prévention et de sécurité (APS)",
     "Agent de prévention et de sécurité (APS)"),
    ("Formation Assurer les missions de chef de poste en sécurité privée (CPSP) - Encadrement (chef de poste)",
     "Chef de poste en sécurité privée (CPSP)"),
    ("Formation Dirigeant d'une entreprise sécurité privée - CQP dirigeant "
     "- Titre Dirigeant d'entreprise de sécurité privée (DESP)", "DESP – Formation initiale"),
    ("VAE TOTALE Dirigeant d'une entreprise sécurité privée - CQP dirigeant "
     "- Titre Dirigeant d'entreprise de sécurité privée (DESP) - Validation des acquis de l'expérience",
     "DESP – VAE totale"),
    ("VAE Titre Dirigeant d'entreprise de sécurité privée (DESP) - CQP dirigeant", "DESP – VAE"),
    ("Formation SSIAP 1 (agent de sécurité incendie) + SST (Sauveteur Secouriste du Travail)",
     "Formation SSIAP 1 + SST"),
    ("Pack Formation agent de sécurité : CQP Agent de Prévention et de sécurité (APS) "
     "+ Agent de sécurité incendie SSIAP 1 + SST + habilitation électrique",
     "Pack APS + SSIAP 1 + SST + habil. élec."),
    ("Module complémentaire SSIAP 1 agent de sécurité incendie - spécial pompiers - SSIAP 1 par équivalence",
     "SSIAP 1 par équivalence – Pompiers"),
    ("Recyclage SSIAP 1 agent de service de sécurité incendie et d'assistance aux personnes (formation continue)",
     "Recyclage SSIAP 1"),
    ("Recyclage SSIAP 2 chef d'équipe de sécurité incendie et d'assistance aux personnes (SSIAP 2)",
     "Recyclage SSIAP 2"),
    ("Recyclage SSIAP 3 chef de service de sécurité incendie et d'assistance aux personnes (formation continue)",
     "Recyclage SSIAP 3"),
    ("Remise à niveau SSIAP 1 agent de service de sécurité incendie et d'assistance aux personnes (formation continue)",
     "Remise à niveau SSIAP 1"),
    ("Remise à niveau SSIAP 2 chef d'équipe de sécurité incendie et d'assistance aux personnes (SSIAP 2)",
     "Remise à niveau SSIAP 2"),
    ("Remise à niveau SSIAP 3 chef de service de sécurité incendie et d'assistance aux personnes (formation continue)",
     "Remise à niveau SSIAP 3"),
)}


def invoice_item_title(course_title):
    title = ' '.join(course_title.split())
    if len(title) <= QONTO_ITEM_TITLE_LIMIT:
        return title
    catalogue_title = CATALOGUE_ITEM_TITLES.get(normalized(title))
    if catalogue_title:
        return catalogue_title
    heading = re.split(r':|\s+[-–—]\s+', title, maxsplit=1)[0].strip()
    if heading and len(heading) <= QONTO_ITEM_TITLE_LIMIT:
        return heading
    return 'Formation professionnelle'


def invoice_body(terms,client_id):
    today=datetime.now(ZoneInfo('Europe/Paris')).date()
    french=lambda value:datetime.fromisoformat(value).strftime('%d/%m/%Y')
    description=(f"{terms['folder_id']} - {terms['last_name']} {terms['first_name']} - "
                 f"du {french(terms['session_start_date'])} au {french(terms['session_end_date'])} - {terms['title']}")
    notes=f"Service fait validé par EDOF. Taux de réalisation : {terms['rate']} %."
    if terms.get('duration'):
        notes+=f" Durée prévue : {terms['duration']} h."
    if terms['actual_start']!=terms['session_start_date'] or terms['actual_end']!=terms['session_end_date']:
        notes+=f" Période réalisée : du {french(terms['actual_start'])} au {french(terms['actual_end'])}."
    return {'client_id':client_id,'currency':'EUR','status':'draft','issue_date':today.isoformat(),
            'due_date':(today+timedelta(days=30)).isoformat(),'payment_methods':{'iban':terms['iban']},
            'performance_start_date':terms['actual_start'],'performance_end_date':terms['actual_end'],
            'purchase_order':terms['folder_id'],'header':f"Dossier CPF {terms['folder_id']}",
            'terms_and_conditions':notes,
            'items':[{'title':invoice_item_title(terms['title']),'description':description,'quantity':'1',
                      'unit_price':{'value':terms['amount'],'currency':'EUR'},'vat_rate':'0'}]}


def unwrap(result):
    return result.get('client_invoice') or result.get('invoice') or result


def invoice_text(inv):
    fields=[inv.get(k) or '' for k in ('purchase_order','header','footer','terms_and_conditions')]
    for item in inv.get('items') or []:
        fields.extend([item.get('title') or '',item.get('description') or ''])
    return ' '.join(str(x) for x in fields)


def has_reference(inv,folder):
    return bool(re.search(r'(?<!\d)'+re.escape(folder)+r'(?!\d)',invoice_text(inv)))


def validate(inv,terms,client_id):
    customer=inv.get('client') or inv.get('customer') or {}
    if str(inv.get('client_id') or customer.get('id') or '')!=client_id and str(customer.get('tax_identification_number') or '')!=CDC_SIRET:
        raise Review('Le destinataire de la facture Qonto ne correspond pas à la Caisse des Dépôts.')
    amount=inv.get('total_amount')
    if not isinstance(amount,dict) or amount.get('currency',inv.get('currency'))!='EUR' or money(amount.get('value'))!=terms['amount']:
        raise Review('Le montant de la facture Qonto ne correspond pas au montant validé par EDOF.')
    methods = inv.get('payment_methods') or []
    if isinstance(methods, dict):
        methods = [methods]
    transfer_ibans = {
        re.sub(r'\s+', '', str(method.get('iban') or '')).upper()
        for method in methods
        if isinstance(method, dict) and method.get('type', 'transfer') == 'transfer'
    }
    if transfer_ibans != {terms['iban']}:
        raise Review('Le compte de virement indiqué sur la facture Qonto ne correspond pas au compte de règlement du dossier EDOF.')
    if not has_reference(inv,terms['folder_id']):
        raise Review('Le numéro CPF manque sur la facture Qonto.')
    text=invoice_text(inv).casefold()
    for value in (terms['first_name'],terms['last_name'],terms['title']):
        if value.casefold() not in text:
            raise Review('La facture Qonto existante ne contient pas tous les détails du dossier. Vérifiez-la avant transmission.')
    for key in ('session_start_date','session_end_date'):
        day=terms[key]
        if day not in text and datetime.fromisoformat(day).strftime('%d/%m/%Y') not in text:
            raise Review('Les dates de la formation manquent sur la facture Qonto existante.')
    if any(Decimal(str(item.get('vat_rate') or 0)) for item in inv.get('items') or []):
        raise Review('La TVA de la facture Qonto diffère du dossier EDOF.')
    if inv.get('status') not in {'draft','unpaid','paid'}:
        raise Review('La facture Qonto est annulée ou son état est inconnu.')


def find_existing(app,terms,client_id):
    matches={}
    # API has no client_id / arbitrary text search filter. Read all pages of active
    # invoices; never conclude absence from a failed/partial scan.
    for page in range(1,101):
        payload=app.list_qonto_invoices({'page':page,'per_page':100,'filter[status]':'draft,unpaid,paid','sort_by':'created_at:desc'})
        batch=payload.get('client_invoices')
        meta=payload.get('meta') or {}
        if not isinstance(batch,list) or not isinstance(meta.get('total_pages'),int):
            raise Review('La recherche des factures Qonto est incomplète. Aucune nouvelle facture créée.')
        for inv in batch:
            if not isinstance(inv,dict) or not inv.get('id'):
                raise Review('Réponse Qonto incomplète pendant la recherche de doublons.')
            if has_reference(inv,terms['folder_id']):
                matches[inv['id']]=inv
            else:
                # An old invoice without the CPF reference may already cover this
                # learner/period. Do not issue a second one on a heuristic match.
                text=invoice_text(inv).casefold()
                customer=inv.get('client') or inv.get('customer') or {}
                cdc=(str(inv.get('client_id') or customer.get('id') or '')==client_id or
                     str(customer.get('tax_identification_number') or '')==CDC_SIRET or 'caisse des d' in str(customer.get('name') or '').casefold())
                names=all(terms[k].casefold() in text for k in ('first_name','last_name'))
                period=any(terms[k] in text or datetime.fromisoformat(terms[k]).strftime('%d/%m/%Y') in text for k in ('session_start_date','session_end_date'))
                if cdc and names and period:
                    raise Review('Une facture Qonto pourrait déjà concerner ce stagiaire. Vérifiez son numéro CPF avant toute création.')
        if page>=meta['total_pages']:
            if len(matches)>1:
                raise Review('Plusieurs factures Qonto portent ce numéro CPF. Aucun nouvel envoi effectué.')
            return next(iter(matches.values()),None)
        if not batch:
            break
    raise Review('La recherche complète des factures Qonto doit être terminée avant toute création.')


def prepare(app,path,record):
    from cpf_provider import on_test_service
    if on_test_service():
        raise Review('La facturation automatique est réservée au service de production.')
    terms=record['terms']
    if not app._qonto_is_configured():
        raise Review('Qonto n’est pas connecté pour la facturation.')
    client=app.find_qonto_client_by_tax_identification_number(CDC_SIRET)
    if not client:
        client=app.get_or_create_cpf_qonto_client()
    client=client.get('client') or client
    if not client.get('id') or str(client.get('tax_identification_number') or '')!=CDC_SIRET:
        raise Review('Le SIRET du client Caisse des Dépôts doit être vérifié dans Qonto.')
    client_id=str(client['id'])
    inv=unwrap(app.get_qonto_invoice(record['qonto_id'])) if record['qonto_id'] else find_existing(app,terms,client_id)
    if not inv:
        if record['status']=='creating' or record['create_started']:
            raise Review('La création précédente a été interrompue. Vérifiez Qonto avant de reprendre ; aucune deuxième facture créée.')
        if not fence(path,record,'prepared','creating'):
            raise Review('La facturation a été suspendue avant la création Qonto.')
        # Persist the fence BEFORE the POST. Qonto idempotency expires after 30min;
        # the durable local fence is therefore the primary duplicate protection.
        try:
            result = app._qonto_request('POST', '/v2/client_invoices', invoice_body(terms, client_id),
                                        idempotency_key=record['token'])
        except RuntimeError as exc:
            if getattr(exc, 'status_code', None) != 422:
                raise
            message = 'Qonto a refusé les données du brouillon de facture. Vérifiez les informations avant de relancer.'
            if 'iban' in str(getattr(exc, 'body', '')).casefold():
                message = 'Qonto a refusé le compte de règlement EDOF. Vérifiez que ce compte est utilisable pour les factures Qonto, puis réexaminez le dossier.'
            record_creation_rejection(path, record['token'], message)
            raise Review(message) from None
        inv = unwrap(result)
        if not inv.get('id'):
            raise RuntimeError('Qonto invoice response incomplete')
        update(path,record['token'],qonto_id=str(inv['id']),status='draft')
    else:
        update(path,record['token'],qonto_id=str(inv['id']),status='draft')
    inv=unwrap(app.get_qonto_invoice(str(inv['id'])))
    validate(inv,terms,client_id)
    if inv['status']=='draft':
        current=get(path,record['token'])
        if not fence(path,current,'draft','draft'):
            raise Review('La facturation est suspendue avant la finalisation Qonto.')
        app.finalize_qonto_invoice(str(inv['id']))
        inv=unwrap(app.get_qonto_invoice(str(inv['id'])))
        validate(inv,terms,client_id)
    number=str(inv.get('number') or '')
    if inv.get('status') not in {'unpaid','paid'} or not re.fullmatch(r'[-A-Za-z0-9_./\\]{1,40}',number):
        raise Review('Qonto n’a pas confirmé le numéro définitif de la facture.')
    issued=str(inv.get('issue_date') or '')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',issued):
        raise Review('La date de la facture Qonto est manquante.')
    update(path,record['token'],status='ready',invoice_number=number,invoice_date=issued,message='',retry_at=0)
