import datetime as dt
import importlib
import json
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault('PERSIST_DIR', tempfile.mkdtemp(prefix='alternance-tests-'))
os.environ.setdefault('NATIVE_ELEARNING_ENABLED', '0')
import crm_app
import app as host
import parcours_alternance as alt


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(host, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setattr(host, 'load_data', lambda: {'sessions': [], 'partners': [], 'users': []})
    monkeypatch.setattr(alt, 'today', lambda: dt.date(2026, 10, 22))
    host.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    send = Mock(return_value={'ok': True})
    monkeypatch.setattr(host, 'brevo_send_email', send)
    client = host.app.test_client()
    return client, send, tmp_path


def payload(client):
    response = client.get('/parcoursalternance/candidature')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    return dict(csrf=re.search(r'data-csrf="([^"]+)"', html)[1],
                submission_token=re.search(r'data-token="([^"]+)"', html)[1],
                first_name='Alice', last_name='Exemple', birth_date='2005-05-15',
                available_year=True, judicial_clear=True, license_b=True, mobile_departments=True,
                privacy_consent=True, email='alice@example.test', phone='06 12 34 56 78',
                city='Puget-sur-Argens', postcode='83480', situation='En études', vehicle='yes',
                contact_slot='Le matin', motivation='Je veux apprendre à protéger les personnes et acquérir une expérience sur le terrain.')


def staff(client, role='admin', partner=''):
    with client.session_transaction() as s:
        s['admin_logged_in'] = True
        s['admin_role'] = role
        if partner:
            s['partner_id'] = partner


def rows():
    with alt.database(host) as db:
        return [dict(row) for row in db.execute('SELECT * FROM applications')]


def test_landing_assets_and_download(setup):
    client, _, _ = setup
    page = client.get('/parcoursalternance')
    assert page.status_code == 200
    assert 'formation est entièrement gratuite' in page.text
    assert 'Janvier → février' in page.text
    assert 'Agent de protection physique des personnes' in page.text
    brochure = client.get('/parcoursalternance/brochure')
    assert brochure.status_code == 200
    assert brochure.data.startswith(b'%PDF')
    assert 'attachment' in brochure.headers['Content-Disposition']
    assert client.get('/static/parcours-alternance/application.js').status_code == 200


def test_submission_is_persisted_before_mail_and_idempotent(setup):
    client, send, _ = setup
    data = payload(client)
    def deliver(*args, **kwargs):
        assert len(rows()) == 1
        return {'ok': True}
    send.side_effect = deliver
    response = client.post('/parcoursalternance/candidature', json=data)
    assert response.status_code == 201
    assert response.json['email_sent'] is True
    assert send.call_count == 2
    assert {c.args[0] for c in send.call_args_list} == {'clement@integraleacademy.com','alice@example.test'}
    candidate_mail = next(c for c in send.call_args_list if c.args[0] == 'alice@example.test')
    staff_mail = next(c for c in send.call_args_list if c.args[0] == 'clement@integraleacademy.com')
    assert candidate_mail.kwargs['reply_to']['email'] == 'aurelie@integraleacademy.com'
    assert staff_mail.kwargs['reply_to']['email'] == 'alice@example.test'
    assert '04 87 83 06 15' in candidate_mail.args[2]
    assert '07 69 39 04 57' in candidate_mail.kwargs['text_content']
    raw = json.loads(rows()[0]['payload'])
    assert raw['last_name'] == 'EXEMPLE'
    assert 'judicial_clear' not in raw
    again = client.post('/parcoursalternance/candidature', json=data)
    assert again.json['reference'] == response.json['reference']
    assert send.call_count == 2
    new_form = payload(client)
    assert client.post('/parcoursalternance/candidature', json=new_form).json['already_received'] is True
    assert len(rows()) == 1 and send.call_count == 2


@pytest.mark.parametrize('field,value', [('birth_date','2000-10-22'),('birth_date','1998-01-01'),('birth_date','2028-01-01'),('birth_date','2020-02-30'),('available_year',False),('judicial_clear',False),('judicial_clear','true'),('license_b',False),('mobile_departments',False),('privacy_consent',False),('email','x\r\nBcc:someone@example.test'),('phone','abc'),('motivation','trop court'),('postcode','83'),('situation','invalid')])
def test_invalid_or_ineligible_never_stores_or_sends(setup,field,value):
    client,send,_=setup
    data=payload(client);data[field]=value
    response=client.post('/parcoursalternance/candidature',json=data)
    assert response.status_code == 400
    assert rows() == []
    send.assert_not_called()


def test_age_boundary_and_leap_date(setup):
    client,_,_=setup
    data=payload(client);data['birth_date']='2000-10-23'
    assert client.post('/parcoursalternance/candidature',json=data).status_code == 201
    assert alt.age_on(dt.date(2000,2,29),dt.date(2026,2,28))==25
    assert alt.age_on(dt.date(2000,2,29),dt.date(2026,3,1))==26


def test_csrf_and_payload_limits(setup):
    client,send,_=setup
    data=payload(client);data['csrf']='wrong'
    assert client.post('/parcoursalternance/candidature',json=data).status_code==400
    assert client.post('/parcoursalternance/candidature',json=[]).status_code==400
    assert client.post('/parcoursalternance/candidature',json={'motivation':'a'*25000}).status_code==413
    assert rows()==[];send.assert_not_called()


def test_failed_email_retries_only_failed_recipient(setup):
    client,send,_=setup
    data=payload(client)
    send.side_effect=[{'ok':True},{'ok':False}]
    response=client.post('/parcoursalternance/candidature',json=data)
    assert response.status_code==201 and response.json['email_sent'] is False
    assert len(rows())==1
    again=client.post('/parcoursalternance/candidature',json=data)
    assert again.json['email_sent'] is False
    send.side_effect=None
    with host.app.app_context():alt.deliver(host,response.json['reference'])
    assert send.call_count==3
    assert send.call_args.args[0]=='alice@example.test'
    assert rows()[0]['candidate_mail']=='sent'


def test_admin_access_csrf_update_conflict_and_escape(setup):
    client,send,_=setup
    data=payload(client);data['motivation']='<script>alert(1)</script> Je veux apprendre le métier et protéger les autres.'
    response=client.post('/parcoursalternance/candidature',json=data)
    ref=response.json['reference'];path='/admin/parcours-alternance/'+ref
    assert client.get('/admin/parcours-alternance').status_code in (301,302)
    assert client.get(path).status_code in (301,302)
    staff(client)
    listing=client.get('/admin/parcours-alternance')
    assert listing.status_code==200 and 'Alice' in listing.text
    page=client.get(path)
    assert page.status_code==200 and '&lt;script&gt;' in page.text
    assert '<script>alert(1)</script>' not in send.call_args_list[0].args[2]
    assert client.post(path,data={'action':'save','status':'accepted'}).status_code==400
    with client.session_transaction() as s:csrf=s['parcours_alternance_csrf']
    update={'csrf':csrf,'action':'save','status':'interview','notes':'Appel prévu demain','revision':'0'}
    assert client.post(path,data=update).status_code==302
    assert rows()[0]['status']=='interview'
    assert client.post(path,data=update).status_code==409
    assert send.call_count==2
    assert client.get('/admin/parcours-alternance?status=accepted').status_code==200
    with client.session_transaction() as s:s['assist_partner_id']='external'
    assert client.get(path).status_code==403


def test_external_and_viewer_are_denied(setup,monkeypatch):
    client,_,_=setup
    staff(client,role='viewer')
    assert client.get('/admin/parcours-alternance').status_code==403
    staff(client,role='partner_admin',partner='external')
    monkeypatch.setattr(host,'_load_partner_auth_data',lambda:{'partners':[],'users':[]})
    assert client.get('/admin/parcours-alternance').status_code in (302,403)


def test_retention_and_background_retry(setup):
    client,send,_=setup
    send.return_value={'ok':False}
    ref=client.post('/parcoursalternance/candidature',json=payload(client)).json['reference']
    old=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=6)).isoformat()
    with alt.database(host) as db:db.execute('UPDATE applications SET staff_attempt=?,candidate_attempt=?',(old,old))
    send.return_value={'ok':True}
    with host.app.app_context():alt.maintain(host)
    assert rows()[0]['staff_mail']=='sent' and rows()[0]['candidate_mail']=='sent'
    ancient=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=366)).isoformat()
    with alt.database(host) as db:db.execute('UPDATE applications SET created_at=?',(ancient,))
    with host.app.app_context():alt.maintain(host)
    assert rows()==[]
