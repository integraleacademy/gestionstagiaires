"""Acceptance, compatible sessions and idempotent local registration; no live EDOF."""
import json
import time
from unittest.mock import Mock

import pytest

import edof_directory as directory
import edof_enrolment_watch as watch
from edof_server_browser import EDOF_HOST, API_PREFIX
from integrale_edof_registration import training_family, matching_sessions
from test_integrale_edof_dashboard import site

BASE = '/admin/edof-test/dossiers/100000'
HEADERS = {'Accept':'application/json'}


@pytest.mark.parametrize('title,family', [
    ('Formation VTC tout inclus : théorie en e-learning + pratique', 'VTC'),
    ('Formation Agent de Sécurité - CQP Agent de prévention et de sécurité (APS)', 'APS'),
    ('Pack APS + SSIAP 1 + SST + habilitation électrique', 'APS + SSIAP 1'),
    ('Formation Agent de protection physique des personnes (A3P) - garde du corps', 'A3P'),
    ('Formation Dirigeant d’entreprise de sécurité privée (DESP)', 'DIRIGEANT initial'),
    ('VAE TOTALE Dirigeant d’entreprise de sécurité privée', 'DIRIGEANT VAE'),
    ('Formation SSIAP3 - diplôme de chef de service', 'SSIAP 3'),
    ('Formation SSIAP 2', 'SSIAP 2'),
    ('MAC APS', 'MAC APS'),
    ('Assurer les missions de chef de poste en sécurité privée (CPSP)', 'CPSP'),
])
def test_catalogue_families(title, family):
    assert training_family(title) == family


def catalogue():
    return {'sessions':[
        {'id':'v1','name':'VTC janvier · Puget','training_type':'VTC','date_start':'2027-01-04','date_end':'2027-02-04','trainees':[]},
        {'id':'v2','name':'VTC février','training_type':'VTC','date_start':'2027-02-04','date_end':'2027-03-04','trainees':[]},
        {'id':'a1','name':'APS janvier','training_type':'APS','date_start':'2027-01-04','date_end':'2027-02-04','trainees':[]},
        {'id':'archive','name':'VTC archivée','training_type':'VTC','archived':True},
        {'id':'old','name':'VTC terminée','training_type':'VTC','date_end':'2020-01-01'},
        {'id':'other','name':'VTC partenaire','training_type':'VTC','partner_id':'other'},
    ]}


def prepare(site, *, state='accepted', full=True):
    site.gate.switch('integrale',0,'fixture')
    site.local.write_text(json.dumps(catalogue()))
    row = {'folder_id':'100000','first_name':'Anne','last_name':'Exemple','state':state,
           'title':'Formation VTC tout inclus','session_start_date':'2027-01-04','session_end_date':'2027-02-04'}
    site.vault.put(directory.record_key(site.owner), {'checked':time.time()-10,'rows':{'100000':row}})
    if full:
        watch.watch(site.vault,site.owner,row)
        site.vault.put(watch.key(site.owner,'100000'), {'checked':time.time(), 'row':row,
            'fields':{**row,'birth_date':'1988-02-12','email':'anne@example.invalid','phone':'0600000000','total_incl':'1500.00'}})
    site.legacy.INTEGRALE_PARTNER_ID='integrale'
    site.legacy._session_trainees_list=lambda group:group['trainees']
    site.legacy._new_session_trainee=lambda group, fields:{**fields,'id':'new-trainee'}
    site.legacy._apply_pending_cnaps_imports_for_trainee=Mock()
    site.legacy.increment_partner_trainee_usage=Mock()
    return row


def test_session_filter_never_falls_back_to_other_trainings_or_partners():
    row={'title':'Formation VTC', 'session_start_date':'2027-01-04','session_end_date':'2027-02-04'}
    result=matching_sessions(catalogue(),'integrale',row,today='2026-11-11')
    assert [s['id'] for s in result]==['v1','v2'] and result[0]['dates_match']
    assert matching_sessions(catalogue(),'integrale',dict(row,title='Formation inconnue'),today='2026-11-11')==[]
    ssiap={'sessions':[{'id':'s1','name':'SSIAP 1','training_type':'SSIAP'}, {'id':'s3','name':'SSIAP 3','training_type':'SSIAP'}]}
    assert [s['id'] for s in matching_sessions(ssiap,'integrale',{'title':'Formation SSIAP3'})]==['s3']


def test_waiting_is_not_accepted_and_gets_never_contact_edof(site):
    prepare(site,state='validated',full=False)
    assert site.client.get(BASE+'/journey').json['state']=='waiting'
    assert not site.client.get(BASE+'/journey').json['can_register']
    assert site.client.get(BASE+'/registration').status_code==409
    assert site.client.post(BASE+'/create-trainee',data={'csrf':site.csrf,'session_id':'v1'},headers=HEADERS).status_code==409
    assert not json.loads(site.local.read_text())['sessions'][0]['trainees']


