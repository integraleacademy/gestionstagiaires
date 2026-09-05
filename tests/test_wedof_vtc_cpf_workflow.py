from unittest.mock import Mock, patch

import app as application
from wedof_service import WedofApiError


def _folder(*, state="notProcessed", action_id=None, folder_type="cpf"):
    return {
        "externalId": "RF-VTC-001",
        "type": folder_type,
        "state": state,
        "attendee": {
            "firstName": "Nora",
            "lastName": "Martin",
            "email": "nora@example.test",
            "phoneNumber": "0612345678",
        },
        "trainingActionInfo": {
            "title": "Préparation à l'examen Chauffeur VTC",
            "trainingId": application.VTC_CPF_TRAINING_ID,
            "externalId": action_id or application.VTC_CPF_TRAINING_ACTION_ID,
        },
    }


def test_target_not_processed_folder_is_validated_and_notified_once():
    incoming = _folder()
    validated = {**incoming, "state": "validated"}
    entry = {"id": "EVENT-1", "wedof_folder_details": incoming}
    entries = [entry]
    client = Mock()
    client.validate_registration_folder.return_value = validated

    with patch.object(application, "WedofClient", return_value=client) as client_class, \
            patch.object(application, "brevo_send_email", return_value={"ok": True}) as send_email, \
            patch.object(application, "brevo_send_sms", return_value=True) as send_sms, \
            patch.object(application, "_save_wedof_webhooks") as save:
        result = application._process_vtc_cpf_auto_workflow(
            incoming, entries, entry,
        )

    assert result["state"] == "validated"
    client_class.assert_called_once_with(origin="gestionstagiaires-vtc-cpf")
    client.validate_registration_folder.assert_called_once_with("RF-VTC-001")
    assert send_email.call_count == 1
    assert send_email.call_args.args[0] == "nora@example.test"
    assert "Mon Compte Formation" in send_email.call_args.args[2]
    assert "acceptez l'inscription" in send_email.call_args.args[2]
    send_sms.assert_called_once()
    assert send_sms.call_args.args[0] == "0612345678"
    assert "acceptez l'inscription" in send_sms.call_args.args[1]
    workflow = entry["vtc_cpf_workflow"]
    assert workflow["validation"]["status"] == "succeeded"
    assert workflow["notifications"]["email"]["status"] == "sent"
    assert workflow["notifications"]["sms"]["status"] == "sent"
    assert save.call_count >= 3


def test_later_validated_event_does_not_duplicate_email_or_sms():
    incoming = _folder()
    first_entry = {"id": "EVENT-1", "wedof_folder_details": incoming}
    entries = [first_entry]
    client = Mock()
    client.validate_registration_folder.return_value = {
        **incoming, "state": "validated",
    }

    with patch.object(application, "WedofClient", return_value=client), \
            patch.object(application, "brevo_send_email", return_value={"ok": True}) as send_email, \
            patch.object(application, "brevo_send_sms", return_value=True) as send_sms, \
            patch.object(application, "_save_wedof_webhooks"):
        application._process_vtc_cpf_auto_workflow(
            incoming, entries, first_entry,
        )
        second_entry = {
            "id": "EVENT-2",
            "wedof_folder_details": _folder(state="validated"),
        }
        entries.insert(0, second_entry)
        application._process_vtc_cpf_auto_workflow(
            second_entry["wedof_folder_details"], entries, second_entry,
        )

    client.validate_registration_folder.assert_called_once_with("RF-VTC-001")
    send_email.assert_called_once()
    send_sms.assert_called_once()
    assert second_entry["vtc_cpf_workflow"]["notifications"]["email"]["status"] == "already_sent"
    assert second_entry["vtc_cpf_workflow"]["notifications"]["sms"]["status"] == "already_sent"


