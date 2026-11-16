from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import logging
import sqlite3
import threading
from unittest.mock import Mock

import pytest

import app as host
from qonto_webhook_inbox import Inbox


SECRET = 'local-receipt-test'
logger = logging.getLogger(__name__)


def invoice(delivery, invoice_id='invoice-1'):
    return {'id': delivery, 'type': 'v1/client-invoices', 'data': {'id': invoice_id, 'status': 'paid'}}


def deliver(payload, url='/api/webhooks/qonto'):
    body = json.dumps(payload).encode()
    signature = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    with host.app.test_client() as client:
        return client.post(url, data=body, content_type='application/json', headers={'X-Qonto-Signature': signature})


@pytest.fixture
def inbox(monkeypatch, tmp_path):
    monkeypatch.setattr(host, 'PERSIST_DIR', str(tmp_path))
    monkeypatch.setenv('QONTO_WEBHOOK_SECRET', SECRET)
    return Inbox(tmp_path)


def test_parallel_delivery_during_slow_processing_and_reopen(inbox, tmp_path, monkeypatch):
    never_in_http = Mock(side_effect=AssertionError('A receipt must not open the business store or contact Qonto'))
    monkeypatch.setattr(host, 'load_data', never_in_http)
    monkeypatch.setattr(host, 'get_qonto_invoice', never_in_http)
    assert deliver(invoice('delivery-a')).json == {'ok': True, 'queued': True}
    started, release = threading.Event(), threading.Event()
    processed = []

    def slow_process(key, event, item):
        processed.append(item['id'])
        started.set()
        assert release.wait(5)
        return 'updated'

    with ThreadPoolExecutor(max_workers=6) as pool:
        processing = pool.submit(inbox.process_one, slow_process, logger)
        assert started.wait(2)
        try:
            backlog = [pool.submit(deliver, invoice('delivery-b'), '/api/qonto/webhooks') for _ in range(4)]
            for response in backlog:
                assert response.result(timeout=1).json == {'ok': True, 'queued': True}
            assert host.app.test_client().get('/healthz').status_code == 200
            assert not Inbox(tmp_path).process_one(slow_process, logger)
        finally:
            release.set()
        assert processing.result(timeout=2)
    reopened = Inbox(tmp_path)
    assert reopened.process_one(slow_process, logger)
    assert deliver(invoice('delivery-a')).status_code == 200
    assert not reopened.process_one(slow_process, logger)
    assert processed == ['invoice-1', 'invoice-1']
    never_in_http.assert_not_called()
    with reopened.connect() as db:
        assert db.execute('SELECT count(*) FROM receipts WHERE body IS NOT NULL').fetchone()[0] == 0


def test_persistence_failure_never_acknowledges_delivery(inbox, monkeypatch):
    def full(*args):
        raise sqlite3.OperationalError('disk full')

    monkeypatch.setattr(Inbox, 'enqueue', full)
    assert deliver(invoice('delivery-a')).status_code == 503


def test_retry_orders_same_resource_and_allows_independent_invoices(inbox):
    for delivery, resource in [('a', 'inv1'), ('b', 'inv1'), ('c', 'inv2')]:
        assert deliver(invoice(delivery, resource)).status_code == 200
    calls = []

    def process(key, event, item):
        calls.append(item['id'])
        if len(calls) == 1:
            raise TimeoutError('temporary provider failure')
        return 'updated'

    assert inbox.process_one(process, logger)
    assert inbox.process_one(process, logger)
    assert calls == ['inv1', 'inv2']
    assert not inbox.process_one(process, logger)
    with inbox.connect() as db:
        db.execute('UPDATE receipts SET due=0 WHERE attempts=1')
    assert inbox.process_one(process, logger)
    assert inbox.process_one(process, logger)
    assert calls == ['inv1', 'inv2', 'inv1', 'inv1']


def test_crash_after_business_commit_does_not_apply_twice(inbox, monkeypatch):
    current = {'sessions': [], 'billing_lines': []}
    monkeypatch.setattr(host, '_atomic_update_data', lambda fn: fn(current))
    monkeypatch.setattr(host.exam_retakes, 'notify', lambda *args, **kwargs: False)
    monkeypatch.setattr(host, 'get_qonto_invoice', lambda i: {'id': i, 'status': 'paid'})
    assert deliver(invoice('a')).status_code == 200

    def interrupted(*args):
        host._process_qonto_webhook(*args)
        raise SystemExit()

    with pytest.raises(SystemExit):
        inbox.process_one(interrupted, logger)
    assert Inbox(host.PERSIST_DIR).process_one(host._process_qonto_webhook, logger)
    assert len(current['qonto_webhook_history']) == 1


def test_invalid_signature_is_rejected_before_processing(inbox):
    with host.app.test_client() as client:
        assert client.post('/api/webhooks/qonto', json=invoice('a')).status_code == 401
    assert inbox.latest_notice()['error'] == 'invalid_signature'
    assert not inbox.process_one(Mock(), logger)
