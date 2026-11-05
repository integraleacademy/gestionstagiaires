import copy
from functools import wraps
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

from flask import Flask, jsonify, session
import pytest

import edof_readonly_test as pilot


FOLDER_ID = "123456789012"


@pytest.fixture
def observation():
    return {"siret": pilot.SIRET, "folder": {
        "id": FOLDER_ID, "currentState": "serviceDoneValidated",
        "trainingId": pilot.SIRET + "_formation_demo",
        "trainingActionId": pilot.SIRET + "_action_demo",
        "beginDate": "2024-11-14", "endDate": "2024-12-14",
        "billingDate": None, "currentBillingState": None, "paymentState": None,
        "attendee": {"firstName": "Camille", "lastName": "EXEMPLE", "email": "exemple@example.invalid"},
        "trainingActionInfo": {"title": "Formation de démonstration", "sessionId": pilot.SIRET + "_session_demo",
            "sessionStartDate": "14/11/2024", "sessionEndDate": "14/12/2024", "totalIncl": 1600,
            "trainingCompletionRate": 100, "validatedServiceDone": True},
    }}


@pytest.fixture
def web(tmp_path):
    root = Path(pilot.__file__).parent
    app = Flask(__name__, template_folder=str(root / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="local-unit-test-only")
    store = pilot.ObservationStore(tmp_path)
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps({"sessions": [], "wedof_links": []}))

    def admin_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("admin_logged_in"):
                return jsonify(ok=False), 401
            return view(*args, **kwargs)
        return wrapper

    pilot.register_routes(app, store, admin_required=admin_required,
        can_access=lambda: session.get("admin_role") == "admin" and not session.get("partner_id") and not session.get("assist_partner_id"),
        data_file=data_path)
    # The preview must not invoke legacy context processors or business loaders.
    @app.context_processor
    def forbidden_context():
        raise AssertionError("Legacy context processor was invoked")
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(admin_logged_in=True, admin_role="admin")
    assert client.get("/admin/edof-test").status_code == 200
    with client.session_transaction() as sess:
        csrf = sess["edof_test_csrf"]
    return SimpleNamespace(app=app, client=client, store=store, data_path=data_path, csrf=csrf)


def prepare(web):
    response = web.client.post("/admin/edof-test/prepare", json={"folder_id": FOLDER_ID}, headers={"X-CSRF-Token": web.csrf})
    assert response.status_code == 200
    return response.json["code"]


def deliver(web, key, payload):
    # An extension sends no session cookie. Authenticate only with the one-use key.
    return web.app.test_client().post("/api/edof-test/receive", json=payload, headers={"X-Edof-Test-Key": key})


def test_normalization_preserves_unknown_finance_and_dates(observation):
    result = pilot.normalize_observation(observation, FOLDER_ID)
    assert result["title"] == "Formation de démonstration"
    assert result["start_date"] == result["session_start_date"] == "2024-11-14"
    assert result["total_incl"] == "1600.00"
    assert result["billing_state"] is None
    assert result["payment_state"] is None


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(siret="00000000000000"),
    lambda p: p["folder"].update(id="999999999999"),
    lambda p: p["folder"].update(Authorization="synthetic-prohibited-field"),
    lambda p: p["folder"]["attendee"].update(birthDate="01/01/2000"),
    lambda p: p["folder"]["trainingActionInfo"].update(vat=1600),
    lambda p: p["folder"]["trainingActionInfo"].update(sessionId="00000000000000_other"),
    lambda p: p["folder"].update(beginDate="31/02/2024"),
    lambda p: p["folder"]["trainingActionInfo"].update(totalIncl=float("nan")),
    lambda p: p["folder"]["trainingActionInfo"].update(totalIncl=-5),
    lambda p: p["folder"]["trainingActionInfo"].update(totalIncl=True),
    lambda p: p["folder"]["trainingActionInfo"].update(trainingCompletionRate=101),
])
def test_invalid_or_excess_fields_rejected(observation, mutation):
    mutation(observation)
    with pytest.raises(pilot.InvalidObservation):
        pilot.normalize_observation(observation, FOLDER_ID)


def test_receive_is_single_use_and_cannot_write_business_data(web, observation):
    before = web.data_path.read_bytes()
    key = prepare(web)
    assert deliver(web, key, observation).status_code == 201
    assert deliver(web, key, observation).status_code == 401
    assert web.data_path.read_bytes() == before
    page = web.client.get("/admin/edof-test")
    assert page.status_code == 200
    assert "Dossier reçu" in page.text
    assert "Camille" in page.text
    assert "Non renseigné dans cette réponse" in page.text
    assert "Aucune inscription n’est présente" in page.text
    assert key not in page.text
    assert key.encode() not in web.store.path.read_bytes()
    assert web.store.path.stat().st_mode & 0o777 == 0o600


def test_wrong_dossier_does_not_consume_code(web, observation):
    key = prepare(web)
    wrong = copy.deepcopy(observation)
    wrong["folder"]["id"] = "888888888888"
    assert deliver(web, key, wrong).status_code == 400
    assert deliver(web, key, observation).status_code == 201


def test_expiration_and_new_code_revoke_previous(web, observation, monkeypatch):
    old = prepare(web)
    current = prepare(web)
    assert deliver(web, old, observation).status_code == 401
    now = pilot.time.time()
    monkeypatch.setattr(pilot.time, "time", lambda: now + pilot.PAIR_TTL + 1)
    assert deliver(web, current, observation).status_code == 401


