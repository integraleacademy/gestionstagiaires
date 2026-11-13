from contextlib import closing

import pytest

import edof_directory as directory
import edof_dossier_dates as dates
from integrale_edof_dashboard import category
from integrale_edof_sync import observe_pending, process_directory, stage_dates
from test_integrale_edof_dashboard import site
from test_edof_navigation import table_ids


def folder(state="validated", **kwargs):
    raw = {"id": "123456", "currentState": state, "changingStateDate": "2026-10-23",
           "trainingActionInfo": {"sessionStartDate": "2026-12-15"}}
    return directory.project({**raw, **kwargs})


@pytest.mark.parametrize("status,day", [("refused", "2026-11-03"), ("inProgress", "2026-10-30")])
def test_ft_dates_are_specific_to_the_solicitation(status, day):
    request = {"fundingType": 9, "status": status, "submissionDate": "2026-10-30"}
    if status == "refused":
        request["decisionDate"] = "2026-11-03"
    row = folder(trainingActionInfo={"solicitations": [
        {"fundingType": 1, "status": status, "decisionDate": "2026-11-04"}, request]},
        history=[{"state": "notProcessed", "date": "2026-10-01"}])
    assert dates.source_dates(row, category) == ("2026-10-01", day)


def test_refusal_with_no_date_never_borrows_an_earlier_refusal_or_parent_status():
    requests = [{"fundingType": 9, "status": "refused", "submissionDate": "2026-09-01", "decisionDate": "2026-09-02"},
                {"fundingType": 9, "status": "refused", "submissionDate": "2026-11-01"}]
    row = folder(trainingActionInfo={"solicitations": requests})
    assert category(row) == "ft_refused" and dates.source_dates(row, category) == ("", "")
    assert dates.source_dates(folder("notProcessed"), category) == ("2026-10-23", "2026-10-23")


def test_billing_payment_dates_follow_the_displayed_stage():
    row = folder("serviceDoneValidated", currentBillingState="billed", billingDate="2026-11-02")
    assert category(row) == "invoiced" and dates.source_dates(row, category)[1] == "2026-11-02"
    row["payment_state"] = "issued"
    assert category(row) == "paid" and not dates.source_dates(row, category)[1]


def test_export_distinguishes_filing_status_and_ft():
    csv = ("N° de dossier;Nom du titulaire;Prénom du titulaire;Date d’inscription;Date de la dernière action;"
           "Statut du dossier;Statut de l’abondement France Travail;Date de refus de l’abondement France Travail\n"
           "123456;Test;Marie;01/10/2026;05/11/2026;En attente;Refusé;03/11/2026\n")
    row = directory.csv_snapshot(csv.encode(), {"numberOfItems": 1, "items": []}, {})["rows"]["123456"]
    assert category(row) == "ft_refused"
    assert dates.source_dates(row, category) == ("2026-10-01", "2026-11-03")


def test_observation_is_retained_per_owner_and_changes_only_with_status(site):
    def save(method, when, row, owner):
        method(site.store, {"checked": when, "rows": {"123456": row}}, owner=owner)
    initial = folder("notProcessed")
    save(observe_pending, 120, initial, site.owner)
    waiting = folder(trainingActionInfo={"solicitations": [{"fundingType": 9, "status": "refused"}]})
    save(process_directory, 200, waiting, site.owner)
    save(observe_pending, 190, initial, site.owner)
    save(process_directory, 300, waiting, site.owner)
    save(observe_pending, 400, initial, "other")
    with closing(site.gate.connect()) as db:
        saved = stage_dates(db, site.owner)
        assert stage_dates(db, "other")["123456"]["observed"] == 400
    row = {**waiting, "kind": category(waiting)}
    dates.annotate([row], saved, 300, category)
    assert saved["123456"]["observed"] == 200 and row["filed_label"] == "23/10/2026"
    assert row["stage_observed"] and row["stage_order"] == 200


@pytest.mark.parametrize("group,tab,state", [("requests", "waiting", "validated"), ("requests", "request", "notProcessed"),
    ("training", "accepted", "accepted"), ("billing", "paid", "paid"), ("closed", "refused", "refused"), ("all", "all", "validated")])
def test_every_list_sorts_by_filing_before_pagination(site, group, tab, state):
    base = folder(state)
    rows = {}
    for index in range(28):
        key = str(100000 + index)
        rows[key] = {**base, "folder_id": key, "filed_at": f"2026-10-{index + 1:02}",
                     "session_start_date": f"2026-11-{28 - index:02}"}
    rows["999999"] = {"folder_id": "999999", "state": state, "session_start_date": "2026-12-01"}
    site.vault.put(directory.record_key(site.owner), {"checked": 10000, "rows": rows})
    url = f"/admin/edof-test?section=state&group={group}&tab={tab}"
    first, last = site.client.get(url).text, site.client.get(url+"&page=2").text
    assert table_ids(first) == [str(100000+i) for i in range(27, 2, -1)]
    assert table_ids(last) == ["100002", "100001", "100000", "999999"]
    assert "Demande du 28/10/2026" in first and "Passage dans le statut" in first
    assert "Date de changement inconnue" in last and "Statut observé le" in last


