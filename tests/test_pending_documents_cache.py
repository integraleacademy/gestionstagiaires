import copy
import json
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

import app as host


def document(key, status="A CONTRÔLER"):
    return {"key": key, "status": status}


def roster(name):
    return {"sessions": [{"id": "S", "name": "Formation", "training_type": "APS", "trainees": [
        {"id": "a", "last_name": name, "documents": [document("id"), document("photo", " A CONTROLER ")]},
        {"id": "b", "last_name": "Second", "documents": [document("id"), document("dom")]},
        {"id": "c", "documents": [document("photo"), document("photo", "VALIDÉ")]},
        {"id": "d", "registration_cancelled": True, "documents": [document("id")]},
    ]}, {"id": host.WEDOF_LEADS_SESSION_ID, "trainees": [{"id": "lead", "documents": [document("id")]}]}]}


def test_document_projection_preserves_legacy_rules_without_changing_trainees():
    data = roster("Premier")
    original = copy.deepcopy(data)
    items = host._docs_to_control_items(data)
    assert [(item["trainee_id"], item["pending_count"]) for item in items] == [("a", 2), ("b", 1)]
    assert items[0]["admin_url"] == "/admin/sessions/S/stagiaires/a"
    assert data == original


def test_shared_dashboard_cache_checks_auth_and_picks_up_new_files(monkeypatch, tmp_path):
    path = tmp_path / "data.json"
    data = roster("Premier")
    path.write_text(json.dumps(data))
    monkeypatch.setattr(host, "DATA_FILE", str(path))
    monkeypatch.setattr(host, "_docs_to_control_cache", OrderedDict())
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "off")
    monkeypatch.setattr(host, "DOCS_TO_CONTROL_PUBLIC_TOKEN", "test-dashboard")
    load = Mock(side_effect=lambda: json.loads(path.read_text()))
    monkeypatch.setattr(host, "load_data", load)
    client = host.app.test_client()
    url = "/docs_to_control.json"
    headers = {"X-Docs-To-Control-Token": "test-dashboard"}
    for _ in range(25):
        response = client.get(url, headers=headers)
        assert response.json["count"] == 2
        assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert client.get(url).status_code == 403
    assert client.open(url, method="OPTIONS", headers=headers).status_code == 204
    with client.session_transaction() as user:
        user.update(admin_logged_in=True, admin_role="admin")
    assert client.get("/api/docs_to_control").json == response.json
    load.assert_called_once_with()
    data["sessions"][0]["trainees"][0]["documents"][0]["status"] = "VALIDÉ"
    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps(data))
    replacement.replace(path)
    updated = client.get("/api/docs_to_control").json
    assert [item["pending_count"] for item in updated["items"]] == [1, 1]
    assert load.call_count == 2


def test_postgres_revisions_cover_platform_tenant_and_assistance(monkeypatch, tmp_path):
    path = tmp_path / "data.json"
    path.write_text("{}")
    monkeypatch.setattr(host, "DATA_FILE", str(path))
    monkeypatch.setattr(host, "_docs_to_control_cache", OrderedDict())
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "active")
    revisions = {"tenant-a": 1, "tenant-b": 1}
    def bundle_revisions(partner):
        return tuple((key, value) for key, value in revisions.items() if not partner or key == partner)
    store = SimpleNamespace(bundle_revisions=Mock(side_effect=bundle_revisions))
    monkeypatch.setattr(host, "_get_partner_postgres_store", lambda: store)

    def read():
        scope, partner, _ = host._request_data_cache_key(False)
        if scope == "global":
            host.g.partner_postgres_platform_baselines = {}
            return roster("plateforme-" + str(revisions["tenant-a"]))
        return roster(partner + "-" + str(revisions[partner]))

    load = Mock(side_effect=read)
    monkeypatch.setattr(host, "load_data", load)
    def listed_surname(partner="", *, assist=False):
        with host.app.test_request_context("/api/docs_to_control"):
            host.session.update(admin_logged_in=True, admin_role="viewer" if partner else "admin", partner_id=partner)
            if assist:
                host.session.update(partner_id=host.INTEGRALE_PARTNER_ID, admin_role="admin", assist_partner_id=partner)
            return host._pending_document_items()[0]["last_name"]

    assert listed_surname() == "plateforme-1"
    assert listed_surname("tenant-a") == "tenant-a-1"
    assert listed_surname("tenant-b") == "tenant-b-1"
    assert listed_surname("tenant-b", assist=True) == "tenant-b-1"
    revisions["tenant-a"] += 1
    assert listed_surname("tenant-a", assist=True) == "tenant-a-2"
    assert listed_surname() == "plateforme-2"
    assert listed_surname("tenant-b") == "tenant-b-1"
    assert load.call_count == 5
    store.bundle_revisions.side_effect = host.PartnerPostgresUnavailable("temporary outage")
    assert listed_surname("tenant-b") == "tenant-b-1"
    assert listed_surname("tenant-b") == "tenant-b-1"
    assert load.call_count == 7


def test_atomic_replacement_during_a_document_read_is_not_cached(monkeypatch, tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps(roster("Première")))
    monkeypatch.setattr(host, "DATA_FILE", str(path))
    monkeypatch.setattr(host, "_docs_to_control_cache", OrderedDict())
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "off")
    def replace_during_first_read():
        old = json.loads(path.read_text())
        replacement = tmp_path / "replacement.json"
        replacement.write_text(json.dumps(roster("Deuxième")))
        replacement.replace(path)
        return old
    with host.app.test_request_context("/api/docs_to_control"):
        monkeypatch.setattr(host, "load_data", replace_during_first_read)
        assert host._pending_document_items()[0]["last_name"] == "Première"
    with host.app.test_request_context("/api/docs_to_control"):
        monkeypatch.setattr(host, "load_data", lambda: json.loads(path.read_text()))
        assert host._pending_document_items()[0]["last_name"] == "Deuxième"
