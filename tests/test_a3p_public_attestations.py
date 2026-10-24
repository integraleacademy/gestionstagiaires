import copy
from unittest.mock import Mock

import pytest

import app


@pytest.fixture
def case(monkeypatch, tmp_path):
    trainee={'id':'T1','first_name':'Camille','last_name':'MARTIN','public_token':'a3p-test','public_has_logged_in':True}
    training={'id':'S1','name':'A3P TEST','training_type':'A3P','date_start':'2026-09-01','date_end':'2026-10-27','trainees':[trainee]}
    other={'id':'T2','first_name':'Alex','last_name':'TEST','public_token':'other-test'}
    training['trainees'].append(other)
    data={'sessions':[training]}
    monkeypatch.setattr(app,'load_data',lambda **kwargs:copy.deepcopy(data))
    monkeypatch.setattr(app,'save_data',Mock())
    monkeypatch.setattr(app,'_atomic_update_data',lambda mutate:mutate(data))
    monkeypatch.setattr(app,'APS_END_ATTESTATION_DIR',str(tmp_path))
    def generate(kind):
        pdf=tmp_path/(kind+'.pdf');docx=tmp_path/(kind+'.docx')
        pdf.write_bytes(b'%PDF-1.4 '+kind.encode());docx.write_bytes(b'docx')
        return str(docx),str(pdf)
    generators={kind:Mock(side_effect=lambda *args,k=kind:generate(k)) for kind in ('conducteur','stu')}
    monkeypatch.setattr(app,'_generate_a3p_driver_attestation_files',generators['conducteur'])
    monkeypatch.setattr(app,'_generate_a3p_stu_attestation_files',generators['stu'])
    mail=Mock();monkeypatch.setattr(app,'brevo_send_email',mail)
    client=app.app.test_client()
    with client.session_transaction() as cookie:cookie['public_auth_a3p-test']=True
    return client,training,trainee,generators,mail,tmp_path


@pytest.mark.parametrize('kind',['conducteur','stu'])
def test_backfill_after_issue_and_reuse_without_email(case,kind):
    client,_,trainee,generators,mail,_=case
    url=f'/espace/a3p-test/attestations-a3p/{kind}.pdf'
    assert client.get(url).status_code==404
    trainee['attestation_fin_aps_sent_at']='2026-10-27T18:00:00Z'
    response=client.get(url)
    assert response.status_code==200 and response.data.startswith(b'%PDF')
    assert response.headers['Cache-Control']=='private, no-store'
    assert client.get(url).status_code==200
    assert generators[kind].call_count==1 and not mail.called
    stored=trainee['a3p_driver_attestation']
    assert (stored['stu'] if kind=='stu' else stored)['pdf_path']


def test_legacy_files_display_two_public_links(case):
    client,_,trainee,generators,mail,tmp_path=case
    for kind in ('conducteur','stu'):(tmp_path/(kind+'.pdf')).write_bytes(b'%PDF legacy')
    trainee['a3p_driver_attestation']={'pdf_path':str(tmp_path/'conducteur.pdf'),'stu':{'pdf_path':str(tmp_path/'stu.pdf')}}
    html=client.get('/espace/a3p-test').text
    assert 'data-a3p-attestation="conducteur"' in html and 'data-a3p-attestation="stu"' in html
    for kind in ('conducteur','stu'):
        assert f'/espace/a3p-test/attestations-a3p/{kind}.pdf' in html
        assert client.get(f'/espace/a3p-test/attestations-a3p/{kind}.pdf').status_code==200
    assert not any(g.called for g in generators.values()) and not mail.called


def test_scope_auth_and_no_other_learner_document(case):
    client,training,trainee,_,mail,_=case
    trainee['attestation_fin_aps_sent_at']='2026-10-27'
    url='/espace/a3p-test/attestations-a3p/conducteur.pdf'
    assert client.get('/espace/other-test/attestations-a3p/conducteur.pdf').status_code==302
    with client.session_transaction() as cookie:cookie['public_auth_other-test']=True
    assert client.get('/espace/other-test/attestations-a3p/conducteur.pdf').status_code==404
    assert client.get(url.replace('conducteur','unknown')).status_code==404
    for kind in ('APS','MAC A3P','A3P VAE'):
        training.update(training_type=kind,name=kind)
        assert client.get(url).status_code==404
        assert 'data-a3p-attestation' not in client.get('/espace/a3p-test').text
    training.update(training_type='A3P',name='A3P')
    trainee['registration_cancelled']=True
    assert client.get(url).status_code==403 and not mail.called


def test_outside_file_is_never_served(case,tmp_path_factory):
    client,_,trainee,_,mail,_=case
    outside=tmp_path_factory.mktemp('outside')/'private.pdf';outside.write_bytes(b'private')
    trainee['a3p_driver_attestation']={'pdf_path':str(outside)}
    assert client.get('/espace/a3p-test/attestations-a3p/conducteur.pdf').status_code==404
    assert not mail.called
