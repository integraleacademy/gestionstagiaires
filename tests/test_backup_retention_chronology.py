import json
from pathlib import Path

import app as gestion_app
from trainee_recovery import backup_inventory, find_backup


def test_new_snapshot_survives_when_legacy_manual_backups_fill_retention(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(gestion_app, "BACKUP_RETENTION", 2)
    for hour in ("010000", "020000"):
        (backup_dir / f"data_json.manual.20260517T{hour}Z.json").write_text('{"sessions": []}')
    current = tmp_path / "data.json"
    current.write_text('{"sessions": [{"id": "NEW"}]}')
    snapshot = gestion_app._force_backup_snapshot(str(current), reason="pre-trainee-recovery")
    assert snapshot and Path(snapshot).is_file()
    assert json.loads(Path(snapshot).read_text())["sessions"][0]["id"] == "NEW"
    assert len(list(backup_dir.iterdir())) == 2
    assert not (backup_dir / "data_json.manual.20260517T010000Z.json").exists()


def test_restore_and_recovery_choose_latest_timestamp_across_naming_formats(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(backup_dir))
    old = {"sessions": [{"id": "S1", "trainees": [{"id": "TRN-12345678", "first_name": "Old"}]}]}
    new = {"sessions": [{"id": "S1", "trainees": [{"id": "TRN-12345678", "first_name": "Current"}]}]}
    (backup_dir / "data_json.manual.20260517T010000Z.json").write_text(json.dumps(old))
    newest = "data_json.20260909T131950.123456Z.before-save.example.json"
    (backup_dir / newest).write_text(json.dumps(new))
    target = tmp_path / "data.json"
    assert gestion_app._restore_latest_backup(str(target))
    assert json.loads(target.read_text()) == new
    target.unlink()
    assert gestion_app._recover_data_file(str(target)) == str(backup_dir / newest)
    assert json.loads(target.read_text()) == new
    assert backup_inventory(backup_dir)["newest"] == newest
    assert find_backup(backup_dir, "TRN-12345678", "integrale")["trainee"]["first_name"] == "Current"
