from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, session

from admin_trainee_wedof_refresh import (
    _refresh_associated_cpf,
    register_admin_trainee_wedof_refresh,
)


class FakeWedofError(RuntimeError):
    code = "wedof_unavailable"


def _legacy_app(data, *, refresh_side_effect=None):
    flask_app = Flask(__name__)
    flask_app.secret_key = "test"
    save_data = Mock()

    def local_registration(current, session_id, trainee_id):
        session_obj = next(
            (item for item in current["sessions"] if item["id"] == session_id),
            None,
        )
        trainee = next(
            (item for item in (session_obj or {}).get("trainees", [])
             if item["id"] == trainee_id),
            None,
        )
        return session_obj, trainee

    def active_link(current, *, session_id, trainee_id):
        return next(
            (item for item in current["wedof_links"]
             if item.get("active") is True
             and item["session_id"] == session_id
             and item["trainee_id"] == trainee_id),
            None,
        )

    refresh = Mock(side_effect=refresh_side_effect)
    if refresh_side_effect is None:
        def update_snapshot(current, link):
            link["wedof_state"] = "serviceDoneValidated"
            link["cpf_snapshot"] = {
                "state": "serviceDoneValidated",
                "billing_state": "billed",
                "invoice_number": "FL-2026-374",
            }
            link.pop("cpf_sync_error", None)
        refresh.side_effect = update_snapshot

    return SimpleNamespace(
        app=flask_app,
        load_data=Mock(return_value=data),
        save_data=save_data,
        _cpf_local_registration=local_registration,
        _cpf_active_link=active_link,
        _refresh_cpf_link_from_wedof=refresh,
        WedofApiError=FakeWedofError,
        WedofConfigurationError=FakeWedofError,
    )


def _data():
    return {
        "sessions": [{
            "id": "S-CPF",
            "trainees": [{"id": "T-CPF", "cpf_amount": 4300}],
        }],
        "wedof_links": [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "391667980849",
            "wedof_state": "accepted",
            "cpf_snapshot": {"state": "accepted"},
        }],
    }


def test_refresh_updates_the_link_before_persisting_the_trainee_page_data():
    data = _data()
    legacy = _legacy_app(data)

    assert _refresh_associated_cpf(legacy, "S-CPF", "T-CPF") is True

    legacy._refresh_cpf_link_from_wedof.assert_called_once_with(
        data, data["wedof_links"][0],
    )
    legacy.save_data.assert_called_once_with(data)
    assert data["wedof_links"][0]["wedof_state"] == "serviceDoneValidated"
    assert data["wedof_links"][0]["cpf_snapshot"]["billing_state"] == "billed"


def test_wedof_failure_keeps_the_cached_snapshot_and_does_not_block_the_page():
    data = _data()
    legacy = _legacy_app(data, refresh_side_effect=FakeWedofError("offline"))

    assert _refresh_associated_cpf(legacy, "S-CPF", "T-CPF") is True

    legacy.save_data.assert_called_once_with(data)
    link = data["wedof_links"][0]
    assert link["cpf_snapshot"]["state"] == "accepted"
    assert link["cpf_sync_error"] == "Synchronisation momentanément indisponible"


def test_admin_view_wrapper_refreshes_only_for_an_authenticated_opening():
    data = _data()
    legacy = _legacy_app(data)
    app = legacy.app

    @app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>",
             endpoint="admin_trainee_page")
    def trainee_page(session_id, trainee_id):
        return data["wedof_links"][0]["wedof_state"]

    register_admin_trainee_wedof_refresh(legacy)

    client = app.test_client()
    anonymous = client.get("/admin/sessions/S-CPF/stagiaires/T-CPF")
    assert anonymous.get_data(as_text=True) == "accepted"
    legacy._refresh_cpf_link_from_wedof.assert_not_called()

    with client.session_transaction() as flask_session:
        flask_session["admin_logged_in"] = True
    authenticated = client.get("/admin/sessions/S-CPF/stagiaires/T-CPF")

    assert authenticated.status_code == 200
    assert authenticated.get_data(as_text=True) == "serviceDoneValidated"
    legacy._refresh_cpf_link_from_wedof.assert_called_once()


def test_render_entrypoint_registers_the_admin_trainee_refresh():
    source = open("crm_app.py", encoding="utf-8").read()
    assert "register_admin_trainee_wedof_refresh(legacy_app)" in source

