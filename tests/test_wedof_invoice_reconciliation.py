import datetime as dt
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request

import wedof_invoice_reconciliation as reconciliation


class FakeWedofError(RuntimeError):
    code = "wedof_unavailable"


def _has_invoice(snapshot, trainee, session_obj, data):
    return bool(
        snapshot.get("invoice_number")
        or snapshot.get("qonto_invoice_number")
        or str(snapshot.get("billing_state") or "").casefold() in {
            "billed", "generated", "sent", "paid",
        }
    )


def _base_data():
    return {
        "sessions": [{
            "id": "S1",
            "trainees": [
                {"id": "T1", "cpf_amount": 4300},
                {"id": "T2", "cpf_amount": 4300},
                {"id": "T3", "cpf_amount": 4300},
            ],
        }],
        "wedof_links": [
            {
                "active": True,
                "external_id": "W1",
                "session_id": "S1",
                "trainee_id": "T1",
                "wedof_state": "serviceDoneDeclared",
                "cpf_snapshot": {"state": "serviceDoneDeclared"},
            },
            {
                "active": True,
                "external_id": "W2",
                "session_id": "S1",
                "trainee_id": "T2",
                "wedof_state": "accepted",
                "cpf_snapshot": {"state": "accepted"},
            },
            {
                "active": True,
                "external_id": "W3",
                "session_id": "S1",
                "trainee_id": "T3",
                "wedof_state": "serviceDoneValidated",
                "cpf_snapshot": {
                    "state": "serviceDoneValidated",
                    "billing_state": "billed",
                    "invoice_number": "FL-2026-001",
                },
            },
        ],
        "wedof_automation_status": [],
        "wedof_folder_cache": [],
    }


def _legacy(data, client):
    app = Flask(__name__)
    app.secret_key = "test"

    def local_registration(current, session_id, trainee_id):
        session_obj = next(
            (item for item in current.get("sessions", []) if item.get("id") == session_id),
            None,
        )
        trainee = next(
            (item for item in (session_obj or {}).get("trainees", [])
             if item.get("id") == trainee_id),
            None,
        )
        return session_obj, trainee

    def public_snapshot(remote):
        return {key: value for key, value in remote.items() if value not in (None, "")}

    def upsert_cache(current, folder):
        remote = dict(folder)
        cache = current.setdefault("wedof_folder_cache", [])
        existing = next(
            (item for item in cache if item.get("external_id") == remote.get("external_id")),
            None,
        )
        if existing:
            existing.clear()
            existing.update(remote)
        else:
            cache.append(remote)

    def sync_status(current, folder, now=None):
        rows = current.setdefault("wedof_automation_status", [])
        existing = next(
            (item for item in rows if item.get("external_id") == folder.get("external_id")),
            None,
        )
        value = {
            "external_id": folder.get("external_id"),
            "wedof_state": folder.get("state"),
        }
        if existing:
            existing.update(value)
        else:
            rows.append(value)

    def atomic_update(mutator):
        return mutator(data)

    return SimpleNamespace(
        app=app,
        WedofClient=Mock(return_value=client),
        WedofApiError=FakeWedofError,
        WedofConfigurationError=FakeWedofError,
        _atomic_update_data=atomic_update,
        _cpf_local_registration=local_registration,
        _cpf_public_snapshot=public_snapshot,
        _upsert_wedof_folder_cache=upsert_cache,
        extract_folder=lambda folder: dict(folder),
        has_generated_cpf_invoice=_has_invoice,
        is_wedof_maintenance_window=lambda now=None: {"active": False},
        read_env_bool=lambda name, default=False: True,
        sync_folder_automation_status=sync_status,
    )


def test_hourly_run_promotes_only_service_done_non_invoiced_links(monkeypatch):
    data = _base_data()
    client = Mock()
    client.get_registration_folder_interactive.return_value = {
        "external_id": "W1",
        "type": "cpf",
        "state": "serviceDoneValidated",
        "billing_state": "billed",
        "invoice_number": "FL-2026-374",
    }
    legacy = _legacy(data, client)
    monkeypatch.setenv("WEDOF_INVOICE_RECONCILIATION_INTERVAL_MINUTES", "60")
    monkeypatch.setenv("WEDOF_INVOICE_RECONCILIATION_MAX_CANDIDATES", "10")
    now = dt.datetime(2026, 9, 5, 13, 0, tzinfo=dt.timezone.utc)

    result = reconciliation.run_hourly_wedof_invoice_reconciliation(
        legacy, now=now,
    )

    assert result["status"] == "success"
    assert result["candidate_count"] == 1
    assert result["checked"] == 1
    assert result["newly_invoiced"] == 1
    client.get_registration_folder_interactive.assert_called_once_with(
        "W1", operation="cpf_invoice_hourly_reconciliation",
    )
    updated = data["wedof_links"][0]
    assert updated["cpf_snapshot"]["billing_state"] == "billed"
    assert updated["cpf_snapshot"]["invoice_number"] == "FL-2026-374"
    assert data["wedof_links"][1]["cpf_snapshot"]["state"] == "accepted"


