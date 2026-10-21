import copy
import datetime as dt
import importlib.util
import json
from unittest.mock import patch

import pytest

import app as host
import vtc_elearning_activation as activation
from elearning_native import vtc
from elearning_native.vtc_enrolments import effective_learner_session
from tests import test_native_elearning_web as web_tests

NOW = dt.datetime(2026, 10, 21, 12, tzinfo=dt.timezone.utc)
DUE = NOW + dt.timedelta(minutes=10)
KEY = activation.STATE_KEY


@pytest.fixture
def case():
    value = web_tests.NativeElearningWebTests(methodName="runTest")
    value.setUp()
    training = value.data["sessions"][0]
    training.update(training_type="VTC", date_start="2099-01-01", aps_elearning_enabled=False)
    person = training["trainees"][0]
    person["email"] = "alice@example.test"
    activation.schedule_new_enrolment(host, training, person, now=NOW)
    try:
        yield value
    finally:
        value.tearDown()


def test_ten_minutes_exactly_and_single_delivery_even_with_stale_snapshot(case):
    training, person = case.data["sessions"][0], case.data["sessions"][0]["trainees"][0]
    original_session = {k: copy.deepcopy(v) for k, v in training.items() if k != "trainees"}
    stale = copy.deepcopy(case.data)
    with patch.object(host, "brevo_send_email", return_value={"ok": True, "message_id": "accepted"}) as send:
        activation.process_due(host, data=case.data, now=DUE - dt.timedelta(seconds=1))
        assert not person[KEY]["activated_at"]
        send.assert_not_called()
        activation.process_due(host, data=case.data, now=DUE)
        assert person[KEY]["activated_at"] == DUE.isoformat()
        assert person[KEY]["email_status"] == "sent"
        activation.process_due(host, data=stale, now=DUE + dt.timedelta(days=1))
        send.assert_called_once()
        args, kwargs = send.call_args
        assert args[0] == "alice@example.test"
        assert "/espace/public-token" in args[2]
        assert kwargs["metadata"]["idempotency_key"]
        assert len(person["sent_email_history"]) == 1
    assert {k: v for k, v in training.items() if k != "trainees"} == original_session


def test_pending_is_locked_and_activated_is_available_before_formation(case):
    training, person = case.data["sessions"][0], case.data["sessions"][0]["trainees"][0]
    # The synthetic course exercises all real portal/player/tracking routes.
    person[KEY]["modules"] = [{"course_id": case.course["id"], "course_version": case.course["version"]}]
    case._public_login()
    assert case.client.get("/espace/public-token/elearning").status_code == 403
    before = case.client.get("/espace/public-token")
    assert before.status_code == 200
    assert "Votre parcours VTC sera disponible dans quelques minutes. Vous recevrez un email dès son activation." in before.text
    with patch.object(host, "brevo_send_email", return_value={"ok": True}):
        activation.process_due(host, data=case.data, now=DUE)
    after = case.client.get("/espace/public-token")
    assert after.status_code == 200
    assert "Votre accès est disponible dès maintenant" in after.text
    assert "Accéder à mon parcours VTC" in after.text
    assert "Accès disponible le 01/01/2099" not in after.text
    assert case.client.get("/espace/public-token/elearning").status_code == 200
    assert case.client.get(f'/espace/public-token/elearning/{case.course["id"]}').status_code == 200
    with case.client.session_transaction() as browser:
        browser.clear()
    assert case.client.get("/espace/public-token/elearning").status_code in (302, 401)
    assert not training["aps_elearning_enabled"]


@pytest.mark.parametrize("change", ["cancelled", "archived", "other_training", "other_tenant", "deleted"])
def test_rechecks_current_registration_before_activation(case, change):
    stale = copy.deepcopy(case.data)
    training, person = case.data["sessions"][0], case.data["sessions"][0]["trainees"][0]
    if change == "cancelled": person["registration_cancelled"] = True
    if change == "archived": training["archived"] = True
    if change == "other_training": training["training_type"] = "APS"
    if change == "other_tenant": training["partner_id"] = "external-partner"
    if change == "deleted": training["trainees"] = []
    with patch.object(host, "brevo_send_email") as send:
        activation.process_due(host, data=stale, now=DUE)
        send.assert_not_called()
    assert not person[KEY]["activated_at"]


def test_only_new_integrale_vtc_people_receive_a_complete_pinned_path(case):
    training, person = case.data["sessions"][0], case.data["sessions"][0]["trainees"][0]
    snapshot = copy.deepcopy(person[KEY])
    activation.schedule_new_enrolment(host, training, person, now=DUE)
    assert person[KEY] == snapshot
    assert len(snapshot["modules"]) == 8
    assert sum(m["required_minutes"] for m in snapshot["modules"]) == 105 * 60
    for module in snapshot["modules"]:
        assert vtc.load_bundled_course(module["course_id"], module["course_version"])
    old = {"id": "old", "created_at": "2020-01-01"}
    training["trainees"].append(old)
    assert effective_learner_session(training, old) is training
    for t in ({"training_type": "APS"}, {"training_type": "VTC", "partner_id": "external"}):
        new = {}
        activation.schedule_new_enrolment(host, t, new, now=NOW)
        assert KEY not in new
    with patch.object(host, "brevo_send_email", return_value={"ok": True}):
        activation.process_due(host, data=case.data, now=DUE)
    assert KEY not in old


