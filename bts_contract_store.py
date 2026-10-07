"""Private apprenticeship preparation state and immutable document versions."""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path

import fcntl

from bts_workspace_store import ALL_FIELDS, WorkspaceStore, WorkspaceError, EditConflict, as_json, now


class ContractStore(WorkspaceStore):
    def __init__(self, db_path):
        super().__init__(db_path)
        self.files_root = Path(db_path).resolve().parent / "bts_documents"
        self.files_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS bts_candidate_imports (
                    source_id TEXT PRIMARY KEY, dossier_id TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_contract_settings (
                    dossier_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bts_contract_packages (
                    id TEXT PRIMARY KEY, dossier_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bts_packages_dossier ON bts_contract_packages(dossier_id,created_at);
            """)

    @contextmanager
    def lock(self, record_id):
        import hashlib
        path = self.files_root / (hashlib.sha256(record_id.encode()).hexdigest() + ".lock")
        with path.open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WorkspaceError("Une opération est déjà en cours sur ce dossier. Réessayez à sa fin.") from None
            yield

    def imported(self, dossier_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bts_candidate_imports WHERE dossier_id=?", (dossier_id,)).fetchone()
        return {**dict(row), "values": json.loads(row["payload_json"])} if row else None

    def import_candidate(self, candidate, actor):
        from bts_cerfa import FIELDS, validate_values, CerfaValidationError
        from bts_inscriptions import candidate_values, candidate_id, normalize
        source_id = candidate_id(candidate.get("id"))
        raw_values = candidate_values(candidate)
        # Keep malformed source values in the source panel, never insert them as
        # valid CERFA defaults or discard the rest of an otherwise useful import.
        try:
            values = validate_values(raw_values)
        except CerfaValidationError as exc:
            values = validate_values({k: v for k, v in raw_values.items() if k not in exc.errors})
        if not values.get("apprentice_last_name") or not values.get("apprentice_first_name"):
            raise WorkspaceError("Le nom et le prénom de cette préinscription sont incomplets.")
        snapshot = {k: v for k, v in candidate.items() if k not in {"num_secu"}}
        local = {k: v for k, v in values.items() if k in ALL_FIELDS}
        complements = {k: v for k, v in values.items() if k in FIELDS and k not in ALL_FIELDS}
        mode = normalize(candidate.get("mode"))
        settings = {"teaching_mode": mode if mode in {"presentiel", "distanciel", "hybride"} else "",
                    "guardian_first_name": str(candidate.get("resp_prenom") or ""),
                    "guardian_last_name": str(candidate.get("resp_nom") or ""),
                    "guardian_phone": str(candidate.get("resp_tel") or "")}
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT dossier_id FROM bts_candidate_imports WHERE source_id=?", (source_id,)).fetchone()
            if old:
                return old[0], False
            record_id, stamp = "l-" + uuid.uuid4().hex, now()
            conn.execute("INSERT INTO bts_local_dossiers(id,payload_json,created_at,updated_at) VALUES(?,?,?,?)",
                         (record_id, as_json(local), stamp, stamp))
            conn.execute("INSERT INTO bts_cerfa_complements(dossier_id,payload_json,updated_at) VALUES(?,?,?)",
                         (record_id, as_json(complements), stamp))
            conn.execute("INSERT INTO bts_candidate_imports VALUES(?,?,?,?)", (source_id, record_id, as_json(snapshot), stamp))
            conn.execute("INSERT INTO bts_contract_settings(dossier_id,payload_json,updated_at) VALUES(?,?,?)",
                         (record_id, as_json(settings), stamp))
            self._event(conn, record_id, "Dossier créé depuis les inscriptions BTS", actor)
        return record_id, True

    def settings(self, dossier_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM bts_contract_settings WHERE dossier_id=?", (dossier_id,)).fetchone()
        return {"values": json.loads(row["payload_json"]), "revision": row["revision"]} if row else {"values": {}, "revision": 0}

    def save_settings(self, dossier_id, values, revision, actor, *, _connection=None):
        with (self._connect() if _connection is None else nullcontext(_connection)) as conn:
            if _connection is None:
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT revision FROM bts_contract_settings WHERE dossier_id=?", (dossier_id,)).fetchone()
            if (row[0] if row else 0) != revision:
                raise EditConflict("Les paramètres ont changé. Rechargez le dossier avant d’enregistrer.")
            conn.execute("INSERT INTO bts_contract_settings VALUES(?,?,?,?) ON CONFLICT(dossier_id) DO UPDATE SET payload_json=excluded.payload_json,revision=excluded.revision,updated_at=excluded.updated_at",
                         (dossier_id, as_json(values), revision + 1, now()))
            self._event(conn, dossier_id, "Paramètres des conventions et signataires enregistrés", actor)

    def save_contract_information(self, dossier_id, data, settings, revision, cerfa_revision, source_hash, actor):
        """One transaction for both visible sections of the Contract tab."""
        from bts_cerfa import effective_values, validate_values
        from bts_contract_documents import defaults
        submitted = validate_values(data)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record = self.record(dossier_id)
            if not record:
                raise WorkspaceError("Dossier introuvable.")
            row = conn.execute("SELECT payload_json FROM bts_cerfa_complements WHERE dossier_id=?", (dossier_id,)).fetchone()
            values = effective_values(record, json.loads(row[0]) if row else {})
            values.update(submitted)
            calculated = defaults(values, settings)
            self.save_cerfa_complements(dossier_id, submitted, cerfa_revision, source_hash, actor, _connection=conn)
            self.save_settings(dossier_id, calculated, revision, actor, _connection=conn)

    def packages(self, dossier_id):
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM bts_contract_packages WHERE dossier_id=? ORDER BY rowid DESC", (dossier_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def package(self, dossier_id, package_id=None):
        packages = self.packages(dossier_id)
        return next((p for p in packages if p["id"] == package_id), None) if package_id else next(iter(packages), None)

    def save_package(self, dossier_id, package, *, event=None, actor="Équipe"):
        with self._connect() as conn:
            conn.execute("INSERT INTO bts_contract_packages VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                         (package["id"], dossier_id, as_json(package), package["created_at"], now()))
            if event:
                self._event(conn, dossier_id, event, actor)

    def path(self, relative):
        path = (self.files_root / relative).resolve()
        if not path.is_relative_to(self.files_root):
            raise WorkspaceError("Chemin de document invalide.")
        return path