def test_hourly_gate_prevents_rechecking_before_sixty_minutes(monkeypatch):
    data = _base_data()
    client = Mock()
    client.get_registration_folder_interactive.return_value = {
        "external_id": "W1", "type": "cpf", "state": "serviceDoneDeclared",
    }
    legacy = _legacy(data, client)
    monkeypatch.setenv("WEDOF_INVOICE_RECONCILIATION_INTERVAL_MINUTES", "60")
    first = dt.datetime(2026, 9, 5, 13, 0, tzinfo=dt.timezone.utc)

    reconciliation.run_hourly_wedof_invoice_reconciliation(legacy, now=first)
    second = reconciliation.run_hourly_wedof_invoice_reconciliation(
        legacy, now=first + dt.timedelta(minutes=59),
    )

    assert second["status"] == "not_due"
    assert client.get_registration_folder_interactive.call_count == 1


def test_capped_batch_rotates_unchecked_links_first(monkeypatch):
    data = _base_data()
    data["wedof_links"][1].update({
        "wedof_state": "serviceDoneDeclared",
        "cpf_snapshot": {"state": "serviceDoneDeclared"},
    })
    data["wedof_links"][0]["cpf_invoice_last_checked_at"] = "2026-09-05T10:00:00+00:00"
    client = Mock()
    legacy = _legacy(data, client)

    selected = reconciliation._service_done_candidates(legacy, data, limit=1)

    assert selected["total"] == 2
    assert [item["external_id"] for item in selected["selected"]] == ["W2"]


def test_global_wedof_error_keeps_cache_and_stops_the_batch(monkeypatch):
    data = _base_data()
    data["wedof_links"][1].update({
        "wedof_state": "serviceDoneDeclared",
        "cpf_snapshot": {"state": "serviceDoneDeclared"},
    })
    client = Mock()
    error = FakeWedofError("quota")
    error.code = "wedof_quota_exceeded"
    client.get_registration_folder_interactive.side_effect = error
    legacy = _legacy(data, client)
    now = dt.datetime(2026, 9, 5, 13, 0, tzinfo=dt.timezone.utc)

    result = reconciliation.run_hourly_wedof_invoice_reconciliation(
        legacy, now=now,
    )

    assert result["status"] == "failed"
    assert result["errors"] == 1
    assert result["stopped_early"] is True
    assert client.get_registration_folder_interactive.call_count == 1
    assert data["wedof_links"][0]["cpf_snapshot"] == {
        "state": "serviceDoneDeclared",
    }
    assert data["wedof_links"][0]["cpf_invoice_reconciliation_error"] == "wedof_quota_exceeded"


def test_cron_wrapper_runs_only_after_the_secret_is_accepted(monkeypatch):
    data = _base_data()
    legacy = _legacy(data, Mock())
    app = legacy.app

    @app.post("/internal/cron/wedof-automation", endpoint="internal_cron_wedof_automation")
    def cron():
        if request.headers.get("X-Cron-Secret") != "secret":
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return jsonify({"ok": True, "status": "success"})

    run = Mock(return_value={"ok": True, "status": "success", "checked": 1})
    monkeypatch.setattr(reconciliation, "run_hourly_wedof_invoice_reconciliation", run)
    reconciliation.register_wedof_invoice_reconciliation(legacy)
    client = app.test_client()

    assert client.post("/internal/cron/wedof-automation").status_code == 403
    run.assert_not_called()
    response = client.post(
        "/internal/cron/wedof-automation",
        headers={"X-Cron-Secret": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json()["invoice_reconciliation"]["checked"] == 1
    run.assert_called_once_with(legacy)


def test_render_entrypoint_registers_hourly_invoice_reconciliation():
    source = open("crm_app.py", encoding="utf-8").read()
    assert "register_wedof_invoice_reconciliation(legacy_app)" in source
