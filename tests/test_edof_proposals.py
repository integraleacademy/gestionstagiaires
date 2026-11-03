"""A private synthetic EDOF portal; no external requests or real notifications."""
from copy import deepcopy
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import Mock
from werkzeug.datastructures import MultiDict

import pytest

import edof_directory as directory
import edof_proposal as offer
import edof_proposal_jobs as jobs
from cpf_provider import ProviderStore
from edof_gmail import Vault, connector_key
from edof_server_browser import API_PREFIX, EDOF_HOST
from test_integrale_edof_dashboard import site

FOLDER = "100002"
URL = "https://"+EDOF_HOST+API_PREFIX+FOLDER
DAY = (dt.datetime.now(offer.PARIS).date()+dt.timedelta(days=50)).isoformat()
END = (dt.date.fromisoformat(DAY)+dt.timedelta(days=10)).isoformat()
OPTIONS = {"trainingPaces":{"p":"Temps partiel"},"typeOfTrainingCourse":{"2":"Parcours individualisé"},
           "teachingModalities":{"0":"Présentiel","1":"Mixte","2":"À distance"},
           "countryCode":{"FR":"France"}, "roadType":{"R":"Rue"}, "repetitionIndex":{"BIS":"Bis"}}


def official():
    return {"id":FOLDER,"trainingId":directory.SIRET+"_offre","attendee":{"firstName":"Anne","lastName":"Exemple"},
            "currentState":"notProcessed","minDate":DAY,"ableToValidate":True,"changingStateDate":DAY,
            "trainingActionInfo":{"title":"Formation test","trainingGoal":"Objectifs du parcours","expectedResult":"Résultats du parcours",
             "content":"Programme du parcours","sessionStartDate":None,"sessionEndDate":None,"teachingModalities":"2",
             "typeOfTrainingCourse":2,"trainingPaces":["p"],"weeklyDuration":None,"indicativeDuration":None,
             "hoursInCenter":0,"hoursInCompany":0,"vat":1400,"totalIncl":1400,"doesPriceIncludeMontantFraisExam":"NONE",
             "sessionId":directory.SIRET+"_session","conditionsPrerequisitesDetails":"Conditions catalogue",
             "infosBlocsCompetences":{"blocsModifiables":True,"blocsRetenus":[{"code":"BC01","libelle":"Surveiller"}],"blocsExclus":[]}}}


def terms(raw):
    source=offer.project(raw)
    submitted={**source["values"],"priceTotal":"1500,00","sessionStartDate":DAY,"sessionEndDate":END,
               "indicativeDuration":"35","weeklyDuration":"35","hoursInCenter":"28","hoursInCompany":"7"}
    return offer.validate(submitted,source,OPTIONS)


class Portal:
    def __init__(self):
        self.raw=official()
        self.writes=[]
        self.refused=False
        self.drop_reply=False
        self.ignore_edit=False
    def response(self,url,state,data):
        return SimpleNamespace(status=state,url=url,json=lambda:deepcopy(data),body=lambda:json.dumps(data).encode(),dispose=lambda:None)
    def get(self,url,**args):
        assert args["max_redirects"]==0
        if url==URL:
            return self.response(url,200,self.raw)
        assert url.startswith("https://"+EDOF_HOST+"/edof-api/v1/api/public/")
        key = next(k for k,v in offer.ENUMS.items() if v==url.rsplit("/",1)[1])
        return self.response(url,200,[{"code":k,"label":v} for k,v in OPTIONS[key].items()])
    def put(self,url,**args):
        assert args["max_redirects"]==0 and args["headers"]["Current-Siret"]==directory.SIRET
        assert args["headers"]["x-icdc-dgefp-token"]=="synthetic"
        assert "cookie" not in args["headers"]
        body=args["data"]
        self.writes.append(url)
        if url==URL:
            assert body["attendee"]==self.raw["attendee"]
            if not self.ignore_edit:
                self.raw=deepcopy(body)
        else:
            assert url==URL+"/status" and body=={"state":"VALIDATED"}
            if self.refused:
                return self.response(url,422,{"message":"Certification non habilitée"})
            self.raw["currentState"]="validated"
            if self.drop_reply:
                raise TimeoutError()
        return self.response(url,200,self.raw)


@pytest.fixture
def conn(tmp_path):
    gate=ProviderStore(tmp_path)
    gate.switch("integrale",0,"admin")
    vault=Vault(tmp_path,connector_key("synthetic-private-connector"*2))
    portal=Portal()
    witness=Mock(method="GET",url=URL)
    witness.all_headers.return_value={"x-icdc-dgefp-token":"synthetic","cookie":"do-not-forward"}
    return SimpleNamespace(path=tmp_path,gate=gate,vault=vault,portal=portal,witness=witness,ctx=SimpleNamespace(request=portal))


