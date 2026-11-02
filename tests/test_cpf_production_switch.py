from contextlib import closing
import os
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

from flask import Flask, jsonify
import pytest

import cpf_provider as providers
import cpf_provider_bridge as bridge
from cpf_transfer_history import receipt, receipts


@pytest.fixture
def pair(tmp_path, monkeypatch):
    prod_dir, test_dir = tmp_path / "prod", tmp_path / "test"
    prod_dir.mkdir()
    test_dir.mkdir()
    prod, pilot = providers.ProviderStore(prod_dir), providers.ProviderStore(test_dir)
    app = Flask(__name__)
    actual = []
    def task(name):
        def call():
            actual.append(name)
            return jsonify(ok=True, name=name)
        return call
    for name in ("internal_cron_wedof_automation", "internal_cron_wedof_reconciliation",
                 "internal_cron_qonto_sync", "internal_cron_document_reminders",
                 "internal_wedof_governor_reserve", "wedof_webhook"):
        app.add_url_rule("/" + name, name, task(name), methods=["POST"])
    legacy = SimpleNamespace(app=app, _send_wedof_entry_to_crm=Mock(), _send_wedof_entry_to_salesforce=Mock(),
                             _load_wedof_webhooks=lambda: [])
    monkeypatch.setenv("RENDER_SERVICE_ID", providers.PROD_SERVICE_ID)
    monkeypatch.setenv(bridge.SECRET_NAME, "x" * 45)
    monkeypatch.setattr(providers, "current_store", lambda: prod)
    monkeypatch.setattr(bridge, "current_store", lambda: prod)
    bridge.register_production_control(legacy)
    providers.register_wedof_guards(app)
    client = app.test_client()
    headers = {"X-Cpf-Control": "x" * 45}
    def remote(body=None):
        reply = client.open("/internal/cpf/provider", method="GET" if body is None else "POST", headers=headers, json=body)
        if reply.status_code != 200:
            raise providers.ProviderUnavailable("Production occupée")
        return reply.json
    return SimpleNamespace(prod=prod, pilot=pilot, remote=remote, client=client, headers=headers, actual=actual, legacy=legacy)


def test_pair_switch_and_resume_only_wedof(pair):
    assert pair.remote()["provider"] == "wedof"
    for target, revision in (("integrale", 0), ("wedof", 1)):
        result = bridge.coordinated_switch(pair.pilot, target, revision, "operator", pair.remote)
        assert result["provider"] == pair.remote()["provider"] == target
        assert result["revision"] == revision + 1 and not result["pending"]
        for name in ("internal_cron_wedof_automation", "internal_cron_wedof_reconciliation",
                     "wedof_webhook", "internal_wedof_governor_reserve"):
            response = pair.client.post("/" + name)
            assert (name in pair.actual) == (target == "wedof")
            if target == "integrale":
                assert response.status_code == (409 if "governor" in name else 200)
        for name in ("internal_cron_qonto_sync", "internal_cron_document_reminders"):
            assert pair.client.post("/" + name).json["name"] == name


@pytest.mark.parametrize("target", ["integrale", "wedof"])
def test_lost_reply_both_local_providers_paused_until_exact_retry(pair, target):
    if target == "wedof":
        bridge.coordinated_switch(pair.pilot, "integrale", 0, "operator", pair.remote)
    revision = pair.pilot.state()["revision"]
    def lost(body=None):
        result = pair.remote(body)
        if body:
            raise providers.ProviderUnavailable("lost reply")
        return result
    with pytest.raises(providers.ProviderUnavailable):
        bridge.coordinated_switch(pair.pilot, target, revision, "operator", lost)
    restart = providers.ProviderStore(pair.pilot.directory)
    assert pair.remote()["provider"] == target
    for name in providers.PROVIDERS:
        with pytest.raises(providers.ProviderUnavailable):
            restart.acquire(name)
    remote_rev = pair.remote()["revision"]
    assert bridge.coordinated_switch(restart, target, revision, "operator", pair.remote)["pending"] is None
    assert pair.remote()["revision"] == remote_rev


