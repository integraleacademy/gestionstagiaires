import json
import threading

import app as gestion_app


def test_background_transaction_preserves_record_created_after_request_read(monkeypatch, tmp_path):
    monkeypatch.setattr(gestion_app, "DATA_FILE", str(tmp_path / "data.json"))
    monkeypatch.setattr(gestion_app, "BACKUP_DIR", str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()
    monkeypatch.setenv("PARTNER_POSTGRES_MODE", "off")
    gestion_app.save_data({"sessions": [{"id": "S1", "trainees": []}]})
    failures = []

    def create_record():
        try:
            data = gestion_app.load_data()
            data["sessions"][0]["trainees"].append({"id": "TRN-12345678", "first_name": "Test", "last_name": "EXAMPLE"})
            data["sessions"][0]["comment"] = "Concurrent edit"
            gestion_app.save_data(data)
        except BaseException as exc:
            failures.append(exc)

    # The CNAPS endpoint loads data before its remote checks. The same request
    # later calls update_data; its request-local cache must not become a write.
    with gestion_app.app.test_request_context("/internal/jobs/cnaps-public-annuaire-monitor", method="POST"):
        stale = gestion_app.load_data()
        assert stale["sessions"][0]["trainees"] == []
        creator = threading.Thread(target=create_record)
        creator.start()
        creator.join(timeout=5)
        assert not creator.is_alive()
        assert failures == []
        gestion_app.update_data(lambda data: data.update({"cnaps_public_annuaire_statuses": {"example": {"known": True}}}))

    persisted = json.loads((tmp_path / "data.json").read_text())
    assert persisted["sessions"][0]["trainees"][0]["id"] == "TRN-12345678"
    assert persisted["sessions"][0]["comment"] == "Concurrent edit"
    assert persisted["cnaps_public_annuaire_statuses"]["example"]["known"] is True
