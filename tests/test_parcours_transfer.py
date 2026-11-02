import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import parcours_alternance as parcours


def test_transfer_only_from_production_with_signed_body_and_durable_ack(tmp_path,monkeypatch):
    host=SimpleNamespace(app=Flask(__name__),PERSIST_DIR=str(tmp_path))
    with parcours.database(host) as db:
        db.execute("""INSERT INTO applications(id,dedupe,request_key,created_at,payload,notes)
                   VALUES('ALT-ABCDEF123456','d','k','2026-11-02','{"first_name":"Alice"}','Appeler mardi')""")
    cid='12345678-1234-4123-8123-123456789012'
    reply=Mock(status_code=200)
    reply.json.return_value={'ok':True,'candidate_id':cid}
    post=Mock(return_value=reply)
    monkeypatch.setattr(parcours.requests,'post',post)
    secret='x'*32
    monkeypatch.setenv('BTS_IMPORT_API_KEY',secret)
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME','gestionstagiaires-test-v2.onrender.com')
    parcours.transfer_legacy_applications(host)
    post.assert_not_called()
    monkeypatch.setenv('RENDER_EXTERNAL_HOSTNAME','gestionstagiaires-r5no.onrender.com')
    parcours.transfer_legacy_applications(host)
    parcours.transfer_legacy_applications(host)
    assert post.call_count==1
    body=post.call_args.kwargs['data']
    key=hmac.digest(secret.encode(),b'parcours-securite-import-v1','sha256')
    assert post.call_args.kwargs['headers']['X-Parcours-Signature']==hmac.new(key,body,hashlib.sha256).hexdigest()
    assert json.loads(body)['notes']=='Appeler mardi'
    with parcours.database(host) as db:
        assert db.execute('SELECT candidate_id FROM admissions_transfer').fetchone()[0]==cid


def test_public_presentation_and_form_destination(tmp_path):
    from pathlib import Path
    root=Path(parcours.__file__).resolve().parent
    app=Flask(__name__,template_folder=str(root/'templates'))
    app.secret_key='test-only'
    shop=SimpleNamespace(manuals_public=SimpleNamespace(CACHEABLE=set()), SAFE_ENDPOINTS=set())
    parcours.register(SimpleNamespace(app=app,PERSIST_DIR=str(tmp_path),admin_login_required=lambda fn:fn,manuals_shop=shop))
    client=app.test_client()
    page=client.get('/parcoursalternance')
    assert page.status_code==200 and page.text.count('href="'+parcours.APPLICATION_URL+'"')>=3
    old=client.get('/parcoursalternance/candidature')
    assert old.status_code==302 and old.location==parcours.APPLICATION_URL
    assert '/parcoursalternance/brochure' in page.text
