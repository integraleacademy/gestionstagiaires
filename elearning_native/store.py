from __future__ import annotations

import contextlib
import datetime as dt
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from .videos import videos_complete


HEARTBEAT_MAX_CREDIT_SECONDS = 20.0
ACTIVE_SESSION_STALE_SECONDS = 45.0
IDLE_TIMEOUT_SECONDS = 300.0

_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_DATABASES: set[str] = set()


class TrackingError(ValueError):
    """Raised when a learner tracking operation is invalid."""


def _utc_iso(epoch: Optional[float] = None) -> str:
    instant = dt.datetime.fromtimestamp(epoch if epoch is not None else time.time(), tz=dt.timezone.utc)
    return instant.isoformat().replace("+00:00", "Z")


def _json_list(raw: Any) -> List[Any]:
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(raw: Any) -> Dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class NativeElearningStore:
    """SQLite-backed progress and server-authoritative active-time store.

    The historical application stores administrative data in ``data.json``.
    Heartbeats deliberately live in this separate transactional database so a
    learner ping never rewrites the large administrative JSON document.
    """

    def __init__(self, database_path: os.PathLike[str] | str) -> None:
        self.database_path = Path(database_path).resolve()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    def _ensure_schema(self) -> None:
        key = str(self.database_path)
        with _INITIALIZE_LOCK:
            if key in _INITIALIZED_DATABASES and self.database_path.is_file():
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS learner_course_progress (
                        session_id TEXT NOT NULL,
                        trainee_id TEXT NOT NULL,
                        course_id TEXT NOT NULL,
                        course_version TEXT NOT NULL,
                        current_activity_id TEXT NOT NULL DEFAULT '',
                        completed_json TEXT NOT NULL DEFAULT '[]',
                        answers_json TEXT NOT NULL DEFAULT '{}',
                        active_seconds REAL NOT NULL DEFAULT 0,
                        score_percent REAL NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'not_started',
                        started_at TEXT,
                        updated_at TEXT,
                        completed_at TEXT,
                        active_tracking_session_id TEXT,
                        active_tracking_seen_epoch REAL,
                        PRIMARY KEY (session_id, trainee_id, course_id, course_version)
                    );

                    CREATE TABLE IF NOT EXISTS tracking_sessions (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        trainee_id TEXT NOT NULL,
                        course_id TEXT NOT NULL,
                        course_version TEXT NOT NULL,
                        tab_id TEXT NOT NULL,
                        current_activity_id TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL,
                        last_seen_epoch REAL NOT NULL,
                        was_active INTEGER NOT NULL DEFAULT 0,
                        was_duplicate INTEGER NOT NULL DEFAULT 0,
                        credited_seconds REAL NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'open',
                        ended_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS tracking_sessions_learner_idx
                    ON tracking_sessions (session_id, trainee_id, course_id, course_version);

                    CREATE TABLE IF NOT EXISTS tracking_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tracking_session_id TEXT,
                        session_id TEXT NOT NULL,
                        trainee_id TEXT NOT NULL,
                        course_id TEXT NOT NULL,
                        course_version TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        activity_id TEXT NOT NULL DEFAULT '',
                        event_at TEXT NOT NULL,
                        credited_seconds REAL NOT NULL DEFAULT 0,
                        details_json TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS tracking_events_learner_idx
                    ON tracking_events (session_id, trainee_id, course_id, course_version, event_at);
                    """
                )
                # Serialize the additive migration across separate Gunicorn workers.
                connection.execute("BEGIN IMMEDIATE")
                columns = {row["name"] for row in connection.execute("PRAGMA table_info(tracking_sessions)")}
                if "active_until_epoch" not in columns:
                    connection.execute("ALTER TABLE tracking_sessions ADD COLUMN active_until_epoch REAL NOT NULL DEFAULT 0")
                if "video_samples_json" not in columns:
                    connection.execute("ALTER TABLE tracking_sessions ADD COLUMN video_samples_json TEXT NOT NULL DEFAULT '{}'")
                progress_columns = {row["name"] for row in connection.execute("PRAGMA table_info(learner_course_progress)")}
                if "video_progress_json" not in progress_columns:
                    connection.execute("ALTER TABLE learner_course_progress ADD COLUMN video_progress_json TEXT NOT NULL DEFAULT '{}'")
            _INITIALIZED_DATABASES.add(key)

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _key_values(access: Mapping[str, Any]) -> tuple[str, str, str, str]:
        values = tuple(
            str(access.get(name) or "").strip()
            for name in ("session_id", "trainee_id", "course_id", "course_version")
        )
        if not all(values):
            raise TrackingError("Contexte apprenant incomplet.")
        return values  # type: ignore[return-value]

    @staticmethod
    def _ensure_progress_row(
        connection: sqlite3.Connection,
        access: Mapping[str, Any],
        *,
        now_iso: str,
        current_activity_id: str = "",
    ) -> None:
        session_id, trainee_id, course_id, course_version = NativeElearningStore._key_values(access)
        connection.execute(
            """
            INSERT INTO learner_course_progress (
                session_id, trainee_id, course_id, course_version,
                current_activity_id, status, started_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?)
            ON CONFLICT(session_id, trainee_id, course_id, course_version) DO NOTHING
            """,
            (
                session_id,
                trainee_id,
                course_id,
                course_version,
                current_activity_id,
                now_iso,
                now_iso,
            ),
        )

    @staticmethod
    def _progress_row(connection: sqlite3.Connection, access: Mapping[str, Any]) -> sqlite3.Row:
        key = NativeElearningStore._key_values(access)
        row = connection.execute(
            """
            SELECT * FROM learner_course_progress
            WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?
            """,
            key,
        ).fetchone()
        if row is None:
            raise TrackingError("Progression apprenant introuvable.")
        return row

    @staticmethod
    def _serialize_progress(
        row: sqlite3.Row,
        *,
        activity_order: Sequence[str] = (),
        scored_activity_ids: Sequence[str] = (),
    ) -> Dict[str, Any]:
        completed = [str(value) for value in _json_list(row["completed_json"])]
        answers = _json_dict(row["answers_json"])
        total = len(activity_order)
        progress_percent = round((len(set(completed)) / total) * 100, 2) if total else 0.0
        correct_count = sum(
            1
            for activity_id in scored_activity_ids
            if isinstance(answers.get(activity_id), dict) and answers[activity_id].get("correct") is True
        )
        return {
            "session_id": row["session_id"],
            "trainee_id": row["trainee_id"],
            "course_id": row["course_id"],
            "course_version": row["course_version"],
            "current_activity_id": row["current_activity_id"],
            "completed_activity_ids": completed,
            "answers": answers,
            "video_progress": _json_dict(row["video_progress_json"]),
            "active_seconds": math.floor(float(row["active_seconds"] or 0) * 100) / 100,
            "score_percent": round(float(row["score_percent"] or 0), 2),
            "correct_answers": correct_count,
            "scored_activities": len(scored_activity_ids),
            "progress_percent": progress_percent,
            "status": row["status"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        access: Mapping[str, Any],
        event_type: str,
        *,
        tracking_session_id: str = "",
        activity_id: str = "",
        at: Optional[str] = None,
        credited_seconds: float = 0.0,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        session_id, trainee_id, course_id, course_version = NativeElearningStore._key_values(access)
        connection.execute(
            """
            INSERT INTO tracking_events (
                tracking_session_id, session_id, trainee_id, course_id, course_version,
                event_type, activity_id, event_at, credited_seconds, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tracking_session_id or None,
                session_id,
                trainee_id,
                course_id,
                course_version,
                event_type,
                activity_id,
                at or _utc_iso(),
                float(credited_seconds or 0),
                json.dumps(dict(details or {}), ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def get_progress(
        self,
        access: Mapping[str, Any],
        *,
        activity_order: Sequence[str] = (),
        scored_activity_ids: Sequence[str] = (),
        mastery_score: float = 80,
        required_seconds: int = 0,
        video_requirements: Optional[Mapping[str, Mapping[str, float]]] = None,
    ) -> Dict[str, Any]:
        now_iso = _utc_iso()
        with self._transaction() as connection:
            self._ensure_progress_row(
                connection,
                access,
                now_iso=now_iso,
                current_activity_id=activity_order[0] if activity_order else "",
            )
            row = self._progress_row(connection, access)
            if activity_order:
                completion = self._completion_values(
                    _json_list(row["completed_json"]), _json_dict(row["answers_json"]),
                    activity_order=activity_order, scored_activity_ids=scored_activity_ids,
                    mastery_score=mastery_score, active_seconds=float(row["active_seconds"] or 0),
                    required_seconds=required_seconds,
                    video_requirements=video_requirements,
                    video_progress=_json_dict(row["video_progress_json"]),
                )
                completed_at = (row["completed_at"] or now_iso) if completion["all_complete"] else None
                if row["status"] != completion["status"] or row["completed_at"] != completed_at or row["score_percent"] != completion["score"]:
                    connection.execute(
                        """UPDATE learner_course_progress SET status = ?, score_percent = ?, completed_at = ?
                           WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?""",
                        (completion["status"], completion["score"], completed_at, *self._key_values(access)),
                    )
                    if completion["all_complete"] and not row["completed_at"]:
                        self._event(connection, access, "course_completed", at=now_iso,
                                    details={"status": completion["status"], "required_seconds": required_seconds})
                    row = self._progress_row(connection, access)
            return self._serialize_progress(
                row,
                activity_order=activity_order,
                scored_activity_ids=scored_activity_ids,
            )

    def start_tracking(
        self,
        access: Mapping[str, Any],
        *,
        tab_id: str,
        activity_id: str,
        now_epoch: Optional[float] = None,
    ) -> Dict[str, Any]:
        if not str(tab_id or "").strip():
            raise TrackingError("Identifiant d’onglet manquant.")
        epoch = float(now_epoch if now_epoch is not None else time.time())
        now_iso = _utc_iso(epoch)
        tracking_id = uuid.uuid4().hex
        session_id, trainee_id, course_id, course_version = self._key_values(access)
        with self._transaction() as connection:
            self._ensure_progress_row(
                connection,
                access,
                now_iso=now_iso,
                current_activity_id=activity_id,
            )
            connection.execute(
                """
                INSERT INTO tracking_sessions (
                    id, session_id, trainee_id, course_id, course_version, tab_id,
                    current_activity_id, created_at, last_seen_at, last_seen_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tracking_id,
                    session_id,
                    trainee_id,
                    course_id,
                    course_version,
                    str(tab_id)[:128],
                    str(activity_id or "")[:128],
                    now_iso,
                    now_iso,
                    epoch,
                ),
            )
            connection.execute(
                """
                UPDATE learner_course_progress
                SET current_activity_id = CASE WHEN ? <> '' THEN ? ELSE current_activity_id END,
                    status = CASE WHEN status = 'not_started' THEN 'in_progress' ELSE status END,
                    updated_at = ?
                WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?
                """,
                (activity_id, activity_id, now_iso, session_id, trainee_id, course_id, course_version),
            )
            self._event(
                connection,
                access,
                "session_started",
                tracking_session_id=tracking_id,
                activity_id=activity_id,
                at=now_iso,
                details={"tab_id": str(tab_id)[:128]},
            )
        return {"tracking_session_id": tracking_id, "server_time": now_iso}

    def heartbeat(
        self,
        access: Mapping[str, Any],
        tracking_session_id: str,
        *,
        activity_id: str,
        visible: bool,
        focused: bool,
        recent_activity: bool,
        media_playing: bool,
        interaction_age_seconds: Optional[float] = None,
        now_epoch: Optional[float] = None,
        video_requirements: Optional[Mapping[str, float]] = None,
        video_samples: Any = None,
    ) -> Dict[str, Any]:
        epoch = float(now_epoch if now_epoch is not None else time.time())
        now_iso = _utc_iso(epoch)
        age = 0.0 if interaction_age_seconds is None else interaction_age_seconds
        if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or age < 0:
            raise TrackingError("Durée d’inactivité invalide. Rechargez la page.")
        requested_active = bool(visible and recent_activity and age < IDLE_TIMEOUT_SECONDS and (focused or media_playing))
        key = self._key_values(access)
        with self._transaction() as connection:
            tracking = connection.execute(
                "SELECT * FROM tracking_sessions WHERE id = ?",
                (tracking_session_id,),
            ).fetchone()
            if tracking is None or tuple(tracking[name] for name in ("session_id", "trainee_id", "course_id", "course_version")) != key:
                raise TrackingError("Session de suivi invalide.")
            if tracking["status"] == "ended":
                progress = self._progress_row(connection, access)
                return {
                    "ended": True,
                    "duplicate": False,
                    "active": False,
                    "credited_seconds": 0.0,
                    "server_time": now_iso,
                    "progress": self._serialize_progress(progress),
                }

            progress = self._progress_row(connection, access)
            owner_id = str(progress["active_tracking_session_id"] or "")
            owner_seen = float(progress["active_tracking_seen_epoch"] or 0)
            owner_is_stale = not owner_id or epoch - owner_seen > ACTIVE_SESSION_STALE_SECONDS
            owns_slot = owner_id == tracking_session_id
            duplicate = bool(requested_active and not owns_slot and not owner_is_stale)
            # One learner must not earn time on two modules at once (e.g. two
            # playing videos). This check shares the same SQLite transaction.
            other_module = connection.execute(
                """SELECT 1 FROM learner_course_progress
                   WHERE session_id = ? AND trainee_id = ?
                     AND NOT (course_id = ? AND course_version = ?)
                     AND active_tracking_session_id IS NOT NULL
                     AND active_tracking_seen_epoch >= ? LIMIT 1""",
                (*key, epoch - ACTIVE_SESSION_STALE_SECONDS),
            ).fetchone()
            duplicate = duplicate or bool(requested_active and other_module)

            previous_active = bool(tracking["was_active"])
            previous_duplicate = bool(tracking["was_duplicate"])
            delta = max(0.0, epoch - float(tracking["last_seen_epoch"] or epoch))
            credited = 0.0
            if previous_active and owns_slot:
                # A delayed heartbeat or a return after inactivity cannot earn
                # time beyond the deadline recorded on the previous heartbeat.
                until_idle = max(0.0, float(tracking["active_until_epoch"]) - float(tracking["last_seen_epoch"]))
                credited = min(delta, HEARTBEAT_MAX_CREDIT_SECONDS, until_idle)

            accepted_active = bool(requested_active and not duplicate)
            next_owner_id: Optional[str] = owner_id or None
            next_owner_seen: Optional[float] = owner_seen or None
            if accepted_active:
                next_owner_id = tracking_session_id
                next_owner_seen = epoch
                # Taking over from a stale *different* module also revokes its
                # old slot, so a delayed heartbeat cannot credit overlapping time.
                connection.execute(
                    """UPDATE learner_course_progress
                       SET active_tracking_session_id = NULL, active_tracking_seen_epoch = NULL
                       WHERE session_id = ? AND trainee_id = ?
                         AND NOT (course_id = ? AND course_version = ?)""",
                    key,
                )
            elif owns_slot:
                next_owner_id = None
                next_owner_seen = None

            connection.execute(
                """
                UPDATE tracking_sessions
                SET current_activity_id = ?, last_seen_at = ?, last_seen_epoch = ?,
                    was_active = ?, was_duplicate = ?, credited_seconds = credited_seconds + ?, active_until_epoch = ?
                WHERE id = ?
                """,
                (
                    str(activity_id or "")[:128],
                    now_iso,
                    epoch,
                    int(accepted_active),
                    int(duplicate),
                    credited,
                    epoch + max(0.0, IDLE_TIMEOUT_SECONDS - age) if accepted_active else 0,
                    tracking_session_id,
                ),
            )
            connection.execute(
                """
                UPDATE learner_course_progress
                SET current_activity_id = CASE WHEN ? <> '' THEN ? ELSE current_activity_id END,
                    active_seconds = active_seconds + ?, updated_at = ?,
                    active_tracking_session_id = ?, active_tracking_seen_epoch = ?
                WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?
                """,
                (
                    activity_id,
                    activity_id,
                    credited,
                    now_iso,
                    next_owner_id,
                    next_owner_seen,
                    *key,
                ),
            )

            if accepted_active and not previous_active:
                self._event(
                    connection,
                    access,
                    "active_resumed",
                    tracking_session_id=tracking_session_id,
                    activity_id=activity_id,
                    at=now_iso,
                )
            elif not accepted_active and previous_active:
                self._event(
                    connection,
                    access,
                    "active_paused",
                    tracking_session_id=tracking_session_id,
                    activity_id=activity_id,
                    at=now_iso,
                    credited_seconds=credited,
                    details={"duplicate": duplicate, "visible": visible, "focused": focused},
                )
            if duplicate and not previous_duplicate:
                self._event(
                    connection,
                    access,
                    "duplicate_tab_blocked",
                    tracking_session_id=tracking_session_id,
                    activity_id=activity_id,
                    at=now_iso,
                )
            elif previous_duplicate and not duplicate:
                self._event(
                    connection,
                    access,
                    "duplicate_tab_released",
                    tracking_session_id=tracking_session_id,
                    activity_id=activity_id,
                    at=now_iso,
                )

            video_resync = self._record_video_samples(
                connection, access, tracking, progress, activity_id=activity_id,
                requirements=video_requirements or {}, samples=video_samples,
                credited=credited, delta=delta, accepted_active=accepted_active,
                visible=visible, focused=focused, now_iso=now_iso,
            )
            updated = self._progress_row(connection, access)
            return {
                "ended": False,
                "duplicate": duplicate,
                "active": accepted_active,
                "credited_seconds": round(credited, 2),
                "server_time": now_iso,
                "video_resync": video_resync,
                "progress": self._serialize_progress(updated),
            }

    def _record_video_samples(
        self, connection: sqlite3.Connection, access: Mapping[str, Any],
        tracking: sqlite3.Row, progress: sqlite3.Row, *, activity_id: str,
        requirements: Mapping[str, float], samples: Any, credited: float,
        delta: float, accepted_active: bool, visible: bool, focused: bool, now_iso: str,
    ) -> Dict[str, float]:
        """Credit only a continuous prefix, within the same active-time budget.

        Durations come from reviewed media metadata, never from the browser.
        The per-tracking-session baseline prevents reloads, duplicate tabs,
        repeated ended events and replayed requests from manufacturing viewing.
        """
        if samples is None:
            samples = []
        if not isinstance(samples, list) or len(samples) > 20:
            raise TrackingError("Suivi vidéo invalide.")
        incoming = {}
        for sample in samples:
            if not isinstance(sample, dict):
                raise TrackingError("Suivi vidéo invalide.")
            video_id = sample.get("id")
            position = sample.get("position")
            rate = sample.get("rate", 1)
            if (not isinstance(video_id, str) or video_id not in requirements or video_id in incoming
                    or isinstance(position, bool) or not isinstance(position, (int, float))
                    or not math.isfinite(position) or position < 0
                    or isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate)):
                raise TrackingError("Position de lecture invalide.")
            incoming[video_id] = sample
        if sum(sample.get("playing") is True for sample in incoming.values()) > 1:
            raise TrackingError("Regardez une seule vidéo à la fois.")
        saved = _json_dict(progress["video_progress_json"])
        activity_saved = saved.setdefault(activity_id, {})
        previous = _json_dict(tracking["video_samples_json"]) if tracking["current_activity_id"] == activity_id else {}
        next_samples = {}
        resync = {}
        budget = credited if visible and focused else 0.0
        for video_id, sample in incoming.items():
            duration = requirements[video_id]
            record = activity_saved.get(video_id) or {}
            if record.get("duration_seconds") != duration:
                record = {"duration_seconds": duration, "watched_seconds": 0.0, "completed": False}
            if videos_complete({video_id: record}, {video_id: duration}):
                continue
            frontier = min(duration, max(0.0, float(record.get("watched_seconds") or 0)))
            position = float(sample["position"])
            before = previous.get(video_id) or {}
            previous_position = float(before.get("position") or 0)
            advancement = position - previous_position
            normal_rate = sample.get("rate", 1) == 1
            valid_position = normal_rate and position <= duration + .05
            continuous = (before.get("playing") is True and previous_position <= frontier + .5
                          and -.25 <= advancement <= min(delta, HEARTBEAT_MAX_CREDIT_SECONDS) + .5)
            carry = 0.0
            if valid_position and continuous and budget > 0:
                # Retain a small amount of *already credited* time to absorb
                # request jitter without losing viewing time on every ping.
                # This is a balance, not a fresh allowance per request.
                available = budget + min(.5, max(0.0, float(before.get("credit_carry") or 0)))
                extension = max(0.0, min(position, frontier + available) - frontier)
                frontier += extension
                carry = min(.5, max(0.0, available - extension))
                budget = 0.0
            if not valid_position or position > frontier + .5:
                resync[video_id] = round(frontier, 3)
            completed = (video_id not in resync and sample.get("ended") is True
                         and position >= duration - .05 and frontier >= duration - .5)
            if completed:
                frontier = duration
                self._event(connection, access, "video_completed", tracking_session_id=tracking["id"],
                            activity_id=activity_id, at=now_iso,
                            details={"video_id": video_id, "duration_seconds": duration})
            activity_saved[video_id] = {
                "duration_seconds": duration, "watched_seconds": round(frontier, 3),
                "completed": completed, "completed_at": now_iso if completed else None,
            }
            next_samples[video_id] = {
                "position": frontier if video_id in resync else min(position, duration),
                "playing": bool(sample.get("playing") is True and normal_rate and accepted_active
                                and visible and focused and video_id not in resync),
                "credit_carry": carry if sample.get("playing") is True and video_id not in resync else 0.0,
            }
        connection.execute("UPDATE tracking_sessions SET video_samples_json = ? WHERE id = ?",
                           (json.dumps(next_samples, separators=(",", ":")), tracking["id"]))
        if incoming:
            connection.execute(
                """UPDATE learner_course_progress SET video_progress_json = ?
                   WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?""",
                (json.dumps(saved, separators=(",", ":")), *self._key_values(access)),
            )
        return resync

    def finish_tracking(
        self,
        access: Mapping[str, Any],
        tracking_session_id: str,
        *,
        activity_id: str = "",
        now_epoch: Optional[float] = None,
    ) -> Dict[str, Any]:
        epoch = float(now_epoch if now_epoch is not None else time.time())
        heartbeat = self.heartbeat(
            access,
            tracking_session_id,
            activity_id=activity_id,
            visible=False,
            focused=False,
            recent_activity=False,
            media_playing=False,
            now_epoch=epoch,
        )
        now_iso = _utc_iso(epoch)
        with self._transaction() as connection:
            tracking = connection.execute(
                "SELECT status FROM tracking_sessions WHERE id = ?",
                (tracking_session_id,),
            ).fetchone()
            if tracking is not None and tracking["status"] != "ended":
                connection.execute(
                    "UPDATE tracking_sessions SET status = 'ended', ended_at = ?, was_active = 0 WHERE id = ?",
                    (now_iso, tracking_session_id),
                )
                self._event(
                    connection,
                    access,
                    "session_finished",
                    tracking_session_id=tracking_session_id,
                    activity_id=activity_id,
                    at=now_iso,
                )
        heartbeat["ended"] = True
        heartbeat["active"] = False
        return heartbeat

    @staticmethod
    def _completion_values(
        completed: Iterable[str],
        answers: Mapping[str, Any],
        *,
        activity_order: Sequence[str],
        scored_activity_ids: Sequence[str],
        mastery_score: float,
        active_seconds: float = 0,
        required_seconds: int = 0,
        video_requirements: Optional[Mapping[str, Mapping[str, float]]] = None,
        video_progress: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        completed_set = {str(value) for value in completed}
        for activity_id, videos in (video_requirements or {}).items():
            if not videos_complete((video_progress or {}).get(activity_id, {}), videos):
                completed_set.discard(activity_id)
        ordered_completed = [activity_id for activity_id in activity_order if activity_id in completed_set]
        correct = sum(
            1
            for activity_id in scored_activity_ids
            if isinstance(answers.get(activity_id), Mapping) and answers[activity_id].get("correct") is True
        )
        score = round((correct / len(scored_activity_ids)) * 100, 2) if scored_activity_ids else 100.0
        activities_complete = bool(activity_order) and len(ordered_completed) == len(activity_order)
        all_complete = activities_complete and active_seconds >= required_seconds
        if all_complete:
            status = "passed" if score >= float(mastery_score) else "failed"
        elif activities_complete:
            status = "awaiting_time"
        else:
            status = "in_progress"
        next_activity = next(
            (activity_id for activity_id in activity_order if activity_id not in completed_set),
            activity_order[-1] if activity_order else "",
        )
        return {
            "completed": ordered_completed,
            "score": score,
            "status": status,
            "next_activity": next_activity,
            "all_complete": all_complete,
        }

    def complete_activity(
        self,
        access: Mapping[str, Any],
        activity_id: str,
        *,
        activity_order: Sequence[str],
        scored_activity_ids: Sequence[str],
        mastery_score: float,
        required_seconds: int = 0,
        answer: Optional[Mapping[str, Any]] = None,
        video_requirements: Optional[Mapping[str, Mapping[str, float]]] = None,
    ) -> Dict[str, Any]:
        if activity_id not in activity_order:
            raise TrackingError("Activité inconnue.")
        now_iso = _utc_iso()
        key = self._key_values(access)
        with self._transaction() as connection:
            self._ensure_progress_row(
                connection,
                access,
                now_iso=now_iso,
                current_activity_id=activity_id,
            )
            row = self._progress_row(connection, access)
            video_progress = _json_dict(row["video_progress_json"])
            if not videos_complete(video_progress.get(activity_id, {}), (video_requirements or {}).get(activity_id, {})):
                raise TrackingError("Regardez toute la vidéo avant de continuer.")
            completed = [str(value) for value in _json_list(row["completed_json"])]
            answers = _json_dict(row["answers_json"])
            already_completed = activity_id in completed
            if not already_completed:
                completed.append(activity_id)
            if answer is not None and activity_id not in answers:
                answers[activity_id] = dict(answer)

            completion = self._completion_values(
                completed,
                answers,
                activity_order=activity_order,
                scored_activity_ids=scored_activity_ids,
                mastery_score=mastery_score,
                active_seconds=float(row["active_seconds"] or 0), required_seconds=required_seconds,
                video_requirements=video_requirements, video_progress=video_progress,
            )
            completed_at = (row["completed_at"] or now_iso) if completion["all_complete"] else None
            connection.execute(
                """
                UPDATE learner_course_progress
                SET current_activity_id = ?, completed_json = ?, answers_json = ?,
                    score_percent = ?, status = ?, updated_at = ?, completed_at = ?
                WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?
                """,
                (
                    completion["next_activity"],
                    # Deselected sequences can later be re-added. Never erase
                    # their completion records when saving another activity.
                    json.dumps(list(dict.fromkeys(completed)), separators=(",", ":")),
                    json.dumps(answers, ensure_ascii=False, separators=(",", ":")),
                    completion["score"],
                    completion["status"],
                    now_iso,
                    completed_at,
                    *key,
                ),
            )
            if not already_completed:
                self._event(
                    connection,
                    access,
                    "answer_submitted" if answer is not None else "content_completed",
                    activity_id=activity_id,
                    at=now_iso,
                    details={"correct": answer.get("correct") if answer else None},
                )
                if completion["all_complete"]:
                    self._event(
                        connection,
                        access,
                        "course_completed",
                        activity_id=activity_id,
                        at=now_iso,
                        details={"status": completion["status"], "score_percent": completion["score"]},
                    )
            updated = self._progress_row(connection, access)
            result = self._serialize_progress(
                updated,
                activity_order=activity_order,
                scored_activity_ids=scored_activity_ids,
            )
            result["already_completed"] = already_completed
            return result

    def learner_progress(self, session_id: str, trainee_id: str) -> List[Dict[str, Any]]:
        """Read the whole path in one query, without starting any new module."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM learner_course_progress WHERE session_id = ? AND trainee_id = ?",
                (session_id, trainee_id),
            ).fetchall()
        return [self._serialize_progress(row) for row in rows]

    def live_progress(
        self,
        course_id: str,
        *,
        course_version: Optional[str] = None,
        now_epoch: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        epoch = float(now_epoch if now_epoch is not None else time.time())
        with self._connect() as connection:
            if course_version:
                rows = connection.execute(
                    """
                    SELECT * FROM learner_course_progress
                    WHERE course_id = ? AND course_version = ?
                    ORDER BY updated_at DESC
                    """,
                    (course_id, course_version),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM learner_course_progress
                    WHERE course_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (course_id,),
                ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            item = self._serialize_progress(row)
            seen = float(row["active_tracking_seen_epoch"] or 0)
            item["live"] = bool(row["active_tracking_session_id"] and epoch - seen <= ACTIVE_SESSION_STALE_SECONDS)
            item["last_seen_seconds_ago"] = round(max(0.0, epoch - seen), 1) if seen else None
            result.append(item)
        return result

    def events_for_learner(
        self,
        access: Mapping[str, Any],
        *,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        key = self._key_values(access)
        safe_limit = max(1, min(int(limit), 5_000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tracking_events
                WHERE session_id = ? AND trainee_id = ? AND course_id = ? AND course_version = ?
                ORDER BY id ASC LIMIT ?
                """,
                (*key, safe_limit),
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "activity_id": row["activity_id"],
                "event_at": row["event_at"],
                "credited_seconds": round(float(row["credited_seconds"] or 0), 2),
                "details": _json_dict(row["details_json"]),
            }
            for row in rows
        ]
