"""Read submitted applications and France Travail decisions in the existing session."""
import json
import time

import edof_directory as directory

INTERVAL = 300


def refresh(context, witness, vault, owner, checkpoint):
    # The regular notProcessed poll cannot discover a dossier already submitted
    # by the OF, nor a later FT solicitation on an existing validated dossier.
    from edof_server_browser import read_recent_directory, EDOF_HOST, API_PREFIX

    attempted = "validated-attempt:" + owner
    if time.time() - (vault.get(attempted) or 0) < INTERVAL:
        return
    vault.put(attempted, time.time(), ttl=900)
    fresh = read_recent_directory(context, witness, "validated", checkpoint, {})
    if any(directory.normalized(r.get("state") or "") != "validated" for r in fresh["rows"].values()):
        raise directory.IncompleteDirectory("scope")
    previous = directory.with_validated(
        vault.get(directory.record_key(owner), keep=True), vault.get(directory.validated_key(owner)))
    rows = {k: {**r, "observed_at": fresh["checked"]} for k, r in fresh["rows"].items()}
    # Publish the verified filtered list even if an optional departed-dossier
    # read fails. Keep recent transitions until the general list catches up.
    prior = vault.get(directory.validated_key(owner)) or {}
    retained = {k: r for k, r in prior.get("rows", {}).items()
                if (r.get("observed_at") or prior.get("checked", 0)) > (previous or {}).get("checked", 0)}
    def save():
        vault.put(directory.validated_key(owner),
                  {**fresh, "rows": {**retained, **rows}, "scope": "validated"}, ttl=directory.TTL)
    save()
    # Absence from this filtered tab does not prove acceptance or refusal.
    # Re-read at most two departed applications; retain their last verified
    # evidence if EDOF is unavailable, and rotate oldest observations first.
    missing = [r for k, r in (previous or {}).get("rows", {}).items()
               if k not in rows and directory.normalized(r.get("state") or "") == "validated"]
    missing.sort(key=lambda r: (r.get("observed_at") or (previous or {}).get("checked", 0), r["folder_id"]))
    for old in missing[:2]:
        folder = old["folder_id"]
        if not directory.ID_RE.fullmatch(folder):
            continue
        checkpoint()
        target = "https://" + EDOF_HOST + API_PREFIX + folder
        reply = context.request.get(target, headers={**directory.private_headers(witness), "Current-Siret": directory.SIRET},
                                    max_redirects=0, timeout=5500)
        try:
            directory.check_throttling(reply)
            if reply.status != 200 or reply.url != target:
                continue
            body = reply.body()
            if len(body) > 2_000_000:
                continue
            row = directory.project(json.loads(body))
            if row["folder_id"] != folder or any(not old.get(k) or
                    directory.normalized(old[k]) != directory.normalized(row.get(k) or "")
                    for k in ("first_name", "last_name")):
                continue
            rows[folder] = {**row, "observed_at": time.time()}
            save()
        finally:
            reply.dispose()
