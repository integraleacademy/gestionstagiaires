from concurrent.futures import ThreadPoolExecutor
import copy
import datetime
import json
import threading
from unittest.mock import Mock

import app as gestion


def test_plain_read_does_not_wait_for_atomic_writer_and_backup_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    before = {"sessions": [], "value": "état précédent"}
    after = {"sessions": [], "value": "état suivant"}
    path.write_text(json.dumps(before))
    monkeypatch.setattr(gestion, "DATA_FILE", str(path))
    monkeypatch.setattr(gestion, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(gestion, "BACKUP_SNAPSHOT_BEFORE_SAVE", True)
    monkeypatch.setattr(gestion, "_store_partner_auth_index", lambda *a: None)
    locked, release = threading.Event(), threading.Event()

    def pause_writer(payload):
        locked.set()
        assert release.wait(3)
        return payload

    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(gestion._write_json_with_backups, str(path), after,
                                gestion._data_lock, pause_writer)
        try:
            assert locked.wait(1)
            reader = workers.submit(gestion._load_valid_json_payload, str(path))
            assert reader.result(timeout=1) == before
        finally:
            release.set()
        writer.result(timeout=2)
    assert gestion._load_valid_json_payload(str(path)) == after
    assert any(json.loads(p.read_text()) == before for p in backup_dir.glob("*.json"))
    assert "\n" not in path.read_text()


def billing_data():
    return {"sessions": [{
        "id": f"S{i}", "training_type": "APS", "date_start": "2026-09-01", "date_end": "2026-09-30",
        "trainees": [{"id": f"T{i}-{j}", "first_name": "Test", "last_name": str(j), "personal_amount": 950}
                     for j in range(6)],
    } for i in range(4)], "billing_lines": []}


def test_scoped_billing_matches_global_results_and_only_builds_one_trainee(monkeypatch):
    data = billing_data()
    monkeypatch.setattr(gestion, "_now_iso", lambda: "2026-10-06T08:00:00Z")
    all_lines = gestion._billing_lines(data)
    expected = [line for line in all_lines if line['sessionId'] == 'S2' and line['traineeId'] == 'T2-3']
    old = copy.deepcopy(expected[0])
    old.update(qontoInvoiceId="invoice-existing", invoiceStatus="finalized", qonto_amount_paid_cents=10000)
    # Historical rows can still be matched by ID without the newer scope fields.
    old.pop('sessionId')
    old.pop('traineeId')
    data['billing_lines'].append(old)
    expected = [line for line in gestion._billing_lines(data) if line['sessionId'] == 'S2' and line['traineeId'] == 'T2-3']
    builder = Mock(wraps=gestion.buildBillingLinesFromSessions)
    monkeypatch.setattr(gestion, "buildBillingLinesFromSessions", builder)
    assert gestion._billing_lines_for_trainee_session(data, 'T2-3', 'S2') == expected
    scoped = builder.call_args.args[0]
    assert len(scoped) == 1
    assert [t['id'] for t in scoped[0]['trainees']] == ['T2-3']
    assert len(data['sessions'][2]['trainees']) == 6
    assert gestion._billing_lines_for_trainee_session(data, 'missing', 'S2') == []


def test_local_billing_poll_never_calls_qonto_or_rewrites_data(monkeypatch):
    data = billing_data()
    monkeypatch.setattr(gestion, 'load_data', lambda **kw: data)
    for name in ('_qonto_is_configured', '_discover_cpf_qonto_invoice',
                 '_sync_billing_line_with_qonto', '_repair_logged_qonto_rejection_retries', 'save_data'):
        monkeypatch.setattr(gestion, name, Mock(side_effect=AssertionError(name)))
    with gestion.app.test_request_context('/api/billing/trainee/T2-3/session/S2?local=1'):
        response = gestion.api_billing_trainee_session.__wrapped__('T2-3', 'S2')
    assert response.status_code == 200
    assert response.json['lines'][0]['traineeId'] == 'T2-3'


def test_cnaps_recent_result_reused_but_manual_refresh_bypasses_it(monkeypatch):
    data = {'sessions': [], 'cnaps_public_annuaire_statuses': {}}
    snapshot = {'check_status': 'success', 'active_titles': [], 'checked_at': gestion._now_iso()}
    data['cnaps_public_annuaire_statuses']['TEST|1234567'] = {'result': snapshot}
    monkeypatch.setattr(gestion, 'load_data', lambda **kw: data)
    remote = Mock(return_value={'check_status': 'error', 'error': 'temporarily unavailable'})
    save = Mock(side_effect=AssertionError('Cached reads must not rewrite the database'))
    monkeypatch.setattr(gestion, 'fetch_cnaps_public_annuaire', remote)
    monkeypatch.setattr(gestion, 'save_data', save)
    url = '/api/cnaps_public_annuaire?nom=TEST&nub=1234567'
    with gestion.app.test_request_context(url):
        response = gestion.api_cnaps_public_annuaire.__wrapped__()
    assert response.json['cached'] is True
    remote.assert_not_called()
    with gestion.app.test_request_context(url + '&cache=bypass'):
        response, status = gestion.api_cnaps_public_annuaire.__wrapped__()
    assert status == 502
    remote.assert_called_once_with('TEST', '1234567')
    snapshot['checked_at'] = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=6)).isoformat()
    with gestion.app.test_request_context(url):
        _, status = gestion.api_cnaps_public_annuaire.__wrapped__()
    assert status == 502
    assert remote.call_count == 2
