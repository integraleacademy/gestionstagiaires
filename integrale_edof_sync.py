"""Track native CPF state changes after a complete EDOF sync."""
from contextlib import closing

from cpf_provider import ProviderStore
import edof_automation_audit as audit


def event_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS directory_states (
        folder TEXT PRIMARY KEY, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS directory_events (
        id INTEGER PRIMARY KEY, folder TEXT NOT NULL, previous TEXT NOT NULL, state TEXT NOT NULL, checked REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS directory_events_folder ON directory_events(folder,checked)")
    db.execute("CREATE TABLE IF NOT EXISTS directory_cursor (id INTEGER PRIMARY KEY CHECK(id=1), checked REAL NOT NULL)")


def process_directory(store, snapshot, *, owner=""):
    from integrale_edof_dashboard import category

    checked = snapshot["checked"]
    with closing(ProviderStore(store.directory).connect()) as db, db:
        event_tables(db)
        db.execute("BEGIN IMMEDIATE")
        audit.tables(db)
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