def test_concurrent_operations_on_either_service_and_stale_forms(pair):
    for busy in (pair.pilot, pair.prod):
        fd = busy.acquire("wedof")
        try:
            with pytest.raises(providers.ProviderUnavailable):
                bridge.coordinated_switch(pair.pilot, "integrale", 0, "operator", pair.remote)
            assert pair.remote()["provider"] == "wedof"
        finally:
            os.close(fd)
    bridge.coordinated_switch(pair.pilot, "integrale", 0, "operator", pair.remote)
    with pytest.raises(providers.ProviderUnavailable):
        bridge.coordinated_switch(pair.pilot, "wedof", 0, "operator", pair.remote)
    assert pair.remote()["provider"] == "integrale"


def test_global_receipts_cover_both_directions_without_transferring_contacts(pair):
    pair.legacy._load_wedof_webhooks = lambda: [{"folder_id": "100001", "crm_sent": True}]
    bridge.coordinated_switch(pair.pilot, "integrale", 0, "operator", pair.remote)
    response = pair.client.post("/internal/cpf/provider/receipt", headers=pair.headers,
                                json={"folder": "100001", "target": "crm"})
    assert response.json["receipt"] == "sent"
    with closing(pair.pilot.connect()) as db, db:
        receipts(db)
        db.executemany("INSERT INTO cpf_transfers VALUES (?,?,?,1)",
                       [("100002", "crm", "sent"), ("100003", "salesforce", "processing")])
    bridge.coordinated_switch(pair.pilot, "wedof", 1, "operator", pair.remote)
    assert receipt(pair.prod, "100002", "crm") == "sent"
    assert pair.legacy._send_wedof_entry_to_crm({"folder_id": "100002"})[0]["skipped"]
    assert pair.legacy._send_wedof_entry_to_salesforce({"folder_id": "100003"})[1] == 409


def test_secret_and_invalid_or_stale_requests_cannot_switch(pair):
    path = "/internal/cpf/provider"
    assert pair.client.get(path).status_code == 403
    request = {"target": "integrale", "actor": "operator", "operation": uuid.uuid4().hex, "revision": 0}
    assert pair.client.post(path, json=request).status_code == 403
    for invalid in ({"revision": True}, {"target": "other"}, {"operation": "invalid"}, {"receipts": [["x","crm","sent"]]}):
        assert pair.client.post(path, headers=pair.headers, json={**request, **invalid}).status_code == 400
    assert pair.client.post(path, headers=pair.headers, json={**request, "revision": 9}).status_code == 409
    assert pair.remote()["provider"] == "wedof"


def test_test_worker_refuses_divergent_or_unconfirmed_production(pair, monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", providers.TEST_SERVICE_ID)
    monkeypatch.setattr(providers, "current_store", lambda: pair.pilot)
    pair.pilot.switch("integrale", 0, "legacy-test-only")
    monkeypatch.setattr(bridge, "production_request", lambda: {"provider": "wedof"})
    with pytest.raises(providers.ProviderUnavailable):
        providers.acquire_provider("integrale")
    # The failed verification releases the local lock.
    os.close(pair.pilot.lock(exclusive=True))


def test_failed_status_read_cannot_start_a_transition_or_change_production(pair):
    def offline():
        raise providers.ProviderUnavailable("indisponible")
    with pytest.raises(providers.ProviderUnavailable):
        bridge.coordinated_switch(pair.pilot, "integrale", 0, "operator", offline)
    assert not pair.pilot.state()["pending"]
    assert pair.remote()["provider"] == "wedof"


@pytest.mark.parametrize("reply", [
    {"scope": "another", "protocol": 1, "provider": "wedof", "revision": 0},
    {"scope": bridge.SCOPE, "protocol": 1, "provider": "wedof", "revision": True},
])
def test_unverified_production_reply_blocks_native_operations(monkeypatch, reply):
    monkeypatch.setenv(bridge.SECRET_NAME, "x" * 45)
    send = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: reply))
    monkeypatch.setattr(bridge.requests, "request", send)
    with pytest.raises(providers.ProviderUnavailable):
        bridge.production_request()
    assert send.call_args.kwargs["allow_redirects"] is False
