"""Append-only, minimal audit records; never drive or retry an EDOF operation."""
from contextlib import closing
import json
import time

NOW_SQL = "(julianday('now') - 2440587.5) * 86400.0"
FIELDS = ("first_name", "last_name", "title", "session_start_date", "session_end_date", "actual_date")
STATE_KINDS = {"entry": "entry", "training": "entry", "out": "out", "declared": "declared",
               "billable": "billable", "invoiced": "invoiced", "paid": "paid"}


def tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS edof_automation_events (
        id INTEGER PRIMARY KEY, event_key TEXT UNIQUE, owner TEXT NOT NULL, folder TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL, status TEXT NOT NULL, occurred REAL NOT NULL, detail TEXT NOT NULL DEFAULT '',
        context TEXT NOT NULL DEFAULT '{}', source TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS edof_events_owner_time ON edof_automation_events(owner,occurred DESC)")
    db.execute("CREATE TABLE IF NOT EXISTS edof_history_meta (name TEXT PRIMARY KEY, value REAL NOT NULL)")
    db.execute("INSERT OR IGNORE INTO edof_history_meta VALUES ('started',?)", (time.time(),))


def context(row):
    return json.dumps({key: row.get(key) or "" for key in FIELDS}, ensure_ascii=False)


def add(db, *, owner, folder="", kind, status, occurred, detail="", row=None, source, key=None):
    db.execute("""INSERT OR IGNORE INTO edof_automation_events
        (event_key,owner,folder,kind,status,occurred,detail,context,source) VALUES(?,?,?,?,?,?,?,?,?)""",
               (key, owner, folder, kind, status, occurred, detail, context(row or {}), source))


def install_declarations(db):
    """Triggers share the declaration transaction, including crashes and retries.

    changed can be a future retry deadline or zero after a recheck. New audit
    timestamps must therefore come from the clock, never from that column.
    """
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='edof_declaration_audit_update'").fetchone():
        return
    with db:
        db.execute("BEGIN IMMEDIATE")
        tables(db)
        for row in db.execute("SELECT * FROM cpf_declarations").fetchall():
            intent = json.loads(row["intent"])
            stamp = row["created"] if row["status"] == "queued" else row["changed"]
            if stamp <= 0 or stamp > time.time():
                continue  # No trustworthy historical timestamp survives.
            add(db, owner=row["owner"], folder=row["folder"], kind="entry" if row["action"] == "entry_training" else "declared",
                status=row["status"], occurred=stamp, detail="" if row["status"] == "queued" else row["detail"], row=intent, source="legacy",
                key=f"legacy-declaration:{row['folder']}:{row['action']}")
        ctx = "json_object(" + ",".join(f"'{k}',json_extract(NEW.intent,'$.{k}')" for k in FIELDS) + ")"
        kind = "CASE WHEN NEW.action='entry_training' THEN 'entry' ELSE 'declared' END"
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS edof_declaration_audit_insert AFTER INSERT ON cpf_declarations BEGIN
            INSERT INTO edof_automation_events(owner,folder,kind,status,occurred,detail,context,source)
            VALUES(NEW.owner,NEW.folder,{kind},NEW.status,{NOW_SQL},NEW.detail,{ctx},'declaration'); END""")
        exit_event = "NEW.detail='declaration_exit_confirmed' AND OLD.token!=NEW.token"
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS edof_declaration_audit_update AFTER UPDATE ON cpf_declarations
            WHEN OLD.status!=NEW.status OR OLD.detail!=NEW.detail OR OLD.token!=NEW.token OR OLD.checks!=NEW.checks
              OR (NEW.status='queued' AND NEW.detail!='' AND OLD.changed!=NEW.changed AND NEW.changed>0)
            BEGIN INSERT INTO edof_automation_events(owner,folder,kind,status,occurred,detail,context,source)
            VALUES(NEW.owner,NEW.folder,CASE WHEN {exit_event} THEN 'out' ELSE {kind} END,
                CASE WHEN {exit_event} THEN 'confirmed' ELSE NEW.status END,{NOW_SQL},NEW.detail,{ctx},'declaration'); END""")


