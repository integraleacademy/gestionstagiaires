"""Single-use, browser-bound transfer from an authenticated trainee session."""
import re
import secrets
from urllib.parse import quote

from campus import db, directory


def initialize():
    with db.pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.schema'))")
        conn.execute("""CREATE TABLE IF NOT EXISTS campus_directory.login_handoffs (
            code_hash TEXT PRIMARY KEY, state_hash TEXT NOT NULL, learner_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS campus_handoff_expiry ON campus_directory.login_handoffs(expires_at)")


def valid_nonce(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", value))


def destination(token, target):
    home = "/espace/" + quote(token, safe="")
    target = str(target or "")
    path = target.partition("?")[0]
    allowed = (path in {home, home + "/elearning"} or
               path.startswith((home + "/elearning/", home + "/questionnaires-uv/")))
    if (allowed and ".." not in path.split("/") and "%" not in path and
            "#" not in target and "\\" not in target and not any(ord(c) < 32 for c in target)):
        return target
    return home


def issue(token, state):
    if not valid_nonce(state):
        raise ValueError("Échange de connexion invalide.")
    code = secrets.token_urlsafe(32)
    with db.pool().connection() as conn:
        conn.execute("DELETE FROM campus_directory.login_handoffs WHERE expires_at <= now()")
        conn.execute("""INSERT INTO campus_directory.login_handoffs VALUES (%s,%s,%s,now()+interval '90 seconds')""",
                     (directory.digest(code), directory.digest(state), directory.digest(token)))
    return code


def consume(token, state, code):
    if not valid_nonce(state) or not valid_nonce(code):
        return False
    with db.pool().connection() as conn:
        return bool(conn.execute("""DELETE FROM campus_directory.login_handoffs
            WHERE code_hash=%s AND state_hash=%s AND learner_hash=%s AND expires_at>now()
            RETURNING code_hash""", (directory.digest(code), directory.digest(state), directory.digest(token))).fetchone())
