"""Durable Qonto receipts, consumed serially outside Gunicorn's HTTP threads."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
import time


class Inbox:
    def __init__(self, directory):
        self.path = Path(directory) / 'qonto_webhooks.sqlite3'

    @contextmanager
    def connect(self):
        # Keep a contended write below Qonto's one-second acknowledgement window.
        db = sqlite3.connect(self.path, timeout=0.4)
        try:
            with db:
                db.execute('''CREATE TABLE IF NOT EXISTS receipts (
                    seq INTEGER PRIMARY KEY, delivery TEXT NOT NULL UNIQUE,
                    resource TEXT NOT NULL, body TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    due REAL NOT NULL DEFAULT 0, finished REAL)''')
                db.execute('CREATE INDEX IF NOT EXISTS pending ON receipts(resource, seq) WHERE finished IS NULL')
                db.execute('CREATE INDEX IF NOT EXISTS finished ON receipts(finished)')
                db.execute('CREATE TABLE IF NOT EXISTS last_notice (id INTEGER PRIMARY KEY, entry TEXT NOT NULL)')
                yield db
        finally:
            db.close()

    def enqueue(self, payload, event, item, resource):
        identity = payload.get('id') or payload.get('event_id')
        if not identity:
            # Legacy payloads lack a delivery ID. Include the entire envelope so
            # two different updates to the same invoice remain distinct.
            identity = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        key = hashlib.sha256(str(identity).encode()).hexdigest()
        body = json.dumps([event, item], separators=(',', ':'))
        with self.connect() as db:
            db.execute('''INSERT INTO receipts(delivery, resource, body) VALUES(?, ?, ?)
                          ON CONFLICT(delivery) DO NOTHING''', (key, resource, body))

    def note(self, entry):
        # One bounded diagnostic for rejected/malformed or unsupported events.
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO last_notice VALUES(1, ?)', (json.dumps(entry),))

    def latest_notice(self):
        if not self.path.exists():
            return {}
        with self.connect() as db:
            row = db.execute('SELECT entry FROM last_notice WHERE id=1').fetchone()
        return json.loads(row[0]) if row else {}

    def process_one(self, process, logger):
        # The OS releases this lock after a crash. Never hold a SQLite write
        # transaction during a provider call or a business-data update.
        with self.path.with_suffix('.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            with self.connect() as db:
                row = db.execute('''SELECT seq, delivery, body, attempts FROM receipts AS r
                    WHERE finished IS NULL AND due <= ? AND NOT EXISTS (
                        SELECT 1 FROM receipts AS older WHERE older.finished IS NULL
                        AND older.resource=r.resource AND older.seq<r.seq)
                    ORDER BY seq LIMIT 1''', (time.time(),)).fetchone()
            if row is None:
                return False
            seq, key, body, attempts = row
            event, item = json.loads(body)
            try:
                result = process(key, event, item)
            except Exception as error:
                delay = min(300, 2 ** min(attempts + 1, 9))
                with self.connect() as db:
                    db.execute('UPDATE receipts SET attempts=attempts+1, due=? WHERE seq=?',
                               (time.time() + delay, seq))
                logger.warning('QONTO_WEBHOOK_RETRY seq=%s delay=%s type=%s', seq, delay, type(error).__name__)
            else:
                now = time.time()
                with self.connect() as db:
                    db.execute('UPDATE receipts SET finished=?, body=NULL WHERE seq=?', (now, seq))
                    # Keep only the delivery fingerprints for provider retries.
                    db.execute('DELETE FROM receipts WHERE finished < ?', (now - 14 * 86400,))
                logger.info('QONTO_WEBHOOK_DONE seq=%s result=%s', seq, result)
            return True


_start_lock = threading.Lock()


def start_worker(host):
    if host.app.testing or 'PYTEST_CURRENT_TEST' in os.environ:
        return
    with _start_lock:
        state = host.app.extensions.get('qonto_webhook_worker')
        if state and state['thread'].is_alive():
            return state
        stop, wake = threading.Event(), threading.Event()
        inbox = Inbox(host.PERSIST_DIR)
        gunicorn_logger = logging.getLogger("gunicorn.error")
        logger = gunicorn_logger if gunicorn_logger.handlers else host.app.logger

        def run():
            while not stop.is_set():
                wake.clear()
                try:
                    # Existing notification links use url_for. Use the configured
                    # public origin, never a webhook caller's Host or cookies.
                    with host.app.test_request_context('/api/webhooks/qonto', base_url=host.PUBLIC_BASE_URL):
                        if inbox.process_one(host._process_qonto_webhook, logger):
                            continue
                except Exception as error:
                    logger.error('QONTO_WEBHOOK_WORKER_ERROR type=%s', type(error).__name__)
                wake.wait(5)

        thread = threading.Thread(target=run, name='qonto-webhooks', daemon=True)
        state = {'thread': thread, 'stop': stop, 'wake': wake}
        host.app.extensions['qonto_webhook_worker'] = state
        thread.start()
        return state