def install_proposals(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='edof_proposal_audit_update'").fetchone():
        return
    with db:
        db.execute("BEGIN IMMEDIATE")
        tables(db)
        for row in db.execute("SELECT * FROM inscription_proposals").fetchall():
            add(db, owner=row["owner"], folder=row["folder"], kind="proposal", status=row["status"],
                occurred=row["updated"], detail=row["message"], row=dict(row), source="legacy",
                key=f"legacy-proposal:{row['folder']}")
        for event, when in [("insert", ""), ("update", "WHEN OLD.status!=NEW.status OR OLD.message!=NEW.message OR OLD.token!=NEW.token")]:
            db.execute(f"""CREATE TRIGGER IF NOT EXISTS edof_proposal_audit_{event} AFTER {event.upper()} ON inscription_proposals {when}
                BEGIN INSERT INTO edof_automation_events(owner,folder,kind,status,occurred,detail,context,source)
                VALUES(NEW.owner,NEW.folder,'proposal',NEW.status,{NOW_SQL},NEW.message,
                    json_object('first_name',NEW.first_name,'last_name',NEW.last_name),'proposal'); END""")


def install_jobs(db):
    """Archive the available jobs before the operational 24-hour cache is pruned."""
    tables(db)
    # Declarations and proposals have their own authoritative receipts. Do not
    # count their browser jobs as a second business event.
    columns = "event_key,owner,kind,status,occurred,detail,source"
    def values(prefix):
        code = f"COALESCE(json_extract({prefix}result,'$.code'),'browser_error')"
        return (f"'job:'||{prefix}id||':'||{prefix}finished||':'||{code},{prefix}owner,CASE WHEN {prefix}mode='directory' THEN 'sync' ELSE 'control' END,"
                f"CASE WHEN {code} IN ('directory_ready','requests_ready','read_success','proposal_loaded','declaration_inspected','login_reachable') "
                f"THEN 'confirmed' ELSE 'error' END,{prefix}finished,{code},'connector'")
    scope = "mode NOT IN ('declare','reconcile','proposal_send','proposal_check')"
    db.execute(f"""INSERT OR IGNORE INTO edof_automation_events({columns}) SELECT {values('')} FROM jobs
        WHERE finished IS NOT NULL AND {scope}""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS edof_job_audit AFTER UPDATE ON jobs
        WHEN NEW.finished IS NOT NULL AND NEW.{scope} BEGIN
        INSERT OR IGNORE INTO edof_automation_events({columns}) VALUES({values('NEW.')}); END""")


def decision(directory, owner, row, action, outcome):
    """Preserve unmet prerequisites without repeating an unchanged alert each scan."""
    from edof_declarations import database
    kind = "entry" if action == "entry_training" else "declared"
    status = "paused" if outcome == "blocked" else "review"
    with closing(database(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        last = db.execute("""SELECT detail FROM edof_automation_events WHERE owner=? AND folder=? AND kind=?
            AND source IN ('discovery','declaration') ORDER BY id DESC LIMIT 1""", (owner,row["folder_id"],kind)).fetchone()
        if not last or last["detail"] != "discovery_" + outcome:
            add(db, owner=owner, folder=row["folder_id"], kind=kind, status=status, occurred=time.time(),
                detail="discovery_" + outcome, row=row, source="discovery")


def observed(db, owner, row, previous, kind, checked, event_id):
    if kind in STATE_KINDS:
        add(db, owner=owner, folder=row["folder_id"], kind=STATE_KINDS[kind], status="observed", occurred=checked,
            detail="state_observed", row=row, source="edof", key=f"directory:{event_id}")


def import_directory_events(db, owner, rows):
    """Recover existing observations only for dossiers visible to this account."""
    for event in db.execute("""SELECT d.* FROM directory_events d LEFT JOIN edof_automation_events e
        ON e.event_key='directory:'||d.id WHERE e.id IS NULL""").fetchall():
        if event["folder"] in rows:
            observed(db, owner, rows[event["folder"]], event["previous"], event["state"], event["checked"], event["id"])
