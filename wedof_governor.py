"""Compteur et verrou WEDOF centralisés sur le stockage persistant."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import tempfile
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo


PARIS_TZ = ZoneInfo("Europe/Paris")
_TRUE_VALUES = {"1", "true", "yes", "on"}
_ORIGIN_RE = re.compile(r"[^a-z0-9_.-]+")


class WedofGovernorError(RuntimeError):
    """Erreur technique du compteur central."""


class WedofQuotaExceeded(WedofGovernorError):
    """Une réservation dépasserait au moins un plafond."""

    def __init__(self, snapshot: Dict[str, Any]):
        super().__init__("Le plafond de requêtes WEDOF est atteint.")
        self.snapshot = snapshot


def governor_enabled() -> bool:
    value = os.getenv("WEDOF_GOVERNOR_ENABLED")
    if value is not None:
        return value.strip().casefold() in _TRUE_VALUES
    return bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
        return value
    except (TypeError, ValueError):
        return default


def configured_limits() -> Dict[str, int]:
    return {
        "hour": _bounded_int("WEDOF_REQUEST_LIMIT_PER_HOUR", 100, 1, 100000),
        "day": _bounded_int("WEDOF_REQUEST_LIMIT_PER_DAY", 500, 1, 1000000),
        "month": _bounded_int("WEDOF_REQUEST_LIMIT_PER_MONTH", 15000, 1, 10000000),
    }


def _database_path() -> str:
    configured = (os.getenv("WEDOF_GOVERNOR_DB_PATH") or "").strip()
    if configured:
        return configured
    for root in ("/var/data", "/data"):
        if os.path.isdir(root) and os.access(root, os.W_OK):
            return os.path.join(root, "wedof_governor.sqlite3")
    return os.path.join(tempfile.gettempdir(), "integrale-wedof-governor.sqlite3")


def _connect() -> sqlite3.Connection:
    path = _database_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS wedof_request_buckets (
            period TEXT NOT NULL,
            bucket TEXT NOT NULL,
            origin TEXT NOT NULL,
            request_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (period, bucket, origin)
        );
        CREATE TABLE IF NOT EXISTS wedof_request_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            requested_at TEXT NOT NULL,
            origin TEXT NOT NULL,
            operation TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wedof_events_requested_at
            ON wedof_request_events(requested_at);
        CREATE TABLE IF NOT EXISTS wedof_governor_leases (
            lease_name TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            lease_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    connection.commit()
    return connection


def _current(now: Optional[dt.datetime] = None) -> dt.datetime:
    value = now or dt.datetime.now(PARIS_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=PARIS_TZ)
    return value.astimezone(PARIS_TZ)


def _buckets(now: dt.datetime) -> Dict[str, str]:
    return {
        "hour": now.strftime("%Y-%m-%dT%H"),
        "day": now.strftime("%Y-%m-%d"),
        "month": now.strftime("%Y-%m"),
    }


def _origin(value: str) -> str:
    cleaned = _ORIGIN_RE.sub("-", str(value or "unknown").strip().casefold())
    return (cleaned.strip("-") or "unknown")[:80]


def _snapshot_with_connection(
    db: sqlite3.Connection, now: dt.datetime,
) -> Dict[str, Any]:
    limits = configured_limits()
    bucket_keys = _buckets(now)
    periods: Dict[str, Any] = {}
    for period, bucket in bucket_keys.items():
        rows = db.execute(
            "SELECT origin, request_count FROM wedof_request_buckets "
            "WHERE period=? AND bucket=? ORDER BY origin",
            (period, bucket),
        ).fetchall()
        by_origin = {
            str(row["origin"]): int(row["request_count"] or 0) for row in rows
        }
        used = sum(by_origin.values())
        periods[period] = {
            "bucket": bucket,
            "used": used,
            "limit": limits[period],
            "remaining": max(0, limits[period] - used),
            "by_origin": by_origin,
        }
    return {
        "enabled": governor_enabled(),
        "timezone": "Europe/Paris",
        "periods": periods,
    }


def quota_snapshot(*, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    current = _current(now)
    with _connect() as db:
        return _snapshot_with_connection(db, current)


def reserve_request(
    *, origin: str, operation: str, method: str, path: str,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Compte une tentative avant son envoi et bloque tout dépassement."""
    if not governor_enabled():
        return {"ok": True, "enabled": False}
    current = _current(now)
    normalized_origin = _origin(origin)
    safe_operation = str(operation or "wedof_request")[:80]
    safe_method = str(method or "GET").upper()[:10]
    safe_path = str(path or "")[:160]
    limits = configured_limits()
    bucket_keys = _buckets(current)
    timestamp = current.isoformat(timespec="seconds")
    db = _connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        snapshot = _snapshot_with_connection(db, current)
        if any(
            snapshot["periods"][period]["used"] + 1 > limits[period]
            for period in ("hour", "day", "month")
        ):
            db.rollback()
            raise WedofQuotaExceeded(snapshot)
        for period, bucket in bucket_keys.items():
            db.execute("""
                INSERT INTO wedof_request_buckets
                    (period, bucket, origin, request_count, updated_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(period, bucket, origin) DO UPDATE SET
                    request_count=request_count + 1,
                    updated_at=excluded.updated_at
            """, (period, bucket, normalized_origin, timestamp))
        db.execute("""
            INSERT INTO wedof_request_events
                (requested_at, origin, operation, method, path)
            VALUES (?, ?, ?, ?, ?)
        """, (
            timestamp, normalized_origin, safe_operation, safe_method, safe_path,
        ))
        cutoff = (current - dt.timedelta(days=35)).isoformat(timespec="seconds")
        db.execute(
            "DELETE FROM wedof_request_events WHERE requested_at < ?", (cutoff,),
        )
        db.commit()
        updated = _snapshot_with_connection(db, current)
        return {"ok": True, **updated}
    except WedofQuotaExceeded:
        raise
    except sqlite3.Error as exc:
        db.rollback()
        raise WedofGovernorError("Le compteur WEDOF central est indisponible.") from exc
    finally:
        db.close()


