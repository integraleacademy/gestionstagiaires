"""Track native CPF state changes after a complete EDOF sync."""
from contextlib import closing

from cpf_provider import ProviderStore
import edof_automation_audit as audit
import edof_dossier_dates as dates


def event_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS directory_states (
        folder TEXT PRIMARY KEY, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS directory_events (
        id INTEGER PRIMARY KEY, folder TEXT NOT NULL, previous TEXT NOT NULL, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS directory_events_folder ON directory_events(folder,checked)")
    db.execute("CREATE TABLE IF NOT EXISTS directory_cursor (id INTEGER PRIMARY KEY CHECK(id=1), checked REAL NOT NULL)")


def stage_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_stage_dates (
        owner TEXT NOT NULL, folder TEXT NOT NULL, kind TEXT NOT NULL, observed REAL NOT NULL,
        checked REAL NOT NULL, filed TEXT NOT NULL, exact_at TEXT NOT NULL, created TEXT NOT NULL,
        stage_key TEXT NOT NULL, PRIMARY KEY(owner,folder))""")


def stage_dates(db, owner):
    stage_table(db)
    return {r["folder"]: r for r in db.execute("SELECT * FROM cpf_stage_dates WHERE owner=?", (owner,))}


def save_dates(db, snapshot, owner, category):
    if not owner:
        return
    stage_table(db)
    checked = snapshot["checked"]

    def values():
        for folder, row in snapshot["rows"].items():
            kind = category(row)
            filed, exact = dates.source_dates(row, category)
            yield owner, folder, kind, checked, checked, filed, exact, dates.stamp(row.get("created_at")), dates.stage_key(row, kind)

    # A new France Travail solicitation can have the same status as its predecessor.
    same = "kind=excluded.kind AND (stage_key='' OR excluded.stage_key='' OR stage_key=excluded.stage_key)"
    db.executemany(f"""INSERT INTO cpf_stage_dates VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(owner,folder) DO UPDATE SET
            observed=CASE WHEN {same} THEN observed ELSE excluded.observed END,
            exact_at=CASE WHEN {same} AND excluded.exact_at='' THEN exact_at ELSE excluded.exact_at END,
            stage_key=CASE WHEN {same} AND excluded.stage_key='' THEN stage_key ELSE excluded.stage_key END,
            filed=COALESCE(NULLIF(excluded.filed,''),filed), created=COALESCE(NULLIF(excluded.created,''),created),
            kind=excluded.kind, checked=excluded.checked WHERE excluded.checked >= checked""", values())


def dates_for_view(db, owner, rows, checked, category):
    # Seed from already-saved evidence on rollout, and retain verified receipts between directory scans.
    saved = stage_dates(db, owner)
    missing = {}
    for row in rows:
        folder = row["folder_id"]
        observed = row.get("observed_at") or checked
        old = saved.get(folder)
        key = dates.stage_key(row, row["kind"])
        changed = old and (old["kind"] != row["kind"] or (key and key != old["stage_key"]))
        if observed and (not old or changed and observed > old["checked"]):
            missing.setdefault(observed, {})[folder] = row
    if missing:
        with db:
            for observed, records in missing.items():
                save_dates(db, {"checked": observed, "rows": records}, owner, category)
        saved = stage_dates(db, owner)
    return saved


def observe_pending(store, snapshot, owner):
    from integrale_edof_dashboard import category
    with closing(ProviderStore(store.directory).connect()) as db, db:
        save_dates(db, snapshot, owner, category)


def process_directory(store, snapshot, *, owner=""):
    from integrale_edof_dashboard import category

    checked = snapshot["checked"]
    with closing(ProviderStore(store.directory).connect()) as db, db:
        event_tables(db)
        db.execute("BEGIN IMMEDIATE")
        audit.tables(db)
        save_dates(db, snapshot, owner, category)
        previous = db.execute("SELECT checked FROM directory_cursor WHERE id=1").fetchone()
        if previous and checked <= previous[0]:
            return
        before = {r["folder"]: r["state"] for r in db.execute("SELECT folder, state FROM directory_states")}
        for folder, row in snapshot["rows"].items():
            kind = category(row)
            if previous and before.get(folder) != kind:
                event = db.execute("INSERT INTO directory_events(folder,previous,state,checked) VALUES (?,?,?,?)",
                                   (folder,before.get(folder, ""),kind,checked))
                if owner:
                    audit.observed(db, owner, row, before.get(folder, ""), kind, checked, event.lastrowid)
            db.execute("INSERT INTO directory_states VALUES(?,?,?) ON CONFLICT(folder) DO UPDATE SET state=excluded.state, checked=excluded.checked",
                       (folder,kind,checked))
        db.execute("INSERT OR REPLACE INTO directory_cursor VALUES (1,?)", (checked,))
