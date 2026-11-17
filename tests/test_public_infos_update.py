import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

import app as portal


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    trainee = {"id": "T", "token": "legacy", "city": "NICE", "address": "1 rue A",
               "updated_at": "unchanged", "billing_note": "existing"}
    training = {"id": "S", "name": "A3P", "training_type": "A3P", "stagiaires": [trainee]}
    path.write_text(json.dumps({"sessions": [training]}))
    monkeypatch.setattr(portal, "DATA_FILE", str(path))
    monkeypatch.setattr(portal, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(portal, "_partner_postgres_shadow", lambda: False)
    monkeypatch.setattr(portal, "_force_backup_snapshot", lambda *args, **kwargs: False)
    return path


def post(payload, token="legacy"):
    with portal.app.test_client() as client:
        with client.session_transaction() as auth:
            auth["public_auth_" + token] = True
        return client.post("/espace/legacy/infos/update", json=payload)


def saved(path):
    return json.loads(path.read_text())["sessions"][0]["trainees"][0]


def test_repeated_legacy_full_post_preserves_file_and_date(store):
    before = store.stat()
    contents = store.read_bytes()
    for _ in range(3):
        response = post({"city": " Nice ", "address": "1 rue A", "pre_number": "", "no_permis": False,
                         "tshirt_size": "", "billing_note": "injected"})
        assert response.status_code == 200
    assert store.stat().st_ino == before.st_ino and store.stat().st_mtime_ns == before.st_mtime_ns
    assert store.read_bytes() == contents


def test_concurrent_changes_merge_and_repeat_is_idempotent(store):
    gate = Barrier(2)

    def change(payload):
        gate.wait(timeout=5)
        return post(payload).status_code

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(change, [
            {"city": " Fréjus ", "_previous": {"city": "Nice"}},
            {"no_permis": True, "pre_number": "2026-0002805-PRE-3P-1050370"},
        ])) == [200, 200]
    trainee = saved(store)
    assert (trainee["city"], trainee["pre_number"], trainee["no_permis"]) == (
        "FRÉJUS", "2026-0002805-PRE-3P-1050370", True)
    assert trainee["updated_at"] != "unchanged" and trainee["billing_note"] == "existing"
    snapshot = store.read_bytes()
    assert post({"city": "FRÉJUS", "_previous": {"city": "Nice"}}).status_code == 200
    assert store.read_bytes() == snapshot
    assert post({"no_permis": "false"}).status_code == 200
    assert saved(store)["no_permis"] is False


def test_conflict_rejects_entire_batch_and_wrong_session_cannot_update(store):
    before = store.read_bytes()
    assert post({"city": "Lyon", "address": "2 rue B", "_previous": {"city": "Paris"}}).status_code == 409
    assert post({"address": "refusée"}, token="other").status_code == 403
    assert store.read_bytes() == before


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("0", False), ("false", False), ("true", True)])
def test_legacy_checkbox_strings(store, value, expected):
    assert post({"no_permis": not expected}).status_code == 200
    assert post({"no_permis": value}).status_code == 200
    assert saved(store)["no_permis"] is expected


def test_legacy_unlisted_shirt_can_be_corrected(store):
    data = json.loads(store.read_text())
    data["sessions"][0]["stagiaires"][0]["tshirt_size"] = "XS"
    store.write_text(json.dumps(data))
    response = post({"tshirt_size": "M", "_previous": {"tshirt_size": "XS"}})
    assert response.status_code == 200
    assert response.json["dossier_complete"] is False
    assert saved(store)["tshirt_size"] == "M"


def test_waived_permit_renders_upload_controls_for_both_choices(store, monkeypatch):
    from lxml import html

    monkeypatch.setattr(portal, "_refresh_trainee_hebergement_status", lambda *args, **kwargs: None)
    assert post({"no_permis": True}).status_code == 200
    with portal.app.test_client() as client:
        with client.session_transaction() as auth:
            auth["public_auth_legacy"] = True
        response = client.get("/espace/legacy")
    assert response.status_code == 200
    page = html.fromstring(response.data)
    row = page.get_element_by_id("doc_permis")
    assert row.get("data-doc-submitted") == "true"
    assert row.get("data-permit-submitted") == "false"
    assert "checked" in row.get_element_by_id("no_permis_checkbox").attrib
    assert "hidden" in row.get_element_by_id("upload_permis").attrib
    assert row.xpath('.//*[@data-permit-waived and not(@hidden)]')
