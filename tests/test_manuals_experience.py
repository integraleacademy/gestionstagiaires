"""Regression cases for recovery, acceptance, tenant isolation and production gates."""
import io
import re
import time
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from pypdf import PdfWriter
from PIL import Image
import pytest
from test_manuals_shop import shop, signup, login, csrf, order_form, all_data
import app as host
from manuals_public import TERMS_VERSION


def admin_client():
    c=host.app.test_client()
    c.post('/admin/login',data={'username':'admin@example.test','password':'platform-test-pass'})
    return c


def submit_order(shop):
    c=shop['client'];signup(c);login(c)
    response=c.post('/admin/manuels/recapitulatif',data=order_form(c))
    path=response.location
    assert c.post(path+'/confirmer',data={'csrf_token':csrf(c,path),'confirm':'yes','terms_version':TERMS_VERSION}).status_code==303
    order=all_data(shop)['manual_orders'][0]
    return path,order


def test_public_pages_headers_and_real_assets(shop):
    c=shop['client']
    for path in ['/','/supports-formateurs','/supports-formateurs/ssiap2','/e-learning','/e-learning/aps','/e-learning/vtc','/mentions-legales','/conditions-de-vente','/confidentialite','/personnalisation-livraison','/robots.txt','/sitemap.xml','/favicon.ico']:
        response=c.get(path)
        assert response.status_code==200,(path,response.text[:300])
        assert response.headers.get('X-Content-Type-Options')=='nosniff'
        assert response.headers.get('X-Robots-Tag','').startswith('noindex')
    assert c.get('/supports-formateurs/mac_sst').status_code==404
    assert 'Disallow: /' in c.get('/robots.txt').text
    assert '/manuels/mac_sst' in c.get('/sitemap.xml').text
    for code in ['ssiap2','mac_aps','ssiap1_recyclage','h0b0','bs_be','mac_sst']:
        response=c.get('/manuels/'+code)
        from manuals_presentation import PRESENTATIONS
        assert PRESENTATIONS[code]['specimen'] in response.text
        assert 'Caractéristiques du manuel' in response.text


def test_registration_retains_safe_purchase_intent(shop):
    c=shop['client'];target='/admin/manuels?article=manual_ssiap2#commander-ssiap2'
    assert signup(c,next=target).status_code==303
    assert 'e-learning à venir' not in c.get('/espace-cree').text
    with c.session_transaction() as s:
        assert s['manuals_registration']['next']==target
    response=c.post('/admin/login',data={'username':'centre@example.test','password':'Une phrase robuste 2026!','next':target})
    assert response.location==target
    assert 'value="50"' in c.get('/admin/manuels?article=manual_ssiap2').text


def test_recovery_single_use_no_enumeration_and_old_session_revoked(shop):
    c=shop['client'];signup(c);login(c)
    visitor=host.app.test_client()
    known=visitor.post('/mot-de-passe-oublie',data={'csrf_token':csrf(visitor,'/mot-de-passe-oublie'),'email':'centre@example.test'})
    missing=visitor.post('/mot-de-passe-oublie',data={'csrf_token':csrf(visitor,'/mot-de-passe-oublie'),'email':'missing@example.test'})
    assert known.status_code==missing.status_code==200
    assert known.data==missing.data
    for _ in range(100):
        if any(m[1].get('metadata',{}).get('purpose')=='password_recovery' for m in shop['mails']): break
        time.sleep(.01)
    mail=next(m for m in shop['mails'] if m[1].get('metadata',{}).get('purpose')=='password_recovery')
    link=re.search(r'https://[^\s<]+/reinitialiser-mot-de-passe/[^\s<]+',mail[1]['text_content']).group(0)
    path=urlparse(link).path
    token=csrf(visitor,path)
    assert visitor.post(path,data={'csrf_token':token,'password':'short','password_confirmation':'short'}).status_code==400
    assert visitor.post(path,data={'csrf_token':token,'password':'Une nouvelle phrase 2026!','password_confirmation':'Une nouvelle phrase 2026!'}).status_code==303
    assert visitor.get(path).status_code==400
    response=c.get('/admin/manuels')
    assert response.status_code==302 and '/admin/login' in response.location
    assert visitor.post('/admin/login',data={'username':'centre@example.test','password':'Une nouvelle phrase 2026!','next':'/admin/organisme'}).location=='/admin/organisme'
    assert visitor.get('/reinitialiser-mot-de-passe/tampered').status_code==400


