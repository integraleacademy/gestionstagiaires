"""Small, durable transactions for formative UV questionnaire state.

Only the three questionnaire fields belong here. Administrative data and
authorization stay with the application. A row, even when its state is empty,
is authoritative: legacy JSON is imported only on the very first mutation.
"""

from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from typing import Any, Callable, Mapping, TypeVar


UV_FIELDS = (
    "uv_questionnaire_attempts",
    "uv_questionnaires",
    "uv_questionnaire_resets",
)
_FIELDS = frozenset(UV_FIELDS)
_BUSY_TIMEOUT_SECONDS = 15
_SCHEMA_LOCK = threading.Lock()
_INITIALIZED_DATABASES: dict[str, tuple[int, int]] = {}
_Result = TypeVar("_Result")


def _key_values(key: tuple[str, str, str]) -> tuple[str, str, str]:
    if (not isinstance(key, tuple) or len(key) != 3
            or any(not isinstance(value, str) or not value.strip() for value in key)):
        raise ValueError("UV state requires non-empty partner, session and trainee identifiers.")
    return key


def _encode_state(state: Mapping[str, Any]) -> str:
    if not isinstance(state, Mapping) or set(state) - _FIELDS:
        raise ValueError("Only UV questionnaire fields may be stored here.")
    return json.dumps(dict(state), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _decode_state(encoded: str) -> dict[str, Any]:
    state = json.loads(encoded)
    # Invalid/corrupt state must fail visibly, never fall back to older JSON.
    if not isinstance(state, dict) or set(state) - _FIELDS:
        raise ValueError("Stored UV questionnaire state is invalid.")
    return state


class UVQuestionnaireStore:
    """SQLite state isolated by partner, session and trainee.

    ``mutator`` must only change its supplied state and compute its result.
    It must not load administrative data, do network I/O or obtain another
    storage lock while this short SQLite transaction is held.
    """

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path), timeout=_BUSY_TIMEOUT_SECONDS,
            isolation_level=None,
        )
        try:
            connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_SECONDS * 1000}")
            connection.execute("PRAGMA foreign_keys = ON")
            # Unlike journal_mode, synchronous is a per-connection setting.
            # A response is acknowledged only after a durable WAL commit.
            connection.execute("PRAGMA synchronous = FULL")
        except BaseException:
            connection.close()
            raise
        return connection

    def _identity(self) -> tuple[int, int] | None:
        try:
            stat = self.database_path.stat()
        except FileNotFoundError:
            return None
        return stat.st_dev, stat.st_ino

    def _ensure_schema(self) -> None:
        path = str(self.database_path)
        with _SCHEMA_LOCK:
            identity = self._identity()
            if identity is not None and _INITIALIZED_DATABASES.get(path) == identity:
                return
            deadline = time.monotonic() + _BUSY_TIMEOUT_SECONDS
            while True:
                try:
                    with closing(self._connect()) as connection:
                        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                        if str(mode).lower() != "wal":
                            raise RuntimeError("UV questionnaire storage requires SQLite WAL mode.")
                        connection.execute(
                            """CREATE TABLE IF NOT EXISTS uv_questionnaire_state (
                                partner_id TEXT NOT NULL,
                                session_id TEXT NOT NULL,
                                trainee_id TEXT NOT NULL,
                                state_json TEXT NOT NULL,
                                PRIMARY KEY (partner_id, session_id, trainee_id)
                            ) WITHOUT ROWID"""
                        )
                        connection.execute(
                            """CREATE TABLE IF NOT EXISTS uv_questionnaire_alias (
                                partner_id TEXT NOT NULL,
                                session_id TEXT NOT NULL,
                                trainee_id TEXT NOT NULL,
                                canonical_partner_id TEXT NOT NULL,
                                canonical_session_id TEXT NOT NULL,
                                canonical_trainee_id TEXT NOT NULL,
                                PRIMARY KEY (partner_id, session_id, trainee_id),
                                FOREIGN KEY (canonical_partner_id, canonical_session_id, canonical_trainee_id)
                                  REFERENCES uv_questionnaire_state (partner_id, session_id, trainee_id)
                            ) WITHOUT ROWID"""
                        )
                    identity = self._identity()
                    if identity is not None:
                        _INITIALIZED_DATABASES[path] = identity
                    return
                except sqlite3.OperationalError as exc:
                    # Concurrent first starts in other processes may briefly
                    # contend while changing journal mode. Only lock errors
                    # are retried; disk/schema errors must remain visible.
                    code = getattr(exc, "sqlite_errorcode", 0)
                    if ((code & 0xFF) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                            or time.monotonic() >= deadline):
                        raise
                    time.sleep(min(0.025, max(0, deadline - time.monotonic())))

    @staticmethod
    def _state_row(connection: sqlite3.Connection, key: tuple[str, str, str]):
        return connection.execute(
            """SELECT state_json FROM uv_questionnaire_state
               WHERE partner_id = ? AND session_id = ? AND trainee_id = ?""",
            key,
        ).fetchone()

    @classmethod
    def _resolve_key(cls, connection: sqlite3.Connection, key: tuple[str, str, str]):
        """Resolve server-created transfer aliases in the caller's transaction."""
        visited = set()
        for _ in range(64):
            if key in visited:
                raise ValueError("UV questionnaire transfer aliases contain a cycle.")
            visited.add(key)
            alias = connection.execute(
                """SELECT canonical_partner_id, canonical_session_id, canonical_trainee_id
                   FROM uv_questionnaire_alias
                   WHERE partner_id = ? AND session_id = ? AND trainee_id = ?""",
                key,
            ).fetchone()
            if alias is None:
                return key
            if cls._state_row(connection, key) is not None:
                raise ValueError("UV questionnaire identity has both an alias and independent state.")
            key = _key_values(tuple(alias))
        raise ValueError("UV questionnaire transfer alias chain is too long.")

    def read(self, key: tuple[str, str, str]) -> dict[str, Any] | None:
        """Return an independent snapshot; ``None`` means never migrated."""
        values = _key_values(key)
        with closing(self._connect()) as connection:
            # Alias resolution and the state read must see the same snapshot
            # if an authorized transfer commits between the two queries.
            connection.execute("BEGIN")
            canonical = self._resolve_key(connection, values)
            row = self._state_row(connection, canonical)
            if canonical != values and row is None:
                raise ValueError("UV questionnaire transfer alias has no canonical state.")
            connection.commit()
        return None if row is None else _decode_state(row[0])

    def mutate(
        self,
        key: tuple[str, str, str],
        seed: Mapping[str, Any],
        mutator: Callable[[dict[str, Any]], _Result],
    ) -> _Result:
        """Atomically mutate one learner's state and return the callback result.

        ``seed`` is a legacy snapshot used only when the row does not exist.
        Keeping empty rows prevents a later stale seed resurrecting reset work.
        Neither the seed nor objects retained by the caller alias stored state.
        """
        values = _key_values(key)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                canonical = self._resolve_key(connection, values)
                row = self._state_row(connection, canonical)
                if canonical != values and row is None:
                    raise ValueError("UV questionnaire transfer alias has no canonical state.")
                if row is None:
                    before = _encode_state(seed)
                    state = _decode_state(before)
                else:
                    state = _decode_state(row[0])
                    before = _encode_state(state)
                result = mutator(state)
                after = _encode_state(state)
                if row is None:
                    connection.execute(
                        """INSERT INTO uv_questionnaire_state
                           (partner_id, session_id, trainee_id, state_json)
                           VALUES (?, ?, ?, ?)""",
                        (*canonical, after),
                    )
                elif after != before:
                    connection.execute(
                        """UPDATE uv_questionnaire_state SET state_json = ?
                           WHERE partner_id = ? AND session_id = ? AND trainee_id = ?""",
                        (after, *canonical),
                    )
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def transfer(
        self,
        source_key: tuple[str, str, str],
        target_key: tuple[str, str, str],
        seed: Mapping[str, Any],
    ) -> None:
        """Link an authorized destination to the same state without moving it.

        The application must authorize both registrations before calling this
        method. A request already using the old identity and a request using
        the new one keep mutating the very same canonical row. If the later
        administrative save fails, the source remains intact and accessible.
        """
        source = _key_values(source_key)
        target = _key_values(target_key)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                canonical = self._resolve_key(connection, source)
                source_row = self._state_row(connection, canonical)
                if canonical != source and source_row is None:
                    raise ValueError("UV questionnaire transfer alias has no canonical state.")
                destination = self._resolve_key(connection, target)
                if destination != canonical and (
                    destination != target or self._state_row(connection, target) is not None
                ):
                    raise ValueError("The destination already owns different UV questionnaire state.")
                if source_row is None:
                    connection.execute(
                        """INSERT INTO uv_questionnaire_state
                           (partner_id, session_id, trainee_id, state_json)
                           VALUES (?, ?, ?, ?)""",
                        (*canonical, _encode_state(seed)),
                    )
                if destination != canonical:
                    connection.execute(
                        """INSERT INTO uv_questionnaire_alias
                           (partner_id, session_id, trainee_id,
                            canonical_partner_id, canonical_session_id, canonical_trainee_id)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (*target, *canonical),
                    )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def backup_to(self, destination: str | Path) -> Path:
        """Atomically publish a standalone snapshot including committed WAL data.

        Run outside ``mutate``/``transfer`` callbacks. SQLite's online backup
        API takes a consistent snapshot while other connections remain usable;
        copying only the live main file would omit commits still in its WAL.
        """
        destination = Path(destination).resolve()
        if (destination == self.database_path or
                (destination.exists() and os.path.samefile(destination, self.database_path))):
            raise ValueError("The UV backup destination must differ from the live database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent, prefix=destination.name + ".", suffix=".tmp",
        )
        os.close(descriptor)
        try:
            with closing(self._connect()) as source, closing(sqlite3.connect(temporary_name)) as target:
                target.execute("PRAGMA synchronous = FULL")
                source.backup(target, pages=256, sleep=0.025)
                # Publish one complete file, never a snapshot requiring sidecars.
                target.execute("PRAGMA journal_mode = DELETE")
            with open(temporary_name, "rb") as snapshot:
                os.fsync(snapshot.fileno())
            os.replace(temporary_name, destination)
            directory = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return destination
        finally:
            for path in (temporary_name, temporary_name + "-wal", temporary_name + "-shm"):
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