def test_exact_refusal_appears_in_table_and_detail_with_paris_time(site):
    row = folder(trainingActionInfo={"sessionStartDate": "2026-12-15", "solicitations": [
        {"fundingType": 9, "status": "refused", "responseDate": "2026-11-02T23:15:00Z"}]})
    site.vault.put(directory.record_key(site.owner), {"checked": 10000, "rows": {"123456": row}})
    url = "/admin/edof-test?section=state&group=requests&tab=ft_refused"
    for page in (site.client.get(url), site.client.get(url+"&folder=123456")):
        assert page.status_code == 200 and "03/11/2026 à 00 h 15" in page.text
    assert dates.instant(dates.stamp("2026-10-25T02:45:00+02:00")) < dates.instant(dates.stamp("2026-10-25T02:10:00+01:00"))
    assert dates.display(dates.stamp("31/02/2026")) == ""


def test_creation_fallback_and_repeated_refusals(site):
    def refusal(requested, decided=None):
        item = {"fundingType": 9, "status": "refused", "submissionDate": requested, "decisionDate": decided}
        return folder(creationDate="2026-08-12", trainingActionInfo={"solicitations": [item]})
    before, after = refusal("2026-10-01", "2026-10-13"), refusal("2026-11-01")
    for when, row in ((100, before), (200, after)):
        process_directory(site.store, {"checked": when, "rows": {row["folder_id"]: row}}, owner=site.owner)
    row = {**after, "kind": category(after)}
    with closing(site.gate.connect()) as db:
        dates.annotate([row], stage_dates(db, site.owner), 230, category)
    assert row["creation_only"] and row["filed_label"] == "12/08/2026"
    assert row["stage_observed"] and row["stage_order"] == 200


def test_legacy_view_keeps_its_first_observation_after_next_sync(site):
    row = folder(trainingActionInfo={"sessionStartDate": "2026-12-01", "solicitations": [{"fundingType": 9, "status": "refused"}]})
    def snapshot(when):
        return {"checked": when, "rows": {"123456": row}}
    site.vault.put(directory.record_key(site.owner), snapshot(100))
    assert site.client.get("/admin/edof-test?tab=ft_refused").status_code == 200
    process_directory(site.store, snapshot(800), owner=site.owner)
    with closing(site.gate.connect()) as db:
        assert stage_dates(db, site.owner)["123456"]["observed"] == 100


def test_undated_ft_refusal_explicitly_labels_observation_in_list_and_detail(site):
    row = folder(trainingActionInfo={"sessionStartDate": "2026-12-01", "solicitations": [
        {"fundingType": 9, "status": "refused"}]})
    site.vault.put(directory.record_key(site.owner), {"checked": 1793875080, "rows": {"123456": row}})
    url = "/admin/edof-test?section=state&group=requests&tab=ft_refused"
    for page in (site.client.get(url), site.client.get(url + "&folder=123456")):
        assert page.status_code == 200
        assert "Date du refus inconnue" in page.text
        assert "Statut observé le" in page.text
        assert "Constaté le" not in page.text


def test_official_nested_states_return_date_and_reason(site):
    row = folder(states={'notProcessed': {'date':'2026-09-10T08:00:00Z'}, 'validated':{'date':'2026-09-12'}},
                 trainingActionInfo={'sessionStartDate':'2026-12-01','solicitations':[{'fundingType':9,'status':'refused','submissionDate':'2026-10-01',
                                                      'returnDate':'2026-10-03T14:30:00Z','refusalReason':'Projet non retenu'}]})
    assert dates.source_dates(row,category)==('2026-09-10T10:00:00+02:00','2026-10-03T16:30:00+02:00')
    site.vault.put(directory.record_key(site.owner),{'checked':1,'rows':{'123456':row}})
    page=site.client.get('/admin/edof-test?folder=123456&group=requests&tab=ft_refused')
    assert page.status_code==200 and 'Projet non retenu' in page.text and '03/10/2026 à 16 h 30' in page.text
    assert '01/10/2026' in page.text


def test_missing_refusal_dates_are_enriched_from_exact_dossier(site):
    from types import SimpleNamespace as NS
    import json
    raw={'id':'123456','currentState':'validated','attendee':{'firstName':'Anne','lastName':'Exemple'},
         'states':{'notProcessed':{'date':'2026-10-01'}},'trainingActionInfo':{'sessionStartDate':'2026-12-01',
         'solicitations':[{'fundingType':9,'status':'refused','submissionDate':'2026-10-02','returnDate':'2026-10-04','refusalReason':'Motif officiel'}]}}
    old=directory.project(raw)
    for k in ('funding_at','filed_at','funding_refusal_reason'):old.pop(k,None)
    site.vault.put(directory.record_key(site.owner),{'checked':1,'rows':{'123456':old}})
    host='of.moncompteformation.gouv.fr'
    prefix=f'/edof-api/v1/api/private/siret/{directory.SIRET}/organisms/current/registration-folders/'
    witness=NS(method='GET',url='https://'+host+prefix+'pad',all_headers=lambda:{})
    calls=[]
    def read(url,**kwargs):
        calls.append(url)
        return NS(url=url,status=200,body=lambda:json.dumps(raw).encode(),dispose=lambda:None)
    dates.enrich_refusals(NS(request=NS(get=read)),witness,site.vault,site.owner,host,prefix)
    saved=site.vault.get(directory.record_key(site.owner),keep=True)
    assert saved['checked']==1 and saved['rows']['123456']['funding_at']=='2026-10-04'
    assert saved['rows']['123456']['filed_at']=='2026-10-01'
    dates.enrich_refusals(NS(request=NS(get=read)),witness,site.vault,site.owner,host,prefix)
    assert len(calls)==1
