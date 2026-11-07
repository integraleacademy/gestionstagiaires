import copy
import hashlib
from unittest.mock import patch

import pytest

import app as host
import desp_vae_elearning as vae
import vtc_elearning_activation as vtc
from tests import test_native_elearning_web as web
from trainee_elearning_reporting import source_for

BASE = "/admin/sessions/session-aps/stagiaires/trainee-1"


@pytest.fixture
def case():
    value = web.NativeElearningWebTests(methodName="runTest")
    value.setUp()
    training = value.data["sessions"][0]
    training.update(training_type="DIRIGEANT VAE", date_start="2099-01-01",
                    aps_elearning_enabled=False, aps_native_course_id="")
    training["trainees"][0]["email"] = "test@example.test"
    value._admin_login()
    try:
        yield value
    finally:
        value.tearDown()


def test_preview_grant_and_progress_use_the_same_registration(case):
    training = case.data["sessions"][0]
    person = training["trainees"][0]
    before = copy.deepcopy(case.data)
    url = BASE + "/e-learning/aps"
    preview = case.client.get(url + "/apercu").json
    assert preview["email"] == person["email"] and preview["can_send"]
    assert "/espace/public-token" in preview["html"]
    assert before == case.data
    assert source_for(training, person) is None
    with patch.object(host, "brevo_send_email", return_value={"ok": True}) as send:
        assert case.client.post(url, json={"ticket": preview["ticket"], "send": False}).json["status"] == "not_sent"
        send.assert_not_called()
        modules = copy.deepcopy(person[vae.KEY]["modules"])
        assert sum(m["required_minutes"] for m in modules) == 62 * 60
        for _ in range(2):
            assert case.client.post(url, json={"ticket": preview["ticket"], "send": True}).json["status"] == "sent"
        send.assert_called_once()
        assert send.call_args.args == (person["email"], preview["subject"], preview["html"])
    assert person[vae.KEY]["modules"] == modules
    assert source_for(training, person)[0]["id"] == training["id"]
    assert source_for(training, {"id": "other"}) is None
    assert not training["aps_elearning_enabled"]
    sheet = case.client.get(BASE)
    assert "Gérer l’accès e-learning APS" in sheet.text
    assert "Consulter le suivi détaillé" in sheet.text
    assert case.client.get(BASE + "/e-learning/suivi/resume").status_code == 200
    vae.preserve_state(before, case.data, host._session_trainees_list)
    assert before["sessions"][0]["trainees"][0][vae.KEY] == person[vae.KEY]
    with case.client.session_transaction() as login:
        login.clear()
    case._public_login()
    assert "Accéder à mon parcours APS" in case.client.get("/espace/public-token").text
    assert case.client.get("/espace/public-token/elearning").status_code == 200
    assert case.client.get("/espace/public-token/elearning/" + modules[0]["course_id"]).status_code == 200


def test_vae_scope_and_explicit_email_choice(case):
    url = BASE + "/e-learning/aps"
    assert case.client.post(url, json={}).status_code == 400
    training = case.data["sessions"][0]
    person = training["trainees"][0]
    preview = case.client.get(url + "/apercu").json
    person["email"] = "another@example.test"
    assert case.client.post(url, json={"ticket": preview["ticket"], "send": True}).status_code == 409
    assert vae.KEY not in person
    training["training_type"] = "DIRIGEANT INITIAL"
    assert case.client.get(url + "/apercu").status_code == 404
    assert case.client.post(url, json={"ticket": preview["ticket"]}).status_code == 404
    training["training_type"] = "DIRIGEANT VAE"
    with case.client.session_transaction() as login:
        login["admin_role"] = "viewer"
    assert case.client.get(url + "/apercu").status_code == 403


def test_individual_vtc_grant_is_silent_idempotent_and_isolated(case):
    training = case.data["sessions"][0]
    training["training_type"] = "CHAUFFEUR VTC"
    person = training["trainees"][0]
    other = {"id": "same-session"}
    training["trainees"].append(other)
    stale = copy.deepcopy(case.data)
    fingerprint = hashlib.sha256(f"{training['id']}/{person['id']}".encode()).hexdigest()
    with patch.object(vtc, "INDIVIDUAL_VTC_GRANT", fingerprint), patch.object(host, "brevo_send_email") as mail:
        vtc.process_due(host, data=case.data)
        state = copy.deepcopy(person[vtc.STATE_KEY])
        vtc.process_due(host, data=stale)
        vtc.process_due(host, data=case.data)
        mail.assert_not_called()
    assert len(state["modules"]) == 8 and state["activated_at"] and state["email_status"] == "not_requested"
    assert state == person[vtc.STATE_KEY] and vtc.STATE_KEY not in other
    assert not training["aps_elearning_enabled"]
    assert source_for(training, person)[0]["course_code"] == "vtc"