def test_cached_acceptance_and_prefilled_registration_are_atomic_and_idempotent(site):
    prepare(site)
    result=site.client.get(BASE+'/registration')
    assert result.status_code==200 and result.json['ready']
    html=result.json['html']
    assert 'anne@example.invalid' in html and 'value="v1"' in html and 'value="v2"' in html
    assert 'value="a1"' not in html and 'VTC partenaire' not in html
    payload={'csrf':site.csrf,'session_id':'v1'}
    # The server also validates the family if a client tampers with the selected ID.
    assert site.client.post(BASE+'/create-trainee',data={**payload,'session_id':'a1'},headers=HEADERS).status_code==409
    for _ in range(2):
        response=site.client.post(BASE+'/create-trainee',data=payload,headers=HEADERS)
        assert response.status_code==200 and response.json['registered']
        assert response.json['link']['url']=='/session/v1/stagiaire/new-trainee'
    saved=json.loads(site.local.read_text())
    assert len(saved['sessions'][0]['trainees'])==len(saved['wedof_links'])==1
    learner=saved['sessions'][0]['trainees'][0]
    assert learner['email']=='anne@example.invalid' and learner['training_price']=='1500.00'
    assert learner['financing_type']=='CPF'
    assert site.client.get(BASE+'/journey').json['link']['session_name']=='VTC janvier · Puget'


def test_newer_cancellation_supersedes_cached_acceptance(site):
    row=prepare(site)
    site.vault.put(directory.record_key(site.owner), {'checked':time.time()+1,'rows':{'100000':dict(row,state='canceled')}})
    assert site.client.get(BASE+'/journey').json['state']=='canceled'
    assert site.client.get(BASE+'/registration').status_code==409
    assert site.client.post(BASE+'/create-trainee',data={'csrf':site.csrf,'session_id':'v1'},headers=HEADERS).status_code==409


def test_missing_full_read_is_loading_and_registration_is_not_invented(site):
    prepare(site,full=False)
    assert not site.client.get(BASE+'/registration').json['ready']
    assert site.client.post(BASE+'/create-trainee',data={'csrf':site.csrf,'session_id':'v1'},headers=HEADERS).status_code==409
    assert not json.loads(site.local.read_text())['sessions'][0]['trainees']


def test_watch_is_scoped_and_protected(site):
    prepare(site,state='validated',full=False)
    assert site.client.post(BASE+'/journey/watch',data={'csrf':'wrong'},headers=HEADERS).status_code==403
    assert site.client.post(BASE+'/journey/watch',data={'csrf':site.csrf},headers=HEADERS).status_code==200
    with site.client.session_transaction() as session:
        session['admin_role']='viewer'
    assert site.client.post(BASE+'/journey/watch',data={'csrf':site.csrf},headers=HEADERS).status_code==403
    assert not site.client.get(BASE+'/journey').json['can_watch']
    with site.client.session_transaction() as session:
        session['admin_role']='admin'
        session['admin_username']='other-admin'
    assert site.client.get(BASE+'/registration').status_code==404


def test_targeted_read_reuses_witness_honors_spacing_and_updates_state(site):
    row=prepare(site,state='validated',full=False)
    watch.watch(site.vault,site.owner,row)
    target='https://'+EDOF_HOST+API_PREFIX+'100000'
    raw={'id':'100000','currentState':'accepted','attendee':{'firstName':'Anne','lastName':'Exemple','email':'anne@example.invalid','birthDate':'1988-02-12'},
         'trainingActionInfo':{'title':row['title'],'sessionStartDate':'2027-01-04','sessionEndDate':'2027-02-04','totalIncl':1500}}
    reply=Mock(status=200,url=target)
    reply.body.return_value=json.dumps(raw).encode()
    context=Mock(); context.request.get.return_value=reply
    witness=Mock(method='GET',url='https://'+EDOF_HOST+API_PREFIX+'pad')
    witness.all_headers.return_value={'authorization':'fixture','cookie':'must-not-copy'}
    watch.fill(context,witness,site.vault,site.owner,EDOF_HOST,API_PREFIX)
    assert site.client.get(BASE+'/journey').json['state']=='accepted'
    assert site.client.get(BASE+'/registration').json['ready']
    watch.fill(context,witness,site.vault,site.owner,EDOF_HOST,API_PREFIX)
    context.request.get.assert_called_once()
    assert context.request.get.call_args.kwargs['max_redirects']==0
    assert 'cookie' not in context.request.get.call_args.kwargs['headers']
    context.request.put.assert_not_called()


def test_targeted_read_rejects_wrong_identity_and_expired_watch(site):
    row=prepare(site,state='validated',full=False)
    watch.watch(site.vault,site.owner,row)
    context=Mock()
    witness=Mock(method='GET',url='https://'+EDOF_HOST+API_PREFIX+'pad')
    witness.all_headers.return_value={}
    reply=Mock(status=200,url='https://'+EDOF_HOST+API_PREFIX+'100000')
    reply.body.return_value=json.dumps({'id':'100000','currentState':'accepted','attendee':{'firstName':'Autre','lastName':'Personne'}}).encode()
    context.request.get.return_value=reply
    watch.fill(context,witness,site.vault,site.owner,EDOF_HOST,API_PREFIX)
    assert not site.vault.get(watch.key(site.owner,'100000'))
    with site.vault.connect() as db:
        db.execute('UPDATE edof_enrolment_watch SET attempted=0,expires=0')
    watch.fill(context,witness,site.vault,site.owner,EDOF_HOST,API_PREFIX)
    context.request.get.assert_called_once()