def run(c,spec):
    return jobs.perform(c.ctx,c.witness,spec,c.path,c.vault,API_PREFIX,EDOF_HOST)


def prepare(c):
    row=directory.project(c.portal.raw)
    token=jobs.request_read(c.path,"owner",row)
    assert token==jobs.request_read(c.path,"owner",row)
    read=jobs.next_job(c.path,c.gate.state())
    assert read["mode"]=="proposal_read" and jobs.reading(c.path,read)
    assert run(c,read)["code"]=="proposal_loaded" and not c.portal.writes
    jobs.finish_read(c.path,read,"OK")
    source=c.vault.get(jobs.source_key("owner",FOLDER))
    values=terms(c.portal.raw)
    assert jobs.enqueue(c.path,"owner",1,row,source,values)=="queued"
    spec=jobs.next_job(c.path,c.gate.state())
    assert jobs.enqueue(c.path,"owner",1,row,source,values)=="queued"
    assert jobs.next_job(c.path,c.gate.state())==spec
    return spec


def test_real_proposal_edit_then_validate_and_apply_verified_receipt(conn):
    spec=prepare(conn)
    result=run(conn,spec)
    assert result["code"]=="proposal_confirmed" and conn.portal.writes==[URL,URL+"/status"]
    assert conn.portal.raw["trainingActionInfo"]["totalIncl"]==1500
    assert conn.portal.raw["trainingActionInfo"]["conditionsPrerequisitesDetails"]=="Conditions catalogue"
    jobs.complete(conn.path,spec,result,"Confirmée")
    assert jobs.next_job(conn.path,conn.gate.state()) is None
    snap={"checked":0,"rows":{FOLDER:directory.project(official())},"pending_ids":{FOLDER}}
    latest=jobs.with_receipts(conn.path,"owner",snap)
    assert latest["rows"][FOLDER]["state"]=="validated" and FOLDER not in latest["pending_ids"]
    assert jobs.with_receipts(conn.path,"other",snap)==snap


def test_ambiguous_validation_reconciles_without_repeating_a_write(conn):
    spec=prepare(conn)
    conn.portal.drop_reply=True
    with pytest.raises(TimeoutError):
        run(conn,spec)
    jobs.complete(conn.path,spec,{"code":"timeout"},"Vérification nécessaire")
    assert jobs.record(conn.path,FOLDER,"owner")["status"]=="uncertain"
    jobs.recheck(conn.path,FOLDER,"owner")
    rec=jobs.next_job(conn.path,conn.gate.state())
    assert rec["mode"]=="proposal_check"
    result=run(conn,rec)
    jobs.complete(conn.path,rec,result,"OK")
    assert jobs.record(conn.path,FOLDER,"owner")["status"]=="confirmed"
    assert conn.portal.writes==[URL,URL+"/status"]


@pytest.mark.parametrize("case",["other_state","stale","edit_not_recorded","refused","paused","wrong_witness"])
def test_no_false_confirmation_or_extra_write(conn,case):
    spec=prepare(conn)
    if case=="other_state":conn.portal.raw["currentState"]="canceled"
    if case=="stale":conn.portal.raw["trainingActionInfo"]["trainingGoal"]="Une autre proposition"
    if case=="edit_not_recorded":conn.portal.ignore_edit=True
    if case=="refused":conn.portal.refused=True
    if case=="paused":conn.gate.switch("wedof",1,"admin")
    if case=="wrong_witness":conn.witness.url=URL.replace(EDOF_HOST,"example.invalid")
    result=run(conn,spec)
    assert result["code"]!="proposal_confirmed"
    assert conn.portal.writes==([URL,URL+"/status"] if case=="refused" else [URL] if case=="edit_not_recorded" else [])
    if case=="refused": assert result["proposal_message"]=="Certification non habilitée"


def test_scope_and_amount_duration_validation_before_sending():
    raw=official()
    row=directory.project(raw)
    assert directory.in_scope(row)
    assert not directory.in_scope({**row,"request_date":"2025-12-31"})
    assert not directory.in_scope({**row,"session_start_date":"2025-12-31"})
    assert FOLDER in directory.with_pending({"checked":2,"rows":{}},{"checked":1,"rows":{FOLDER:row}})["rows"]
    src=offer.project(raw)
    good=terms(raw)
    for updates in ({"hoursInCompany":"25"},{"sessionEndDate":""},{"sessionStartDate":"2026-01-01"},
                    {"exam":"INCLUDED","montantFraisCertificationInclus":"1700"},{"weeklyDuration":"0"},
                    {"additionalFees":"70","additionalFeesDetails":""},{"teachingModalities":"0","roadName":""},
                    {"priceTotal":"50","vatInclTax20":"60"},{"blocks":[]},{"trainingPaces":["fake"]}):
        with pytest.raises(ValueError):
            offer.validate({**good,**updates},src,OPTIONS)


