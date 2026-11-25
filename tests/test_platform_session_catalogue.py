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
