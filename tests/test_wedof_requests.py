import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

import app as application
from wedof_requests import entry_folder_id, grouped_requests, notification_kind


def folder(identifier="CPF-001", **values):
    return {
        "externalId": identifier, "type": "cpf", "state": "notProcessed",
        "attendee": {"firstName": "Marie", "lastName": "Exemple",
                     "email": "marie@example.test", "phoneNumber": "0600000000"},
        "trainingActionInfo": {"title": "Formation DESP",
                               "sessionStartDate": "2027-01-04", "sessionEndDate": "2027-02-18"},
        "_links": {"self": {"href": f"/api/registrationFolders/{identifier}"}},
        **values,
    }


def entry(identifier="ONE", payload=None, **values):
    return {"id": identifier, "payload": folder() if payload is None else payload,
            "event": "registrationFolder.updated", "received_at": "2026-09-16T10:00:00Z", **values}


DOCUMENT = {"id": 550000, "fileName": "justificatif.pdf", "fileType": "application/pdf",
            "_links": {"certificationFolder": {"href": "/api/certificationFolders/CERT-001"}}}
CERTIFICATION = {"externalId": "CERT-001", "attendee": folder()["attendee"], "state": "registered",
                 "_links": {"self": {"href": "/api/certificationFolders/CERT-001"},
                            "registrationFolder": {"href": "/api/registrationFolders/CPF-001"}}}


@pytest.fixture
def webhook_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WEDOF_WEBHOOK_SECRET", "test-only-secret")
    monkeypatch.setattr(application, "WEDOF_WEBHOOK_FILE", str(tmp_path / "webhooks.json"))
    state = []
    monkeypatch.setattr(application, "_load_wedof_webhooks", lambda: copy.deepcopy(state))

    def save(entries):
        state[:] = copy.deepcopy(entries)

    save_mock = Mock(side_effect=save)
    monkeypatch.setattr(application, "_save_wedof_webhooks", save_mock)
    fetch = Mock(return_value={})
    monkeypatch.setattr(application, "_fetch_wedof_folder_details", fetch)
    monkeypatch.setattr(application, "_atomic_update_data", Mock())
    monkeypatch.setattr(application, "_process_vtc_cpf_auto_workflow", lambda value, *_args, **_kwargs: value)

    def send(record):
        time.sleep(0.02)  # Allow concurrent arrivals to overlap during delivery.
        record.update(salesforce_sent=True, salesforce_sent_at="2026-09-16T10:01:00Z", salesforce_send_count=1)
        return {"success": True}, 200

    salesforce = Mock(side_effect=send)
    crm = Mock(return_value=({"success": True}, 200))
    monkeypatch.setattr(application, "_send_wedof_entry_to_salesforce", salesforce)
    monkeypatch.setattr(application, "_send_wedof_entry_to_crm", crm)
    return state, salesforce, crm, fetch, save_mock


def post(payload, delivery, event="registrationFolder.updated"):
    with application.app.test_client() as client:
        return client.post("/api/webhooks/wedof", json=payload, headers={
            "X-Wedof-Event": event, "X-Wedof-Delivery": delivery,
            "X-Wedof-Secret": "test-only-secret",
        })


@pytest.mark.parametrize("payload,event", [
    (DOCUMENT, "certificationFolderFile.created"), (DOCUMENT, ""),
    (CERTIFICATION, "certificationFolder.updated"), (CERTIFICATION, ""),
    ({"data": CERTIFICATION}, ""), ({"id": 123}, "attendee.updated"),
    ({"id": 123}, ""), ({}, "ping"), ({}, "registrationFolder.updated"),
])
def test_technical_events_never_create_requests_or_spend_quota(webhook_env, payload, event):
    state, salesforce, crm, fetch, save = webhook_env
    response = post(payload, "delivery-tech", event)
    assert response.status_code == 200
    assert response.json["ignored"] is True
    assert state == []
    for operation in (salesforce, crm, fetch, save):
        operation.assert_not_called()


def test_registration_with_certification_link_is_kept():
    payload = folder()
    payload["_links"]["certificationFolder"] = {"href": "/api/certificationFolders/CERT-001"}
    assert notification_kind(payload) == "registration"
    assert entry_folder_id(entry(payload=payload)) == "CPF-001"


def test_grouping_uses_folder_not_person_and_preserves_history():
    old = entry("OLD", processed=True, salesforce_sent=True,
                salesforce_sent_at="2026-09-16T10:00:01Z", salesforce_send_count=1)
    new = entry("NEW", received_at="2026-09-16T10:02:00Z", payload={"registrationFolderId": "CPF-001"})
    other = entry("OTHER", payload=folder("CPF-002"))
    records = [new, entry("DOC", DOCUMENT, event="certificationFolderFile.created"), other, old]
    original = copy.deepcopy(records)
    rows, ignored = grouped_requests(records)
    assert len(rows) == 2 and ignored == 1
    assert rows[0]["event_count"] == 2
    assert rows[0]["processed"] is True
    assert rows[0]["salesforce_sent"] is True
    fields = application._wedof_entry_display_fields(rows[0])
    assert fields["training_title"] == "Formation DESP"
    assert fields["email"] == "marie@example.test"
    assert records == original


def test_full_history_is_grouped_before_page_limit():
    records = [entry(f"UPDATE-{i}") for i in range(110)]
    records.append(entry("OLDER-DISTINCT", payload=folder("CPF-002")))
    rows, _ = grouped_requests(records)
    assert len(rows) == 2
    assert rows[0]["event_count"] == 110


