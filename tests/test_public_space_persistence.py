import copy
import json
from unittest.mock import Mock

import app as host


def test_repeated_public_visits_keep_the_dossier_file_unchanged(tmp_path, monkeypatch):
    """Use the real JSON transaction, including its protections for concurrent writes."""
    trainee = {"id": "person", "public_token": "token", "city": "  paris "}
    training = {"id": "training", "name": "APS", "training_type": "APS",
                "date_start": "2026-11-03", "trainees": [trainee]}
    file = tmp_path / "data.json"
    file.write_text(json.dumps({"sessions": [training]}))
    monkeypatch.setattr(host, "DATA_FILE", str(file))
    monkeypatch.setattr(host, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(host, "_partner_postgres_shadow", lambda: False)
    monkeypatch.setattr(host, "BACKUP_SNAPSHOT_BEFORE_SAVE", False)
    monkeypatch.setattr(host, "_force_backup_snapshot", lambda *args, **kwargs: False)
    writes = Mock(wraps=host._write_json_with_backups)
    monkeypatch.setattr(host, "_write_json_with_backups", writes)
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth["public_auth_token"] = True

    assert client.get("/espace/token").status_code == 200
    saved = json.loads(file.read_text())["sessions"][0]["trainees"][0]
    assert saved["public_has_logged_in"] is True
    assert saved["public_last_login_at"]
    assert saved["city"] == host.normalize_city("  paris ")
    assert saved["documents"]
    writes.reset_mock()
    first = file.read_bytes()

    for _ in range(3):
        assert client.get("/espace/token").status_code == 200

    writes.assert_not_called()
    assert file.read_bytes() == first


def test_opening_a_stale_record_preserves_newer_documents_and_login(monkeypatch):
    trainee = {"id": "person", "public_token": "token"}
    training = {"id": "training", "name": "APS", "training_type": "APS", "trainees": [trainee]}
    data = {"sessions": [training]}
    current = copy.deepcopy(data)
    latest = current["sessions"][0]["trainees"][0]
    latest.update(public_has_logged_in=True, public_last_login_at="most-recent-login")
    host._prepare_public_space_record(current["sessions"][0], latest, None)
    doc = latest["documents"][0]
    doc.update(status="VALIDÉ", file="new.pdf", files=["new.pdf"])
    latest["city"] = "LYON"
    before = copy.deepcopy(latest)
    writes = []

    def persist(mutate):
        result = mutate(current)
        writes.append(result)
        return result

    monkeypatch.setattr(host, "load_data", lambda: copy.deepcopy(data))
    monkeypatch.setattr(host, "_atomic_update_data", persist)
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth["public_auth_token"] = True

    assert client.get("/espace/token").status_code == 200
    assert latest == before
    assert not writes


def test_invalidated_token_is_denied_during_first_login(monkeypatch):
    training = {"id": "S", "name": "APS", "training_type": "APS",
                "trainees": [{"id": "T", "public_token": "old"}]}
    monkeypatch.setattr(host, "load_data", lambda: {"sessions": [training]})
    canonical = copy.deepcopy(training)
    canonical["trainees"][0]["public_token"] = "rotated"
    monkeypatch.setattr(host, "_atomic_update_data", lambda update: update({"sessions": [canonical]}))
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth["public_auth_old"] = True
    assert client.get("/espace/old").status_code == 404
    assert "public_has_logged_in" not in canonical["trainees"][0]


def test_concurrent_session_date_edit_does_not_apply_outdated_housing_result(monkeypatch):
    training = {"id": "S", "training_type": "A3P", "date_start": "2026-11-12",
                "trainees": [{"id": "T", "public_token": "token", "hosting_status": "unknown"}]}
    latest = copy.deepcopy(training)
    latest["date_start"] = "2027-01-22"
    monkeypatch.setattr(host, "load_data", lambda: {"sessions": [training]})
    monkeypatch.setattr(host, "fetch_hebergement_status", lambda *args, **kwargs: "reserved")
    monkeypatch.setattr(host, "_atomic_update_data", lambda update: update({"sessions": [latest]}))
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth["public_auth_token"] = True
    assert client.get("/espace/token").status_code == 200
    assert latest["trainees"][0]["hosting_status"] == "unknown"
    assert latest["trainees"][0]["public_has_logged_in"] is True