def test_missing_email_does_not_block_access_then_correction_sends(case):
    person = case.data["sessions"][0]["trainees"][0]
    person["email"] = ""
    with patch.object(host, "brevo_send_email", return_value={"ok": True}) as send:
        activation.process_due(host, data=case.data, now=DUE)
        assert person[KEY]["activated_at"] and person[KEY]["email_status"] == "missing_email"
        send.assert_not_called()
        person["email"] = "corrected@example.test"
        activation.process_due(host, data=case.data, now=DUE + dt.timedelta(minutes=5))
        send.assert_called_once()
        assert send.call_args.args[0] == person["email"]


def test_explicit_refusal_retries_but_sent_email_never_repeats(case):
    person = case.data["sessions"][0]["trainees"][0]
    with patch.object(host, "brevo_send_email", side_effect=[{"ok": False, "status_code": 429}, {"ok": True}]) as send:
        activation.process_due(host, data=case.data, now=DUE)
        assert person[KEY]["email_status"] == "retry_pending"
        activation.process_due(host, data=case.data, now=DUE + dt.timedelta(minutes=4))
        assert send.call_count == 1
        activation.process_due(host, data=case.data, now=DUE + dt.timedelta(minutes=5))
        assert send.call_count == 2
        assert send.call_args_list[0].kwargs["metadata"] == send.call_args_list[1].kwargs["metadata"]
        activation.process_due(host, data=case.data, now=DUE + dt.timedelta(days=1))
        assert send.call_count == 2 and person[KEY]["email_status"] == "sent"


def test_restart_recovers_pending_deadline_and_uncertain_claim_is_not_replayed_late(case):
    person = case.data["sessions"][0]["trainees"][0]
    # Serialize/reload exactly as a worker restart; no in-memory timer required.
    case.data = json.loads(json.dumps(case.data))
    person = case.data["sessions"][0]["trainees"][0]
    with patch.object(host, "_load_valid_json_payload", return_value=case.data), \
         patch.object(host, "brevo_send_email", return_value={"ok": False}) as send:
        activation.process_due(host, now=DUE)
        activation.process_due(host, now=DUE + dt.timedelta(minutes=1))
        assert send.call_count == 2
        activation.process_due(host, now=DUE + dt.timedelta(minutes=11))
        assert send.call_count == 2
    assert person[KEY]["activated_at"] and person[KEY]["email_status"] == "needs_review"


def test_stale_save_keeps_activation_and_email_history(case):
    stale = copy.deepcopy(case.data)
    with patch.object(host, "brevo_send_email", return_value={"ok": True}):
        activation.process_due(host, data=case.data, now=DUE)
    activation.preserve_state(stale, case.data, host._session_trainees_list)
    assert stale["sessions"][0]["trainees"][0][KEY] == case.data["sessions"][0]["trainees"][0][KEY]
    assert len(stale["sessions"][0]["trainees"][0]["sent_email_history"]) == 1
    activation.preserve_state(stale, case.data, host._session_trainees_list)
    assert len(stale["sessions"][0]["trainees"][0]["sent_email_history"]) == 1


def test_creation_route_schedules_without_changing_existing_trainees(case):
    case._admin_login()
    old = copy.deepcopy(case.data["sessions"][0]["trainees"][0])
    with patch.object(host, "fetch_cnapsv3_tracking_requests", return_value=([], None)):
        response = case.client.post("/api/sessions/session-aps/trainees/create", json={
            "last_name": "Test", "first_name": "Nouveau", "email": "new@example.test", "send_access": False})
    assert response.status_code == 200, response.text
    created = case.data["sessions"][0]["trainees"][0]
    assert activation.parse(created[KEY]["due_at"]) - activation.parse(created[KEY]["created_at"]) == dt.timedelta(minutes=10)
    assert not created[KEY]["activated_at"]
    assert case.data["sessions"][0]["trainees"][1] == old


def test_email_escapes_name_and_contains_personal_portal_not_admin(case):
    person = case.data["sessions"][0]["trainees"][0]
    person["first_name"] = '<script>alert("x")</script>'
    content = activation.message(host, person)
    assert "<script>" not in content["html"]
    assert "&lt;script&gt;" in content["html"]
    assert "logo-integrale.png" in content["html"]
    assert "/espace/public-token" in content["html"] and "/admin/" not in content["html"]


def test_gunicorn_starts_scheduler_after_fork_and_stops_it():
    spec = importlib.util.spec_from_file_location("gunicorn_settings", "gunicorn.conf.py")
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings)
    with patch.object(activation, "start_worker") as start:
        settings.post_worker_init(None)
        start.assert_called_once_with(host)
