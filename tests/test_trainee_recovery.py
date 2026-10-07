import copy
import json

import pytest

from trainee_recovery import backup_inventory, find_backup, find_original_conventions, restore_missing


PARTNER = "integrale"
TRAINEE = {"id": "TRN-12345678", "first_name": "Test", "last_name": "EXAMPLE",
           "public_token": "original-token", "documents": [{"path": "original.pdf"}]}


def backup(tmp_path):
    payload = {"sessions": [{"id": "S1", "partner_id": PARTNER, "trainees": [TRAINEE]}],
               "billing_lines": [{"id": "B1", "trainee_id": TRAINEE["id"], "session_id": "S1", "amount": 10}]}
    (tmp_path / "data_json.20260909T131900.json").write_text(json.dumps(payload))
    return payload


def test_search_finds_latest_valid_copy_despite_later_absence_and_corruption(tmp_path):
    backup(tmp_path)
    (tmp_path / "data_json.20260909T132000.json").write_text('{"sessions": []}')
    (tmp_path / "data_json.20260909T132100.json").write_text('{"TRN-12345678":')
    result = find_backup(tmp_path, TRAINEE["id"], PARTNER)
    assert result["trainee"] == TRAINEE
    assert result["source"] == "data_json.20260909T131900.json"
    assert find_backup(tmp_path, TRAINEE["id"], "another-partner") is None


def test_selective_recovery_preserves_other_records_edits_and_existing_finances(tmp_path):
    backup(tmp_path)
    bundle = find_backup(tmp_path, TRAINEE["id"], PARTNER)
    current = {"sessions": [{"id": "S1", "partner_id": PARTNER, "comment": "New edit", "trainees": [{"id": "T2"}]}],
               "billing_lines": [{"id": "B1", "trainee_id": TRAINEE["id"], "session_id": "S1", "amount": 20}],
               "qonto_oauth": {"unchanged": True}}
    restore_missing(current, bundle)
    assert current["sessions"][0]["trainees"] == [{"id": "T2"}, TRAINEE]
    assert current["sessions"][0]["comment"] == "New edit"
    assert current["billing_lines"][0]["amount"] == 20
    assert current["qonto_oauth"] == {"unchanged": True}
    with pytest.raises(ValueError, match="existe déjà"):
        restore_missing(current, bundle)


def test_recovery_refuses_missing_session_and_conflicting_link_without_mutation(tmp_path):
    backup(tmp_path)
    bundle = find_backup(tmp_path, TRAINEE["id"], PARTNER)
    with pytest.raises(ValueError, match="session"):
        restore_missing({"sessions": []}, bundle)
    current = {"sessions": [{"id": "S1", "partner_id": PARTNER, "trainees": []}],
               "billing_lines": [{"id": "B1", "trainee_id": "OTHER", "session_id": "S1"}]}
    before = copy.deepcopy(current)
    with pytest.raises(ValueError, match="autre dossier"):
        restore_missing(current, bundle)
    assert current == before


def test_search_rejects_path_traversal_and_invalid_identifier(tmp_path):
    with pytest.raises(ValueError):
        find_backup(tmp_path, "../data.json", PARTNER)
    with pytest.raises(ValueError):
        find_backup(tmp_path, TRAINEE["id"], PARTNER, source="../data_json.file.json")


def test_recovery_checks_valid_retained_corruption_copy_and_reports_inventory(tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    payload = backup(root)
    inventory = backup_inventory(root)
    assert inventory["count"] == 1
    assert inventory["oldest"] == inventory["newest"]
    (root / inventory["oldest"]).unlink()
    source = "data.json.corrupt.20260909T132000"
    (tmp_path / source).write_text(json.dumps(payload))
    found = find_backup(root, TRAINEE["id"], PARTNER)
    assert found["source"] == source
    assert find_backup(root, TRAINEE["id"], PARTNER, source=source) == found


def test_original_conventions_read_existing_matching_documents_only(tmp_path):
    from docx import Document
    root = tmp_path / "generated_documents" / "conventions_aps"
    root.mkdir(parents=True)
    path = root / "convention_formation_aps_EXAMPLE_Test.docx"
    document = Document()
    document.add_paragraph("Test EXAMPLE : original retained information")
    document.save(path)
    result = find_original_conventions(tmp_path, "Example")
    assert len(result) == 1
    assert result[0]["name"] == path.name
    assert "original retained information" in result[0]["text"]
    assert find_original_conventions(tmp_path, "Someone else") == []
    assert find_original_conventions(tmp_path, "") == []


def test_recovery_route_denies_anonymous_viewers_and_partner_admins(monkeypatch, tmp_path):
    import app as gestion_app
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(tmp_path / "data.json"))
    (tmp_path / "data.json").write_text('{"sessions": []}')
    client = gestion_app.app.test_client()
    path = "/admin/tools/trainee-recovery"
    assert client.get(path).status_code == 302
    for role, partner in [("viewer", gestion_app.INTEGRALE_PARTNER_ID), ("admin", "another-partner")]:
        with client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = role
            session["partner_id"] = partner
            session[gestion_app.SESSION_ISSUED_AT_KEY] = "2099-01-01T00:00:00Z"
        assert client.get(path).status_code in {302, 403}


def test_admin_can_preview_and_restore_only_the_selected_missing_record(monkeypatch, tmp_path):
    import app as gestion_app
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "off")
    (tmp_path / "backups").mkdir()
    old = {"sessions": [{"id": "S1", "partner_id": gestion_app.INTEGRALE_PARTNER_ID, "trainees": [TRAINEE]}]}
    source = "data_json.20260909T131900.json"
    (tmp_path / "backups" / source).write_text(json.dumps(old))
    gestion_app.save_data({"sessions": [{"id": "S1", "partner_id": gestion_app.INTEGRALE_PARTNER_ID, "trainees": []}]})
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
        session[gestion_app.SESSION_ISSUED_AT_KEY] = "2099-01-01T00:00:00Z"
    path = "/admin/tools/trainee-recovery"
    preview = client.get(path, query_string={"trainee_id": TRAINEE["id"]})
    assert preview.status_code == 200
    assert b"EXAMPLE" in preview.data
    assert client.post(path, data={"trainee_id": TRAINEE["id"]}).status_code == 403
    with client.session_transaction() as session:
        csrf = session["trainee_recovery_csrf"]
    bundle = find_backup(gestion_app.BACKUP_DIR, TRAINEE["id"], gestion_app.INTEGRALE_PARTNER_ID)
    form = {"csrf": csrf, "trainee_id": TRAINEE["id"], "source": source, "fingerprint": bundle["fingerprint"]}
    restored = client.post(path, data=form)
    assert restored.status_code == 302
    assert restored.headers["Location"].endswith("/S1/stagiaires/TRN-12345678")
    persisted = json.loads((tmp_path / "data.json").read_text())
    assert persisted["sessions"][0]["trainees"] == [TRAINEE]
    assert client.post(path, data=form).status_code == 409
