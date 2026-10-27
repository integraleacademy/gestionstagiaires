import copy
import json

import pytest

import app as gestion_app
from wedof_automation import build_automation_dashboard


def snapshot(external_id="W1", state="accepted"):
    return {"external_id": external_id, "wedof_state": state, "wedof_type": "cpf",
            "wedof_date_start": "2026-09-07", "wedof_date_end": "2026-10-09",
            "entry_training": {"status": "planned"}, "service_done": {"status": "success"}}


@pytest.mark.parametrize("source", ["folders", "statuses"])
@pytest.mark.parametrize("state", ["accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated"])
def test_manual_classification_moves_unlinked_folder_without_changing_remote_state(source, state):
    folders = [{"externalId": "W1", "type": "cpf", "state": state,
                "trainingActionInfo": {"startDate": "2026-09-07", "endDate": "2026-10-09"}}]
    statuses = [snapshot(state=state), snapshot("W2")]
    anomalies = [{"external_id": "W1", "active": True}]
    original = copy.deepcopy(statuses)
    kwargs = {"statuses": statuses, "manual_anomalies": anomalies}
    dashboard = build_automation_dashboard(folders if source == "folders" else [], **kwargs)
    row = next(row for row in dashboard["rows"] if row["external_id"] == "W1")
    assert row["tab"] == "anomaly"
    assert row["manual_anomaly"] and row["manual_link_required"]
    assert not row["to_associate"]
    assert row["state"] == state
    assert dashboard["stats"]["to_associate"] == 1
    assert dashboard["stats"]["anomaly"] == 1
    assert statuses == original
    anomalies[0]["active"] = False
    restored = build_automation_dashboard(folders if source == "folders" else [], **kwargs)
    assert restored["stats"]["to_associate"] == 2
    assert restored["stats"]["anomaly"] == 0


def test_preexisting_anomaly_is_not_double_counted_or_cleared():
    status = snapshot()
    status["entry_training"]["status"] = "anomaly"
    for active in (True, False):
        dashboard = build_automation_dashboard([], statuses=[status], manual_anomalies=[
            {"external_id": "W1", "active": active}])
        assert dashboard["stats"]["anomaly"] == 1
        assert dashboard["stats"]["to_associate"] == (0 if active else 1)


@pytest.fixture
def anomaly_page(tmp_path, monkeypatch):
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"sessions": [], "wedof_links": [],
        "wedof_automation_status": [snapshot(), snapshot("W2")],
        "wedof_automation_runs": [{"status": "success"}]}), encoding="utf-8")
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(data_file))
    monkeypatch.setattr(gestion_app, "PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(gestion_app, "load_data", lambda **kwargs: json.loads(data_file.read_text()))
    monkeypatch.setattr(gestion_app, "_load_wedof_webhooks", lambda: [])
    monkeypatch.setattr(gestion_app, "_admin_wedof_quota_dashboard", lambda: {"available": False})
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
    response = client.get("/admin/wedof?section=state&tab=to_associate")
    assert response.status_code == 200
    with client.session_transaction() as session:
        csrf = session["wedof_anomaly_csrf"]
    return client, data_file, {"external_id": "W1", "csrf": csrf, "tab": "to_associate"}


def test_checkbox_persists_through_refresh_and_stale_save_and_can_be_unchecked(anomaly_page):
    client, path, form = anomaly_page
    stale = json.loads(path.read_text())
    for _ in range(2):
        response = client.post("/admin/wedof/manual-anomaly", data={**form, "marked": "1"})
        assert response.status_code == 302
        assert "tab=to_associate" in response.location
    records = json.loads(path.read_text())["wedof_manual_anomalies"]
    assert len(records) == 1 and records[0]["active"] is True
    gestion_app.save_data(stale)
    assert json.loads(path.read_text())["wedof_manual_anomalies"] == records
    html = client.get("/admin/wedof?section=state&tab=anomaly").get_data(as_text=True)
    assert '<strong id="wedof-unlinked-count">1</strong>' in html
    assert 'data-wedof-panel="anomaly"' in html
    assert 'data-wedof-to-associate="false"' in html
    assert "anomalie signalée manuellement" in html
    assert "data-wedof-anomaly-toggle\n                               checked" in html
    response = client.post("/admin/wedof/manual-anomaly", data={**form, "tab": "anomaly"})
    assert response.status_code == 302 and "tab=anomaly" in response.location
    assert json.loads(path.read_text())["wedof_manual_anomalies"][0]["active"] is False
    html = client.get("/admin/wedof?section=state&tab=to_associate").get_data(as_text=True)
    assert '<strong id="wedof-unlinked-count">2</strong>' in html


def test_stale_linked_or_unknown_folder_is_rejected(anomaly_page):
    client, path, form = anomaly_page
    data = json.loads(path.read_text())
    data["wedof_links"] = [{"external_id": "W1", "active": True, "session_id": "S1", "trainee_id": "T1"}]
    path.write_text(json.dumps(data))
    for external_id in ("W1", "UNKNOWN"):
        client.post("/admin/wedof/manual-anomaly", data={**form, "external_id": external_id, "marked": "1"})
        assert not json.loads(path.read_text()).get("wedof_manual_anomalies")


def test_classification_can_be_removed_after_manual_association(anomaly_page):
    client, path, form = anomaly_page
    client.post("/admin/wedof/manual-anomaly", data={**form, "marked": "1"})
    data = json.loads(path.read_text())
    data["wedof_links"] = [{"external_id": "W1", "active": True, "session_id": "S1", "trainee_id": "T1"}]
    path.write_text(json.dumps(data))
    client.post("/admin/wedof/manual-anomaly", data=form)
    assert json.loads(path.read_text())["wedof_manual_anomalies"][0]["active"] is False
    html = client.get("/admin/wedof?section=state").get_data(as_text=True)
    assert '<strong id="wedof-unlinked-count">1</strong>' in html
    assert "anomalie signalée manuellement" not in html


def test_write_requires_admin_rights_and_valid_csrf(anomaly_page):
    client, path, form = anomaly_page
    original = path.read_text()
    assert client.post("/admin/wedof/manual-anomaly", data={**form, "csrf": "invalid", "marked": "1"}).status_code == 403
    assert client.post("/admin/wedof/manual-anomaly", data={**form, "marked": "invalid"}).status_code == 400
    with client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert client.post("/admin/wedof/manual-anomaly", data={**form, "marked": "1"}).status_code == 403
    anonymous = gestion_app.app.test_client()
    assert anonymous.post("/admin/wedof/manual-anomaly", data={**form, "marked": "1"}).status_code == 302
    assert path.read_text() == original
