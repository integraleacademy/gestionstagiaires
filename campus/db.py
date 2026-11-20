"""Connections for the three pedagogical stores shared by Campus and Gestion.

Local installations retain their existing SQLite files. Production selects
Postgres explicitly. Each former SQLite database has its own Postgres schema.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import threading


SCHEMAS = {
    "tracking.sqlite3": "campus_tracking",
    "production_ai.sqlite3": "campus_ai",
    "uv-questionnaires.sqlite3": "campus_uv",
}
_pools = {}
_pool_lock = threading.Lock()


def enabled(path=None):
    if path is not None and Path(path).name not in SCHEMAS:
        return False
    return os.environ.get("CAMPUS_STORAGE", "") == "postgres"


def exists(path):
    return enabled(path) or Path(path).is_file()


def pool():
    from psycopg_pool import ConnectionPool
    dsn = os.environ.get("CAMPUS_DATABASE_URL")
    if not dsn:
        raise RuntimeError("La base pédagogique n’est pas configurée.")
    key = (os.getpid(), dsn)
    with _pool_lock:
        if key not in _pools:
            _pools[key] = ConnectionPool(
                dsn, min_size=0, max_size=int(os.environ.get("CAMPUS_POOL_SIZE", "8")),
                timeout=10, kwargs={"connect_timeout": 5, "application_name": "integrale-campus"},
                open=True,
            )
        return _pools[key]


class Record(tuple):
    """DB-API row supporting both positional and named access like sqlite3.Row."""
    def __new__(cls, values, fields):
        obj = super().__new__(cls, values)
        obj.fields = fields
        return obj

    def keys(self):
        return self.fields.keys()

    def __getitem__(self, key):
        return super().__getitem__(self.fields[key] if isinstance(key, str) else key)


def _rows(cursor):
    fields = {column.name: i for i, column in enumerate(cursor.description or ())}
    return lambda values: Record(values, fields)


class PgConnection:
    """Small DB-API bridge for the existing parameterized learning queries."""
    row_factory = None  # Both access styles are provided by Record.

    def __init__(self, path, readonly=False):
        self.pool = pool()
        self.raw = self.pool.getconn()
        self.schema = SCHEMAS[Path(path).name]
        self.readonly = readonly
        self.closed = False
        self._configure = True

    def _cursor(self):
        from psycopg import sql
        if self._configure:
            if self.readonly:
                self.raw.execute("SET TRANSACTION READ ONLY")
            self.raw.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
            self._configure = False
        return self.raw.cursor(row_factory=_rows)

    def execute(self, query, params=()):
        statement = query.strip()
        cursor = self._cursor()
        # These database runtime settings are provided by Postgres itself.
        if statement.upper() == "BEGIN":
            return cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        if statement.upper() == "BEGIN IMMEDIATE":
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (self.schema,))
            return cursor
        if match := re.fullmatch(r"PRAGMA table_info\((\w+)\)", statement, re.I):
            return cursor.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                (self.schema, match[1]),
            )
        if re.fullmatch(r"PRAGMA journal_mode\s*=\s*WAL", statement, re.I):
            return cursor
        if re.fullmatch(r"PRAGMA (?:busy_timeout\s*=\s*\d+|foreign_keys\s*=\s*ON|"
                        r"synchronous\s*=\s*(?:NORMAL|FULL)|query_only\s*=\s*ON)", statement, re.I):
            return cursor
        if "sqlite_master" in statement:
            statement = statement.replace("sqlite_master", (
                "(SELECT tablename AS name, 'table' AS type FROM pg_tables "
                "WHERE schemaname=current_schema()) AS available_tables"))
        if statement.upper().startswith(("CREATE TABLE", "ALTER TABLE")):
            statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
            statement = re.sub(r"\bREAL\b", "DOUBLE PRECISION", statement, flags=re.I)
            statement = statement.replace(" WITHOUT ROWID", "")
        if params:
            statement = statement.replace("%", "%%").replace("?", "%s")
        return cursor.execute(statement, tuple(params) if params else None)

    def executescript(self, script):
        # Only internal DDL batches call this method.
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.raw.commit()
        self._configure = True

    def rollback(self):
        self.raw.rollback()
        self._configure = True

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.raw.rollback()
            finally:
                self.pool.putconn(self.raw)

    def __enter__(self):
        return self

    def __exit__(self, typ, value, trace):
        try:
            if typ is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


def connect(path, *, timeout=15, readonly=False, **options):
    path = Path(path)
    if enabled(path):
        return PgConnection(path, readonly)
    if readonly:
        return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout, **options)
    return sqlite3.connect(str(path), timeout=timeout, **options)


def initialize_schemas():
    from psycopg import sql
    with pool().connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext('campus.schema'))")
        for name in (*SCHEMAS.values(), "campus_directory"):
            db.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(name)))