def test_dashboard_draft_load_send_auth_and_waiting_tab(site):
    client=site.client
    base=f"/admin/edof-test/dossiers/{FOLDER}/proposal/"
    detail=f"/admin/edof-test?section=requests&tab=request&folder={FOLDER}"
    assert "Proposition de commande EDOF" in client.get(detail).text
    assert client.post(base+"read").status_code==403
    result=client.post(base+"draft",data={"csrf":site.csrf,"priceTotal":"1510","sessionStartDate":DAY},follow_redirects=True)
    assert "Brouillon enregistré" in result.text and 'value="1510"' in result.text
    result=client.post(base+"read",data={"csrf":site.csrf},follow_redirects=True)
    assert "attente du connecteur" in result.text
    raw=official();source=offer.project(raw)
    site.vault.put(jobs.source_key(site.owner,FOLDER),source)
    site.vault.put(jobs.option_key(site.owner),OPTIONS)
    values=terms(raw)
    submitted=MultiDict({k:v for k,v in values.items() if k not in {"blocks","trainingPaces"}})
    submitted.update({"blocks":"BC01","trainingPaces":"p","csrf":site.csrf,"signature":source["signature"],"confirm":"yes","priceTotal":"1500"})
    assert "désactivé" in client.post(base+"submit",data=submitted,follow_redirects=True).text
    site.gate.switch("integrale",0,"admin")
    assert "En attente d’envoi" in client.post(base+"submit",data=submitted,follow_redirects=True).text
    rec=jobs.record(site.store.directory,FOLDER,site.owner)
    updated={**raw,"currentState":"validated","trainingActionInfo":offer.amended(raw,values,OPTIONS)["trainingActionInfo"]}
    jobs.complete(site.store.directory,rec,{"code":"proposal_confirmed","proposal_receipt":directory.project(updated)},"Confirmée")
    assert FOLDER in client.get("/admin/edof-test?section=requests&tab=waiting").text
    assert FOLDER not in client.get("/admin/edof-test?section=requests&tab=request").text
    with client.session_transaction() as session:
        session["admin_role"]="viewer"
    for endpoint in ("draft","submit","read","recheck"):
        assert client.post(base+endpoint,data=submitted).status_code==403


def test_tax_breakdown_and_selected_catalogue_blocks_are_preserved():
    raw=official()
    raw["trainingActionInfo"]["infosBlocsCompetences"]["blocsExclus"]=[{"code":"BC02","libelle":"Intervenir"}]
    src=offer.project(raw)
    values={**terms(raw),"priceTotal":"1700","vatInclTax5":"105,50","vatInclTax20":"120","blocks":["BC02"],
            "teachingModalities":"0","countryCode":"FR","roadType":"R","roadName":"du Centre","city":"Puget-sur-Argens",
            "zipCode":"83480","exam":"INCLUDED","montantFraisCertificationInclus":"100"}
    v=offer.validate(values,src,OPTIONS)
    a=offer.amended(raw,v,OPTIONS)["trainingActionInfo"]
    assert (a["vat"],a["vatExclTax5"],a["vatExclTax20"],a["totalIncl"],a["totalExcl"])==(1474.5,100,100,1700,1674.5)
    assert a["presenceFraisCertification"] and a["fraisCertificationInclus"]
    assert a["infosBlocsCompetences"]["blocsRetenus"]==[{"code":"BC02","libelle":"Intervenir"}]
    assert a["address"]["city"]=="Puget-sur-Argens"


def test_interrupted_edit_can_be_reloaded_without_another_put(conn):
    spec=prepare(conn)
    assert jobs.fence(conn.path,spec,"saving")
    jobs.complete(conn.path,spec,{"code":"timeout"},"Connexion interrompue")
    jobs.recheck(conn.path,FOLDER,"owner")
    rec=jobs.next_job(conn.path,conn.gate.state())
    assert run(conn,rec)["code"]=="proposal_resume"
    assert not conn.portal.writes


def test_duplicate_validation_of_unchanged_offer_sends_only_the_status(conn):
    values=terms(conn.portal.raw)
    conn.portal.raw=offer.amended(conn.portal.raw,values,OPTIONS)
    src=offer.project(conn.portal.raw)
    jobs.enqueue(conn.path,"owner",1,directory.project(conn.portal.raw),src,values)
    assert run(conn,jobs.next_job(conn.path,conn.gate.state()))["code"]=="proposal_confirmed"
    assert conn.portal.writes==[URL+"/status"]