def acquire_lease(
    name: str, *, owner: str, ttl_seconds: int = 3600,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    if not governor_enabled():
        return {"ok": True, "enabled": False, "acquired": True, "token": ""}
    lease_name = str(name or "").strip()[:80]
    if not lease_name:
        raise WedofGovernorError("Nom de verrou WEDOF manquant.")
    current = _current(now)
    ttl = max(30, min(int(ttl_seconds), 86400))
    expires = current + dt.timedelta(seconds=ttl)
    timestamp = current.isoformat(timespec="seconds")
    db = _connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT owner, lease_token, expires_at FROM wedof_governor_leases "
            "WHERE lease_name=?",
            (lease_name,),
        ).fetchone()
        if existing:
            try:
                active_until = dt.datetime.fromisoformat(existing["expires_at"])
            except (TypeError, ValueError):
                active_until = current - dt.timedelta(seconds=1)
            if active_until > current:
                db.rollback()
                return {
                    "ok": True, "enabled": True, "acquired": False,
                    "owner": str(existing["owner"]),
                    "expires_at": str(existing["expires_at"]),
                }
        token = secrets.token_urlsafe(24)
        db.execute("""
            INSERT INTO wedof_governor_leases
                (lease_name, owner, lease_token, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lease_name) DO UPDATE SET
                owner=excluded.owner,
                lease_token=excluded.lease_token,
                expires_at=excluded.expires_at,
                updated_at=excluded.updated_at
        """, (
            lease_name, str(owner or "unknown")[:160], token,
            expires.isoformat(timespec="seconds"), timestamp,
        ))
        db.commit()
        return {
            "ok": True, "enabled": True, "acquired": True,
            "token": token, "expires_at": expires.isoformat(timespec="seconds"),
        }
    except sqlite3.Error as exc:
        db.rollback()
        raise WedofGovernorError("Le verrou WEDOF central est indisponible.") from exc
    finally:
        db.close()


def release_lease(name: str, token: str) -> bool:
    if not governor_enabled() or not token:
        return True
    try:
        with _connect() as db:
            cursor = db.execute(
                "DELETE FROM wedof_governor_leases "
                "WHERE lease_name=? AND lease_token=?",
                (str(name or "")[:80], str(token)[:160]),
            )
            return cursor.rowcount == 1
    except sqlite3.Error as exc:
        raise WedofGovernorError("Le verrou WEDOF central est indisponible.") from exc


def governor_auth_token() -> str:
    secret = (
        os.getenv("WEDOF_GOVERNOR_SECRET")
        or os.getenv("WEDOF_API_KEY")
        or ""
    ).strip()
    if not secret:
        return ""
    return hmac.new(
        secret.encode("utf-8"),
        b"integrale-academy-wedof-governor-v1",
        hashlib.sha256,
    ).hexdigest()


def valid_governor_token(value: str) -> bool:
    expected = governor_auth_token()
    return bool(expected and value) and hmac.compare_digest(expected, str(value))
