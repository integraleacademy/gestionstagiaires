"""Last authenticated partner access, including persistent sessions."""
import datetime as dt
from contextlib import closing
from pathlib import Path
import sqlite3

from flask import request, session


def record(host, partner_id, user_id, stamp):
    path = Path(host.PERSIST_DIR) / 'partner-presence.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS presence (partner TEXT, user TEXT, seen TEXT, PRIMARY KEY(partner,user))')
        db.execute('''INSERT INTO presence VALUES(?,?,?) ON CONFLICT(partner,user)
                      DO UPDATE SET seen=excluded.seen WHERE excluded.seen > presence.seen''',
                   (partner_id, user_id, stamp))


def latest(host, data):
    """Account activity only; admin assistance is not a partner visit."""
    users = {str(u.get('id')): u for u in data.get('users', []) if isinstance(u, dict) and u.get('id')}
    by_email = {(u.get('partner_id'), str(u.get('email') or '').lower()): uid for uid,u in users.items() if u.get('email')}
    stamps = {}
    def keep(uid, pid, value):
        user = users.get(str(uid))
        if not user or not pid or user.get('partner_id') != pid:
            return
        stamp = host._parse_iso_datetime(value)
        if stamp and (str(uid) not in stamps or stamp > stamps[str(uid)]):
            stamps[str(uid)] = stamp
    for uid,u in users.items():
        keep(uid, u.get('partner_id'), u.get('last_login_at'))
    for log in data.get('activity_logs', []):
        pid = log.get('partner_id')
        uid = by_email.get((pid, str(log.get('user') or '').lower()))
        if log.get('action') == 'login' and log.get('resource_type') == 'user':
            uid = log.get('resource_id')
        if not str(log.get('action') or '').startswith('super_admin_'):
            keep(uid, pid, log.get('created_at'))
    # Only timestamps from explicit account actions, never payment or worker updates.
    for order in data.get('manual_orders', []):
        terms = order.get('terms_acceptance') or {}
        if terms.get('accepted_at'):
            keep(terms.get('user_id'), order.get('partner_id'), terms.get('accepted_at'))
        else:
            keep(order.get('created_by'), order.get('partner_id'), order.get('created_at'))
    path = Path(host.PERSIST_DIR) / 'partner-presence.sqlite3'
    if path.exists():
        try:
            with closing(sqlite3.connect(path, timeout=1)) as db:
                for pid,uid,stamp in db.execute('SELECT partner,user,seen FROM presence'):
                    keep(uid, pid, stamp)
        except sqlite3.Error:
            host.app.logger.warning('partner_presence_read_unavailable')
    return stamps


def register(host):
    @host.app.after_request
    def track_partner_access(response):
        if (request.method != 'GET' or response.status_code != 200
                or response.mimetype != 'text/html' or not request.path.startswith('/admin/')
                or not host._is_external_partner_session() or session.get('assist_partner_id')):
            return response
        now = dt.datetime.now(dt.timezone.utc)
        last = host._parse_iso_datetime(session.get('partner_presence_at'))
        if last and (now.replace(tzinfo=None) - last).total_seconds() < 60:
            return response
        try:
            auth = host._load_partner_auth_data()
            pid,uid = session.get('partner_id'),session.get('user_id')
            valid_user = any(u.get('id') == uid and u.get('partner_id') == pid and u.get('active', True) for u in auth.get('users', []))
            valid_partner = any(p.get('id') == pid and p.get('status') in {'active','trial'} for p in auth.get('partners', []))
            if valid_user and valid_partner:
                stamp = now.isoformat().replace('+00:00','Z')
                record(host, pid, uid, stamp)
                session['partner_presence_at'] = stamp
        except (OSError, sqlite3.Error, host.PartnerPostgresError):
            host.app.logger.warning('partner_presence_write_unavailable')
        return response