def test_admin_auth_roles_and_csrf(web):
    anonymous = web.app.test_client()
    for path in ("/admin/edof-test", "/admin/edof-test/extension.zip", "/admin/edof-test/assets/page.js"):
        assert anonymous.get(path).status_code == 401
    assert anonymous.post("/api/edof-test/receive", json={}).status_code == 401
    assert web.client.post("/admin/edof-test/prepare", json={"folder_id": FOLDER_ID}).status_code == 403
    assert web.client.post("/admin/edof-test/clear").status_code == 403
    for field, value in (("admin_role", "viewer"), ("partner_id", "other"), ("assist_partner_id", "other")):
        with web.client.session_transaction() as sess:
            sess.clear()
            sess.update(admin_logged_in=True, admin_role="admin")
            sess[field] = value
        assert web.client.get("/admin/edof-test").status_code == 403


def test_owner_scope_and_delete(web, observation):
    key = prepare(web)
    assert deliver(web, key, observation).status_code == 201
    second = web.app.test_client()
    with second.session_transaction() as sess:
        sess.update(admin_logged_in=True, admin_role="admin")
    assert "Camille" not in second.get("/admin/edof-test").text
    assert web.client.post("/admin/edof-test/clear", headers={"X-CSRF-Token": web.csrf}).status_code == 200
    assert "Camille" not in web.client.get("/admin/edof-test").text
    assert deliver(web, key, observation).status_code == 401


def test_public_ping_does_not_create_a_store(web):
    response = web.app.test_client().get("/api/edof-test/ping")
    assert response.status_code == 200
    assert response.json["autonomous_sync"] is False


def test_result_expiry_and_html_escaping(web, observation, monkeypatch):
    observation["folder"]["trainingActionInfo"]["title"] = "<script>unsafe()</script>"
    assert deliver(web, prepare(web), observation).status_code == 201
    html = web.client.get("/admin/edof-test").text
    assert "<script>unsafe()" not in html
    assert "&lt;script&gt;unsafe()" in html
    now = pilot.time.time()
    monkeypatch.setattr(pilot.time, "time", lambda: now + pilot.RESULT_TTL + 1)
    assert "Camille" not in web.client.get("/admin/edof-test").text


def test_content_limits_and_zip_scope(web):
    key = prepare(web)
    response = web.app.test_client().post("/api/edof-test/receive", data=b" " * (pilot.MAX_BODY + 1), content_type="application/json", headers={"X-Edof-Test-Key": key})
    assert response.status_code == 413
    response = web.client.get("/admin/edof-test/extension.zip")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        manifest = json.loads(archive.read("integrale-edof-test/manifest.json"))
        assert manifest["host_permissions"] == [pilot.TEST_ORIGIN + "/*"]
        assert not manifest.get("permissions")
        assert len(archive.namelist()) == 8
    assert web.client.get("/admin/edof-test/assets/not-allowed").status_code == 404


def test_production_is_disabled_even_with_test_host(monkeypatch):
    for service in ("", "srv-production"):
        monkeypatch.setenv("RENDER_SERVICE_ID", service)
        app = Flask(__name__)
        pilot.register_edof_readonly_test(SimpleNamespace(app=app))
        assert app.config["EDOF_READONLY_TEST_ENABLED"] is False
        assert app.test_client().get("/api/edof-test/ping", base_url=pilot.TEST_ORIGIN).status_code == 404


def test_exact_matching_precedence_and_ambiguity():
    trainee = {"id": "T1", "first_name": "Camille", "last_name": "EXEMPLE"}
    data = {"sessions": [{"id": "S1", "trainees": [trainee]}], "wedof_links": []}
    before = copy.deepcopy(data)
    assert pilot.build_comparison(data, {"folder_id": FOLDER_ID})["status"] == "absent"
    assert data == before
    link = {"active": True, "external_id": FOLDER_ID, "session_id": "S1", "trainee_id": "T1"}
    data["wedof_links"] = [link]
    assert pilot.build_comparison(data, {"folder_id": FOLDER_ID})["status"] == "found"
    data["wedof_links"].append(copy.deepcopy(link))
    assert pilot.build_comparison(data, {"folder_id": FOLDER_ID})["status"] == "ambiguous_link"


def test_matching_render_is_escaped_read_only_and_uses_existing_observation(web, observation):
    local = {"sessions": [{"id": "S1", "name": "<script>private()</script>", "training_type": "APS",
             "date_start": "2024-11-14", "date_end": "2024-12-14", "trainees": [{"id": "T1",
             "first_name": "Camille", "last_name": "EXEMPLE", "email": "exemple@example.invalid",
             "address": "NEVER_RENDER_PRIVATE_ADDRESS"}]}]}
    web.data_path.write_text(json.dumps(local))
    original_data = web.data_path.read_bytes()
    assert deliver(web, prepare(web), observation).status_code == 201
    with web.client.session_transaction() as sess:
        owner = pilot.hashlib.sha256(sess["edof_test_owner"].encode()).hexdigest()
    received_at = web.store.latest(owner)["received_at"]
    html = web.client.get("/admin/edof-test").text
    assert "Une correspondance proposée" in html
    assert "Nom et prénom concordants" in html
    assert "&lt;script&gt;private()" in html and "<script>private()" not in html
    assert "NEVER_RENDER_PRIVATE_ADDRESS" not in html
    assert "ne créent aucun rattachement" in html
    assert web.data_path.read_bytes() == original_data
    assert web.store.latest(owner)["received_at"] == received_at


def test_matching_unavailable_data_does_not_hide_received_folder(web, observation):
    assert deliver(web, prepare(web), observation).status_code == 201
    web.data_path.write_text("not valid JSON")
    html = web.client.get("/admin/edof-test").text
    assert "Dossier reçu" in html and "Camille" in html
    assert "données locales sont indisponibles" in html
