import copy
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as host
import session_catalogue as cat


@pytest.fixture
def row():
    return dict(id="source-1",slug="aps",centre="puget",start="2098-03-03",end="2098-04-04",exam="2098-04-07",
                capacity=12, visibility="public",aliases=[],target="",remote_start="",remote_end="",onsite_start="",onsite_end="")


def test_adopt_move_cancel_reopen(row):
    current={"sessions":[dict(id="local",name="APS mars",training_type="APS",partner_id=host.INTEGRALE_PARTNER_ID,
                             date_start=row["start"],date_end=row["end"],exam_date=row["exam"],trainees=[
            {"id":"A","first_name":"PRIVE"},{"id":"B","registration_cancelled":True}])]}
    with host.app.app_context():
        cat.reconcile(host,current,[row])
        with pytest.raises(cat.NoChange):
            cat.reconcile(host,current,[row])
        item, = cat.feed(host,current["sessions"])
        assert item["sold"]==1 and "PRIVE" not in json.dumps(item)
        moved={**row,"start":"2098-05-05","end":"2098-06-06","exam":"2098-06-09"}
        cat.reconcile(host,current,[moved])
        local, = current["sessions"]
        assert local["id"]=="local" and len(local["trainees"])==2 and local["date_start"]==moved["start"]
        assert row["start"] in [a["start"] for a in local[cat.STATE]["aliases"]]
        cat.reconcile(host,current,[])
        assert cat.feed(host,[local])[0]["visibility"]=="closed"
        cat.reconcile(host,current,[moved])
        assert cat.feed(host,[local])[0]["visibility"]=="public"


def test_new_ambiguous_other_tenant(row):
    data={"sessions":[]}
    with host.app.app_context():
        cat.reconcile(host,data,[row])
        dest,=data["sessions"]
        assert dest[cat.STATE]["id"]==row["id"] and dest["trainees"]==[]
        a={k:v for k,v in dest.items() if k!=cat.STATE}
        data={"sessions":[dict(a,id="l1"),dict(a,id="l2"),dict(a,id="external",partner_id="external")]}
        result=cat.reconcile(host,data,[row])
        assert result["conflicts"]==1 and len(data["sessions"])==3
        assert not any(t.get(cat.STATE) for t in data["sessions"])
        cat.reconcile(host,data,[{**row,"target":"l2"}])
        assert data["sessions"][1][cat.STATE]["id"]==row["id"]
        assert len(cat.feed(host,data["sessions"]))==2


def test_existing_wedof_date_review_is_respected(row):
    data={"sessions":[]}
    with host.app.app_context():
        cat.reconcile(host,data,[row]); dest=data["sessions"][0]
        data["wedof_links"]=[{"active": True,"session_id":dest["id"]}]
        cat.reconcile(host,data,[{**row,"start":"2098-03-05"}])
        assert dest["date_start"]==row["start"] and data["session_catalogue_conflicts"]


def test_private_aggregate_endpoint(row, monkeypatch, tmp_path):
    from flask import Flask
    from types import SimpleNamespace
    app=Flask("catalogue-test")
    data={"sessions":[]}
    with host.app.app_context():
        cat.reconcile(host,data,[row])
    path=tmp_path/"data.json";path.write_text(json.dumps(data))
    facade=SimpleNamespace(**{k:v for k,v in vars(host).items() if k not in ("app","DATA_FILE")},app=app,DATA_FILE=str(path))
    cat.register(facade)
    monkeypatch.setenv("SESSION_CATALOG_TOKEN","local-test")
    client=app.test_client(); endpoint="/api/integrations/session-availability"
    assert client.get(endpoint).status_code==401
    reply=client.get(endpoint,headers={"Authorization":"Bearer local-test"})
    assert reply.status_code==200 and reply.json["sessions"][0]["sold"]==0


def test_ssiap_variants_share_active_enrolments_and_preserve_wedof_period(row):
    row.update(slug="ssiap-1", start="2027-02-11", standard_start="2027-02-15", end="2027-02-26", exam="")
    training = dict(id="conserve", name="SSIAP 1", training_type="SSIAP 1", date_start=row["standard_start"],
                    date_end=row["end"], exam_date=row["exam"], trainees=[{"id":"inscrit"}])
    data = {"sessions":[training], "wedof_links":[{"active":True, "session_id":"conserve"}]}
    with host.app.app_context():
        assert cat.reconcile(host, data, [row]) == {"conflicts":0}
    assert len(data["sessions"]) == 1 and training["ssiap_pathways"]["sst_dates"] == ["2027-02-11", "2027-02-12"]
    merged, refresher, renewal = cat.feed(host, [training])
    assert (refresher["sold"], refresher["start"], renewal["end"]) == (1, "2027-02-25", "2027-02-26")
    assert (merged["start"], merged["standard_start"], merged["sold"]) == ("2027-02-11", "2027-02-15", 1)
    assert not any(alias["start"] == "2027-02-15" for alias in merged["aliases"])


