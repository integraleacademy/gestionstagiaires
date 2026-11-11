"""Bounded, read-only follow-up of dossiers opened by an administrator.

Reads share the existing daytime browser, authentication and traffic governor.
The web endpoints only renew a short lease; they never contact EDOF themselves.
"""
import json
import time
from urllib.parse import urlsplit

import edof_directory as directory


def key(owner, folder):
    return f"edof-enrolment:{owner}:{folder}"


def install(db):
    db.execute("""CREATE TABLE IF NOT EXISTS edof_enrolment_watch (
        owner TEXT NOT NULL, folder TEXT NOT NULL, expires REAL NOT NULL,
        attempted REAL NOT NULL DEFAULT 0, PRIMARY KEY(owner,folder))""")


def watch(private, owner, row):
    folder = row["folder_id"]
    if not directory.ID_RE.fullmatch(folder):
        raise ValueError("Numéro de dossier invalide.")
    private.put(key(owner, folder)+":identity", {k:row[k] for k in
                ("folder_id", "first_name", "last_name")}, ttl=600)
    with private.connect() as db:
        install(db)
        db.execute("""INSERT INTO edof_enrolment_watch(owner,folder,expires) VALUES(?,?,?)
            ON CONFLICT(owner,folder) DO UPDATE SET expires=excluded.expires""",
                   (owner, folder, time.time()+300))


def with_watched(private, owner, snapshot):
    if not snapshot:
        return snapshot
    with private.connect() as db:
        install(db)
        folders = [r[0] for r in db.execute("SELECT folder FROM edof_enrolment_watch WHERE owner=?", (owner,))]
    rows = dict(snapshot["rows"])
    for folder in folders:
        saved = private.get(key(owner, folder))
        before = rows.get(folder)
        if not saved or not before or saved["checked"] <= max(before.get("observed_at") or 0, snapshot.get("checked") or 0):
            continue
        fields = saved["fields"]
        if all(directory.normalized(fields.get(k) or "") == directory.normalized(before.get(k) or "")
               for k in ("first_name", "last_name")):
            rows[folder] = {**before, **saved["row"], "observed_at":saved["checked"]}
    return {**snapshot, "rows":rows}


def fill(context, witness, private, owner, origin, prefix):
    """At most two GETs per directory poll, never a new login or a remote write."""
    workspace = f"/edof-api/v1/api/private/siret/{directory.SIRET}/"
    if not witness or witness.method != "GET":
        return
    source = urlsplit(witness.url)
    if ((source.scheme, source.netloc) != ("https", origin) or not source.path.startswith(workspace)
            or prefix != workspace+"organisms/current/registration-folders/"):
        return
    now = time.time()
    with private.connect() as db:
        install(db)
        db.execute("DELETE FROM edof_enrolment_watch WHERE expires<?", (now-86400,))
        folders = [r[0] for r in db.execute("""SELECT folder FROM edof_enrolment_watch
            WHERE owner=? AND expires>? AND attempted<? ORDER BY attempted,folder LIMIT 2""",
            (owner, now, now-110))]
    for folder in folders:
        expected = private.get(key(owner, folder)+":identity")
        if not expected or not directory.ID_RE.fullmatch(folder):
            continue
        with private.connect() as db:
            db.execute("UPDATE edof_enrolment_watch SET attempted=? WHERE owner=? AND folder=?", (now, owner, folder))
        target = "https://"+origin+prefix+folder
        reply = context.request.get(target, headers={**directory.private_headers(witness), "Current-Siret":directory.SIRET},
                                    max_redirects=0, timeout=5500)
        try:
            directory.check_throttling(reply)
            if reply.url != target or reply.status != 200 or len(reply.body()) > 2_000_000:
                continue
            raw = json.loads(reply.body())
            row = directory.project(raw)
            if row["folder_id"] != folder or any(not expected.get(k) or
                    directory.normalized(row.get(k) or "") != directory.normalized(expected[k])
                    for k in ("first_name", "last_name")):
                continue
            from edof_server_browser import project_folder
            fields = project_folder(raw, registration=True)
            private.put(key(owner, folder), {"checked":time.time(), "row":row, "fields":fields}, ttl=86400)
        finally:
            reply.dispose()
