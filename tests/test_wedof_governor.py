import datetime as dt
import os
import tempfile
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import app as gestion_app
from wedof_governor import (
    WedofQuotaExceeded,
    acquire_lease,
    governor_auth_token,
    quota_snapshot,
    release_lease,
    reserve_request,
    valid_governor_token,
)


PARIS = ZoneInfo("Europe/Paris")


def governor_env(path, **overrides):
    values = {
        "WEDOF_GOVERNOR_ENABLED": "true",
        "WEDOF_GOVERNOR_DB_PATH": path,
        "WEDOF_GOVERNOR_SECRET": "shared-governor-secret",
        "WEDOF_REQUEST_LIMIT_PER_HOUR": "2",
        "WEDOF_REQUEST_LIMIT_PER_DAY": "2",
        "WEDOF_REQUEST_LIMIT_PER_MONTH": "2",
    }
    values.update(overrides)
    return patch.dict(os.environ, values, clear=False)


def test_counter_is_shared_by_origin_and_blocks_before_overrun():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "governor.sqlite3")
        now = dt.datetime(2026, 8, 24, 12, 0, tzinfo=PARIS)
        with governor_env(path):
            reserve_request(
                origin="crm", operation="targeted_get", method="GET",
                path="/registrationFolders/:id", now=now,
            )
            reserve_request(
                origin="gestionstagiaires", operation="due_get", method="GET",
                path="/registrationFolders/:id", now=now,
            )
            with pytest.raises(WedofQuotaExceeded):
                reserve_request(
                    origin="crm", operation="targeted_get", method="GET",
                    path="/registrationFolders/:id", now=now,
                )
            snapshot = quota_snapshot(now=now)

        assert snapshot["periods"]["day"]["used"] == 2
        assert snapshot["periods"]["day"]["remaining"] == 0
        assert snapshot["periods"]["day"]["utilization_percent"] == 100.0
        assert snapshot["periods"]["day"]["status"] == "blocked"
        assert snapshot["periods"]["day"]["by_origin"] == {
            "crm": 1,
            "gestionstagiaires": 1,
        }
        assert [event["origin"] for event in snapshot["recent_events"]] == [
            "gestionstagiaires", "crm",
        ]
        assert snapshot["recent_events"][0] == {
            "requested_at": "2026-08-24T12:00:00+02:00",
            "origin": "gestionstagiaires",
            "operation": "due_get",
            "method": "GET",
            "path": "/registrationFolders/:id",
        }


def test_lease_is_cross_process_safe_and_releasable():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "governor.sqlite3")
        with governor_env(path):
            first = acquire_lease("wedof-global-reconciliation", owner="crm")
            second = acquire_lease(
                "wedof-global-reconciliation", owner="gestionstagiaires",
            )
            snapshot = quota_snapshot()
            assert first["acquired"] is True
            assert second["acquired"] is False
            assert snapshot["active_leases"] == [{
                "name": "wedof-global-reconciliation",
                "owner": "crm",
                "expires_at": first["expires_at"],
            }]
            assert release_lease(
                "wedof-global-reconciliation", first["token"],
            ) is True
            third = acquire_lease(
                "wedof-global-reconciliation", owner="gestionstagiaires",
            )
            assert third["acquired"] is True


def test_governor_http_contract_requires_shared_token_and_enforces_limit():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "governor.sqlite3")
        with governor_env(
            path,
            WEDOF_REQUEST_LIMIT_PER_HOUR="1",
            WEDOF_REQUEST_LIMIT_PER_DAY="1",
            WEDOF_REQUEST_LIMIT_PER_MONTH="1",
        ):
            token = governor_auth_token()
            assert valid_governor_token(token)
            client = gestion_app.app.test_client()
            assert client.post(
                "/internal/wedof/governor/reserve", json={"origin": "crm"},
            ).status_code == 403
            headers = {"X-Wedof-Governor-Token": token}
            first = client.post(
                "/internal/wedof/governor/reserve",
                headers=headers,
                json={
                    "origin": "crm",
                    "operation": "targeted_get",
                    "method": "GET",
                    "path": "/registrationFolders/:id",
                },
            )
            second = client.post(
                "/internal/wedof/governor/reserve",
                headers=headers,
                json={"origin": "gestionstagiaires"},
            )
            status = client.get(
                "/internal/wedof/governor/status", headers=headers,
            )

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.get_json()["error"] == "quota_exceeded"
        assert status.status_code == 200
        assert status.get_json()["periods"]["day"]["by_origin"] == {"crm": 1}


def test_governor_http_lock_returns_busy_without_technical_error():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "governor.sqlite3")
        with governor_env(path):
            client = gestion_app.app.test_client()
            headers = {"X-Wedof-Governor-Token": governor_auth_token()}
            first = client.post(
                "/internal/wedof/governor/locks/acquire", headers=headers,
                json={"name": "wedof-global-reconciliation", "owner": "crm"},
            )
            second = client.post(
                "/internal/wedof/governor/locks/acquire", headers=headers,
                json={"name": "wedof-global-reconciliation", "owner": "gestion"},
            )
            released = client.post(
                "/internal/wedof/governor/locks/release", headers=headers,
                json={
                    "name": "wedof-global-reconciliation",
                    "token": first.get_json()["token"],
                },
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.get_json()["acquired"] is False
        assert released.get_json() == {"ok": True, "released": True}


def test_governor_accepts_the_crm_six_hour_schedule_lock():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "governor.sqlite3")
        with governor_env(path):
            client = gestion_app.app.test_client()
            headers = {"X-Wedof-Governor-Token": governor_auth_token()}
            response = client.post(
                "/internal/wedof/governor/locks/acquire",
                headers=headers,
                json={
                    "name": "wedof-crm-reconciliation-schedule",
                    "owner": "crm-worker",
                    "ttl_seconds": 21600,
                },
            )

        assert response.status_code == 200
        assert response.get_json()["acquired"] is True
        expires_at = dt.datetime.fromisoformat(response.get_json()["expires_at"])
        assert expires_at > dt.datetime.now(PARIS) + dt.timedelta(hours=5)
