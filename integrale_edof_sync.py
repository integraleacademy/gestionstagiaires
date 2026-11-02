"""Track native CPF changes and prepare supported actions after a complete EDOF sync."""
import datetime as dt
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo

from cpf_provider import ProviderStore
from edof_directory import canonical_dates


def event_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS directory_states (
        folder TEXT PRIMARY KEY, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS directory_events (
        id INTEGER PRIMARY KEY, folder TEXT NOT NULL, previous TEXT NOT NULL, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS directory_events_folder ON directory_events(folder,checked)")
    db.execute("CREATE TABLE IF NOT EXISTS directory_cursor (id INTEGER PRIMARY KEY CHECK(id=1), checked REAL NOT NULL)")


def first_activity(tracking, link, row):
    if tracking is None or not row.get("session_start_date") or not row.get("session_end_date"):
        return None
    # Connecting, opening a page and time in a tab do not prove a learning activity.
    events = tracking.execute("""SELECT id, event_at FROM tracking_events
        WHERE session_id=? AND trainee_id=? AND event_type IN ('content_completed','answer_submitted')
        AND activity_id != '' AND event_at >= ? ORDER BY event_at, id LIMIT 50""",
        (str(link["session_id"]), str(link["trainee_id"]), (dt.date.fromisoformat(row["session_start_date"]) - dt.timedelta(days=1)).isoformat()))
    for item in events:
        try:
            timestamp = dt.datetime.fromisoformat(item[1])
            if timestamp.tzinfo is None:
                continue
        except (TypeError, ValueError):
            continue
        actual = timestamp.astimezone(ZoneInfo("Europe/Paris")).date().isoformat()
        if row["session_start_date"] <= actual <= row["session_end_date"] and actual <= dt.datetime.now(ZoneInfo("Europe/Paris")).date().isoformat():
            return {"action": "entry_training", "actual_date": actual,
                    "evidence": f"Activité pédagogique enregistrée dans le LMS, événement {item[0]}", "source": "lms"}
    return None


def process_directory(store, snapshot, data_file):
    from integrale_edof_dashboard import ACTIONS, active_blocks, category, operations_db

    checked = snapshot["checked"]
    try:
        with open(data_file, encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        data = {}
    links = {str(x.get("external_id")): x for x in data.get("wedof_links", [])
             if isinstance(x, dict) and x.get("active") and x.get("session_id") and x.get("trainee_id")}
    blocks = active_blocks(data)
    db_path = Path(data_file).parent / "native_elearning" / "tracking.sqlite3"
    tracking = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) if db_path.is_file() else None
    try:
        if tracking and not tracking.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tracking_events'").fetchone():
            tracking.close()
            tracking = None
        with closing(operations_db(ProviderStore(store.directory))) as db, db:
            event_tables(db)
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT checked FROM directory_cursor WHERE id=1").fetchone()
            if previous and checked <= previous[0]:
                return
            before = {r["folder"]: r["state"] for r in db.execute("SELECT folder, state FROM directory_states")}
            for folder, row in snapshot["rows"].items():
                kind = category(row)
                if previous and before.get(folder) != kind:
                    db.execute("INSERT INTO directory_events(folder,previous,state,checked) VALUES (?,?,?,?)",
                               (folder,before.get(folder, ""),kind,checked))
                db.execute("INSERT INTO directory_states VALUES(?,?,?) ON CONFLICT(folder) DO UPDATE SET state=excluded.state, checked=excluded.checked",
                           (folder,kind,checked))
                if kind == "accepted" and folder in links and not any((folder, action) in blocks for action in (ACTIONS[kind],"both")):
                    draft = first_activity(tracking, links[folder], canonical_dates(row))
                    if draft:
                        db.execute("""INSERT INTO dossier_work(folder,draft,updated,actor) VALUES(?,?,?,'LMS')
                            ON CONFLICT(folder) DO UPDATE SET draft=excluded.draft, updated=excluded.updated, actor=excluded.actor
                            WHERE dossier_work.draft IS NULL""", (folder,json.dumps(draft, ensure_ascii=False),
                            dt.datetime.fromtimestamp(checked, dt.timezone.utc).isoformat()))
            db.execute("INSERT OR REPLACE INTO directory_cursor VALUES (1,?)", (checked,))
    finally:
        if tracking is not None:
            tracking.close()