def test_admin_page_counts_distinct_folders_and_preserves_separate_enrolments(monkeypatch):
    records = [entry("NEW"), entry("OLD"), entry("SECOND", payload=folder("CPF-002")),
               entry("DOCUMENT", DOCUMENT, event="certificationFolderFile.created")]
    monkeypatch.setattr(application, "_load_wedof_webhooks", lambda: records)
    monkeypatch.setattr(application, "load_data", lambda **_kwargs: {"sessions": []})
    with application.app.test_client() as client:
        with client.session_transaction() as session:
            session["admin_logged_in"] = True
        response = client.get("/admin/wedof?section=requests")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '2 nouvelles demandes' in html
    assert html.count('data-wedof-notify') == 3  # Two buttons and the JS selector.
    assert 'Dossier CPF-001' in html and 'Dossier CPF-002' in html
    assert '2 notifications regroupées' in html
    assert 'justificatif.pdf' not in html


def test_pagination_keeps_old_requests_accessible(monkeypatch):
    records = [entry(f"E-{i}", payload=folder(f"CPF-{i}")) for i in range(105)]
    monkeypatch.setattr(application, "_load_wedof_webhooks", lambda: records)
    with application.app.test_request_context('/admin/wedof?section=requests&request_page=2'):
        context = application._wedof_requests_context()
    assert len(context["wedof_webhooks"]) == 5
    assert context["wedof_requests_total"] == 105
    assert context["wedof_new_requests_count"] == 105
    assert context["wedof_request_page_count"] == 2


def test_updated_folder_keeps_one_salesforce_delivery_but_updates_crm(webhook_env):
    state, salesforce, crm, fetch, _ = webhook_env
    assert post(folder(), "delivery-1").status_code == 200
    assert post({"registrationFolderId": "CPF-001", "state": "validated"}, "delivery-2").status_code == 200
    salesforce.assert_called_once()
    assert crm.call_count == 2
    assert len(state) == 2
    assert state[0]["salesforce_duplicate_of"] == state[1]["id"]
    assert state[0]["wedof_folder_details"]["trainingActionInfo"]["title"] == "Formation DESP"
    assert state[0]["wedof_folder_details"]["state"] == "validated"
    fetch.assert_not_called()
    assert len(grouped_requests(state)[0]) == 1


def test_simultaneous_events_do_not_duplicate_salesforce_or_lose_history(webhook_env):
    state, salesforce, crm, _, _ = webhook_env
    barrier = threading.Barrier(2)

    def receive(i):
        barrier.wait(timeout=5)
        return post(folder(), f"delivery-{i}").status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(receive, range(2))) == [200, 200]
    assert len(state) == 2
    assert {item["delivery_id"] for item in state} == {"delivery-0", "delivery-1"}
    salesforce.assert_called_once()
    assert crm.call_count == 2


def test_manual_actions_apply_to_whole_group(webhook_env):
    state, *_ = webhook_env
    state.extend([entry("NEW"), entry("OLD")])
    with application.app.test_client() as client:
        with client.session_transaction() as session:
            session["admin_logged_in"] = True
        assert client.post("/admin/wedof/mark-treated/NEW").status_code == 302
        assert all(item["processed"] for item in state)
        assert client.post("/admin/wedof/delete/NEW").status_code == 302
    assert len(state) == 2  # Raw audit history is retained.
    assert grouped_requests(state)[0] == []


def test_salesforce_504_is_ambiguous_service_error(monkeypatch):
    response = Mock(status_code=504, text="Gateway Timeout", url="https://example.test")
    monkeypatch.setattr(application.requests, "post", Mock(return_value=response))
    record = entry()
    result, status = application._send_wedof_entry_to_salesforce(record)
    assert status == 502 and result["success"] is False
    assert "temporairement indisponible" in result["error"]
    assert "champs obligatoires" not in result["error"]
    assert record["salesforce_delivery_uncertain"] is True


def test_uncertain_salesforce_delivery_is_not_retried_on_next_update(webhook_env):
    state, salesforce, crm, _, _ = webhook_env
    state.append(entry("OLD", salesforce_delivery_uncertain=True,
                       salesforce_last_error="Réception non confirmée."))
    assert post(folder(state="validated"), "new-delivery").status_code == 200
    salesforce.assert_not_called()
    crm.assert_called_once()


@pytest.mark.parametrize("payload", [DOCUMENT, CERTIFICATION])
def test_manual_relays_reject_technical_resources(monkeypatch, payload):
    outgoing = Mock()
    monkeypatch.setattr(application.requests, "post", outgoing)
    record = entry(payload=payload, event="")
    assert application._send_wedof_entry_to_salesforce(record)[1] == 422
    assert application._send_wedof_entry_to_crm(record)[1] == 422
    outgoing.assert_not_called()


def test_crm_ignored_response_is_not_reported_as_delivered(monkeypatch):
    monkeypatch.setenv("CRM_WEDOF_WEBHOOK_SECRET", "test-relay-only")
    response = Mock(status_code=200, text='{"ok":true,"ignored":true}')
    response.json.return_value = {"ok": True, "ignored": True}
    monkeypatch.setattr(application.requests, "post", Mock(return_value=response))
    record = entry()
    result, status = application._send_wedof_entry_to_crm(record)
    assert status == 502 and result["success"] is False
    assert not record.get("crm_sent")