def test_acceptance_required_and_snapshot_kept(shop):
    c=shop['client'];signup(c);login(c)
    response=c.post('/admin/manuels/recapitulatif',data=order_form(c))
    path=response.location;token=csrf(c,path)
    assert c.post(path+'/confirmer',data={'csrf_token':token,'confirm':'yes'}).status_code==400
    assert c.post(path+'/confirmer',data={'csrf_token':token,'confirm':'yes','terms_version':'outdated'}).status_code==400
    assert c.post(path+'/confirmer',data={'csrf_token':token,'confirm':'yes','terms_version':TERMS_VERSION}).status_code==303
    saved=all_data(shop)['manual_orders'][0]
    assert saved['terms_acceptance']['version']==TERMS_VERSION
    assert saved['terms_acceptance']['user_id']==saved['created_by']
    assert 'data-cart-complete=' in c.get(path+'/paiement').text
    assert 'data-cart-complete=' not in c.get(path).text


def test_logo_bat_payment_shipping_and_reorder_isolation(shop):
    path,order=submit_order(shop);c=shop['client'];admin=admin_client();pid=order['partner_id']
    admin_path=f"/admin/commandes-manuels/{pid}/{order['id']}"
    assert admin.post(admin_path,data={'csrf_token':csrf(admin,admin_path),'status':'production'}).status_code==400
    image=io.BytesIO();Image.new('RGB',(50,50),'orange').save(image,format='PNG');image.seek(0)
    assert c.post(path+'/transmettre-logo',data={'csrf_token':csrf(c,path),'logo':(image,'logo.png')}).status_code==303
    pdf=io.BytesIO();writer=PdfWriter();writer.add_blank_page(420,595);writer.write(pdf);pdf.seek(0)
    assert admin.post(admin_path+'/suivi',data={'csrf_token':csrf(admin,admin_path),'action':'upload_bat','bat':(pdf,'bat.pdf')}).status_code==303
    assert c.get(path+'/bon-a-tirer').status_code==200
    assert c.post(path+'/bon-a-tirer/decision',data={'csrf_token':csrf(c,path),'decision':'approve','bat_version':'0','confirm_bat':'yes'}).status_code==409
    assert c.post(path+'/bon-a-tirer/decision',data={'csrf_token':csrf(c,path),'decision':'approve','bat_version':'1','confirm_bat':'yes'}).status_code==303
    assert admin.post(admin_path,data={'csrf_token':csrf(admin,admin_path),'status':'production'}).status_code==400
    def paid(data):
        o=next(o for o in data['manual_orders'] if o['id']==order['id']);o['commerce']['payment_status']='paid';return {}
    with host.app.test_request_context():host._atomic_update_data(paid,partner_id=pid)
    assert admin.post(admin_path+'/suivi',data={'csrf_token':csrf(admin,admin_path),'action':'shipping','status':'shipped','carrier':'Transport test','tracking_number':'TEST123','tracking_url':'javascript:alert(1)'}).status_code==400
    assert admin.post(admin_path+'/suivi',data={'csrf_token':csrf(admin,admin_path),'action':'shipping','status':'shipped','carrier':'Transport test','tracking_number':'TEST123','tracking_url':'https://example.test/suivi/TEST123','notify':'yes'}).status_code==303
    assert 'TEST123' in c.get(path).text
    original=next(o for o in all_data(shop)['manual_orders'] if o['id']==order['id'])
    assert original['fulfillment']['bat']['status']=='approved'
    assert original['fulfillment']['events'][-1]['email_status']=='sent'
    response=c.post(path+'/recommander',data={'csrf_token':csrf(c,path)})
    assert response.status_code==303 and '?draft=' in response.location
    draft=next(o for o in all_data(shop)['manual_orders'] if o['status']=='draft')
    assert draft['logo_filename'] and draft['logo_filename']!=original['logo_filename']
    assert draft['total_cents']==259900
    assert not draft.get('terms_acceptance') and not draft.get('commerce')
    other=host.app.test_client();signup(other,email='other@example.test');login(other,email='other@example.test')
    assert other.get(path+'/bon-a-tirer').status_code==404
    assert other.post(path+'/recommander',data={'csrf_token':csrf(other,'/admin/manuels')}).status_code==404
    assert other.get('/admin/commandes-manuels/statistiques').status_code==302


def test_recovery_has_no_cross_tenant_write(shop):
    c=shop['client'];signup(c);login(c)
    original=all_data(shop)['users'][0]['password_hash']
    assert c.post('/reinitialiser-mot-de-passe/fake',data={'csrf_token':csrf(c,'/mot-de-passe-oublie'),'password':'Password changed 2026!'}).status_code==400
    assert all_data(shop)['users'][0]['password_hash']==original
