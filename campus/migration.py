"""One-way, verified cutover, before the disk-backed manager accepts requests."""
from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3

from psycopg import sql
from campus import catalog, db, directory
from elearning_native.exams import ExamStore
from elearning_native.production_ai import ProductionAIService
from elearning_native.store import NativeElearningStore
from elearning_native.vtc_cma import CmaStore
from elearning_native.vtc_105_migration import _ensure_table
from uv_questionnaire_store import UVQuestionnaireStore


def initialize_stores(root, uv_path):
    directory.initialize()
    catalog.initialize()
    UVQuestionnaireStore(uv_path)
    tracking = root / "tracking.sqlite3"
    NativeElearningStore(tracking)
    ExamStore(tracking)
    CmaStore(tracking)
    with db.connect(tracking) as conn:
        _ensure_table(conn)
    ProductionAIService(root / "production_ai.sqlite3", background=False)


def _fingerprint(row):
    payload = json.dumps(list(row), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(payload.encode()).digest(), "big")


def copy_file(conn, path):
    """SQLite holds a read snapshot, Postgres commits all stores or none of them."""
    counts = {}
    if not path.is_file():
        return counts
    schema = db.SCHEMAS[path.name]
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        src.execute("BEGIN")
        if src.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise ValueError(f"Source SQLite illisible: {path.name}")
        tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        # An alias references a canonical attempt; create rows in dependency order.
        for table in sorted(tables, key=lambda t: (t == "uv_questionnaire_alias", t)):
            columns = [r[1] for r in src.execute("SELECT * FROM pragma_table_info(?)", (table,))]
            dest = sql.Identifier(schema, table)
            valid = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                                 (schema, table)).fetchall()
            if not columns or set(columns) - {r[0] for r in valid}:
                raise ValueError(f"Schéma historique non pris en charge: {table}")
            if conn.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(dest)).fetchone():
                raise ValueError(f"Destination déjà alimentée avant bascule: {table}")
            names = sql.SQL(",").join(map(sql.Identifier, columns))
            sqlite_name = '"' + table.replace('"', '""') + '"'
            count = source_sum = 0
            with conn.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(dest, names)) as writer:
                for row in src.execute("SELECT * FROM " + sqlite_name):
                    writer.write_row(row)
                    count += 1
                    source_sum += _fingerprint(row)
            target_sum = target_count = 0
            with conn.cursor(name="campus_verify") as reader:
                reader.execute(sql.SQL("SELECT {} FROM {}").format(names, dest))
                for row in reader:
                    target_sum += _fingerprint(row)
                    target_count += 1
            if (count, source_sum) != (target_count, target_sum):
                raise ValueError(f"Écart entre source et destination: {table}")
            if "id" in columns:
                sequence = conn.execute("SELECT pg_get_serial_sequence(%s, 'id')", (schema + "." + table,)).fetchone()[0]
                if sequence:
                    highest = conn.execute(sql.SQL("SELECT max(id) FROM {}").format(dest)).fetchone()[0]
                    if highest is not None:
                        conn.execute("SELECT setval(%s,%s,true)", (sequence, highest))
            counts[table] = count
    return counts


def ready():
    with db.pool().connection() as conn:
        return bool(conn.execute("SELECT 1 FROM campus_directory.settings WHERE name='active'").fetchone())


def activate(host, read_source):
    if not db.enabled():
        raise RuntimeError("La bascule requiert le stockage pédagogique PostgreSQL.")
    source = Path(host.DATA_FILE)
    if not source.is_file():
        raise ValueError("Source administrative absente. Bascule annulée.")
    root = Path(host.PERSIST_DIR) / "native_elearning"
    uv_path = source.with_name("uv-questionnaires.sqlite3")
    initialize_stores(root, uv_path)
    with db.pool().connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('campus.initial_migration'))")
        prior = conn.execute("SELECT value FROM campus_directory.settings WHERE name='active'").fetchone()
        if prior:
            return json.loads(prior[0])
        report = {}
        for path in (uv_path, root / "tracking.sqlite3", root / "production_ai.sqlite3"):
            report[path.name] = copy_file(conn, path)
        catalog.publish(root, connection=conn)
        report["enrolments"] = directory.synchronize(read_source, host, connection=conn)
        report["activated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        conn.execute("INSERT INTO campus_directory.settings VALUES ('active',%s)", (json.dumps(report),))
    return report