def test_promotion_name_sales_scope_and_history_survive_delete_recreate(row):
    legacy = dict(id="existant", name="Nom de l’ancienne fiche", nom="Ancien", training_type="APS",
                  date_start=row["start"],date_end=row["end"],exam_date=row["exam"],trainees=[
                      {"id":"vendu","contract":{"signed":True}},{"id":"annule","registration_cancelled":True}])
    data = {"sessions":[legacy]}
    catalogue = {**row,"name":"Promotion Atlas","custom_name":True,"gestion_only":False,"edited":True,"venue":"Salle Atlas"}
    active = [row["id"]]
    with host.app.app_context():
        cat.reconcile(host,data,[catalogue],active)
        assert legacy["name"] == legacy["nom"] == catalogue["name"] and legacy["id"] == "existant"
        protected = host._apply_session_update(data,"existant",{"name":"Autre nom"})
        assert protected[1] == 409
        cat.reconcile(host,data,[{**catalogue,"gestion_only":True}],active)
        agg,=cat.feed(host,data["sessions"])
        assert agg["visibility"]=="closed" and not agg["name"] and not agg["venue"] and not legacy.get("archived")
        data["wedof_links"] = [{"active":True,"session_id":"existant","id":"dossier"}]
        moved = {**catalogue,"name":"Promotion Iris","start":"2098-05-06","end":"2098-06-06","exam":""}
        cat.reconcile(host,data,[moved],active)
        agg,=cat.feed(host,data["sessions"])
        assert (legacy["name"],legacy["date_start"],legacy["exam_date"]) == (moved["name"],moved["start"],"")
        assert (agg["visibility"],agg["name"],agg["sold"]) == ("public","Promotion Iris",1)
        assert data["wedof_links"][0]["id"]=="dossier"
        hidden = {**moved,"visibility":"closed","deleted":True,"aliases":[row]}
        next_group = {**moved,"id":"autre","name":"Nouvelle promotion"}
        cat.reconcile(host,data,[next_group,hidden],[next_group["id"]])
        new,old = data["sessions"]
        assert old is legacy and old["archived"] and cat.withdrawn(old)
        assert old["trainees"][0]["contract"]["signed"] and len(old["trainees"])==2
        assert new["id"] != old["id"] and new["trainees"]==[] and not new["archived"]
        assert {r["id"]:(r["visibility"],r["sold"]) for r in cat.feed(host,data["sessions"])} == {
            "platform-source-1":("closed",1), "platform-autre":("public",0)}
        with pytest.raises(cat.NoChange):
            cat.reconcile(host,data,[hidden,next_group],[next_group["id"]])


def test_manifest_distinguishes_past_from_previously_deleted_and_undated(row):
    data={"sessions":[]}
    with host.app.app_context():
        cat.reconcile(host, data, [row], [row["id"]])
        training,=data["sessions"]
        with pytest.raises(cat.NoChange):
            cat.reconcile(host,data,[],[row["id"]])
        assert not training["archived"]
        undated={**row,"start":"","end":"","exam":"","edited":True,"unscheduled":True,"name":"À planifier"}
        assert cat.validate({"version":1,"sessions":[undated]})==[undated]
        cat.reconcile(host,data,[undated],[row["id"]])
        assert not training["archived"] and not training["date_start"] and training["name"]=="À planifier"
        assert cat.feed(host,[training])[0]["visibility"]=="closed"
        cat.reconcile(host,data,[],[])
        assert training["archived"] and cat.withdrawn(training)
        with pytest.raises(cat.NoChange):
            cat.reconcile(host,data,[],[])


def test_ambiguous_restricted_group_hides_offers_until_attached(row):
    roster = dict(name="APS",training_type="APS",date_start=row["start"],date_end=row["end"],exam_date=row["exam"],trainees=[])
    private={**row,"gestion_only":True}
    data={"sessions":[dict(roster,id="l1"),dict(roster,id="l2")]}
    with host.app.app_context():
        assert cat.reconcile(host,data,[private],[row["id"]])["conflicts"]==1
        mask, = [s for s in data["sessions"] if s.get("catalogue_mask")]
        assert mask["archived"] and cat.withdrawn(mask)
        assert cat.feed(host,[mask])[0]["visibility"]=="closed"
        cat.reconcile(host,data,[{**private,"target":"l2"}],[row["id"]])
        assert len(data["sessions"])==2 and data["sessions"][1][cat.STATE]["id"]==row["id"]


def test_changement_niveau_ssiap_retire_aussi_les_parcours_courts(row):
    group={**row,"slug":"ssiap-1","edited":True,"name":"SSIAP 1"}
    data={"sessions":[]}
    with host.app.app_context():
        cat.reconcile(host,data,[group],[group["id"]])
        cat.reconcile(host,data,[{**group,"slug":"ssiap-3","name":"SSIAP 3","aliases":[cat.signature(group)]}],[group["id"]])
    main, refresher, renewal = cat.feed(host,data["sessions"])
    assert main["slug"]=="ssiap-3" and main["visibility"]=="public"
    assert {r["slug"] for r in (refresher, renewal)}=={"recyclage-ssiap-1","remise-a-niveau-ssiap-1"}
    assert all(r["visibility"]=="closed" and r["deleted"] for r in (refresher, renewal))