def test_only_the_exact_cpf_vtc_action_is_eligible():
    wrong_action = _folder(action_id="84089988400026_another-action")
    wrong_type = _folder(folder_type="individual")

    with patch.object(application, "WedofClient") as client_class, \
            patch.object(application, "brevo_send_email") as send_email, \
            patch.object(application, "brevo_send_sms") as send_sms, \
            patch.object(application, "_save_wedof_webhooks") as save:
        for index, candidate in enumerate((wrong_action, wrong_type), start=1):
            entry = {"id": f"EVENT-{index}"}
            assert application._process_vtc_cpf_auto_workflow(
                candidate, [entry], entry,
            ) == candidate
            assert "vtc_cpf_workflow" not in entry

    client_class.assert_not_called()
    send_email.assert_not_called()
    send_sms.assert_not_called()
    save.assert_not_called()


def test_validation_failure_never_sends_candidate_notifications():
    incoming = _folder()
    entry = {"id": "EVENT-1", "wedof_folder_details": incoming}
    client = Mock()
    client.validate_registration_folder.side_effect = WedofApiError(
        "timeout", "wedof_timeout", True, ambiguous=True,
    )

    with patch.object(application, "WedofClient", return_value=client), \
            patch.object(application, "brevo_send_email") as send_email, \
            patch.object(application, "brevo_send_sms") as send_sms, \
            patch.object(application, "_save_wedof_webhooks") as save:
        result = application._process_vtc_cpf_auto_workflow(
            incoming, [entry], entry,
        )

    assert result["state"] == "notProcessed"
    assert entry["vtc_cpf_workflow"]["validation"]["status"] == "ambiguous"
    send_email.assert_not_called()
    send_sms.assert_not_called()
    save.assert_called_once()


def test_emergency_kill_switch_blocks_the_wedof_mutation_and_notifications():
    incoming = _folder()
    entry = {"id": "EVENT-1", "wedof_folder_details": incoming}

    with patch.dict(application.os.environ, {"WEDOF_AUTOMATION_KILL_SWITCH": "true"}, clear=False), \
            patch.object(application, "WedofClient") as client_class, \
            patch.object(application, "brevo_send_email") as send_email, \
            patch.object(application, "brevo_send_sms") as send_sms, \
            patch.object(application, "_save_wedof_webhooks") as save:
        result = application._process_vtc_cpf_auto_workflow(
            incoming, [entry], entry,
        )

    assert result["state"] == "notProcessed"
    assert entry["vtc_cpf_workflow"]["validation"]["status"] == "blocked_kill_switch"
    client_class.assert_not_called()
    send_email.assert_not_called()
    send_sms.assert_not_called()
    save.assert_called_once()


def test_nested_folder_external_id_wins_over_webhook_event_id():
    payload = {
        "id": "WEBHOOK-EVENT-ID",
        "data": _folder(),
    }

    assert application._find_wedof_folder_id(payload) == "RF-VTC-001"


def test_webhook_runs_workflow_only_when_authentication_is_valid():
    client = application.app.test_client()
    incoming = _folder()

    with patch.dict(application.os.environ, {"WEDOF_WEBHOOK_SECRET": "shared-secret"}, clear=False), \
            patch.object(application, "_load_wedof_webhooks", return_value=[]), \
            patch.object(application, "_save_wedof_webhooks"), \
            patch.object(application, "_process_vtc_cpf_auto_workflow", return_value=incoming) as workflow, \
            patch.object(application, "_send_wedof_entry_to_salesforce", return_value=({"success": True}, 200)), \
            patch.object(application, "_send_wedof_entry_to_crm", return_value=({"success": True}, 200)), \
            patch.object(application, "_atomic_update_data"):
        trusted = client.post(
            "/api/webhooks/wedof",
            json=incoming,
            headers={
                "X-Wedof-Delivery": "trusted-delivery",
                "X-Wedof-Secret": "shared-secret",
            },
        )
        assert trusted.status_code == 200
        assert workflow.call_count == 1

        workflow.reset_mock()
        untrusted = client.post(
            "/api/webhooks/wedof",
            json=incoming,
            headers={
                "X-Wedof-Delivery": "untrusted-delivery",
                "X-Wedof-Secret": "wrong-secret",
            },
        )

    assert untrusted.status_code == 200
    workflow.assert_not_called()
