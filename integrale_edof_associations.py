"""Local CPF associations from synchronized Intégrale EDOF dossiers."""
from collections import defaultdict
from contextlib import closing
import json

from edof_directory import accepted_key, email_proof, normalized, pending_key, record_key, session_date
from edof_gmail import Vault
from wedof_links import save_manual_wedof_link
from wedof_matching import match_folder


def observed_rows(store, owner, snapshot):
    """Only reuse a detail's contact for the same dossier and verified identity."""
    rows = dict((snapshot or {}).get("rows", {}))
    if not rows:
        return rows
    with closing(store.connect()) as db:
        reads = db.execute("""SELECT result FROM jobs WHERE owner=? AND mode='read'
                           AND json_extract(result,'$.code')='read_success' ORDER BY finished DESC""", (owner,))
        seen = set()
        for item in reads:
            fields = json.loads(item[0]).get("fields", {})
            folder = fields.get("folder_id")
            if folder in seen or folder not in rows:
                continue
            seen.add(folder)
            row = rows[folder]
            if all(fields.get(k) and normalized(fields[k]) == normalized(row.get(k) or "")
                   for k in ("first_name", "last_name")):
                rows[folder] = {**row, "email": fields.get("email") or row.get("email", "")}
    return rows


def eligible_groups(data, partner_id, is_cancelled, *, include_cancelled=False):
    for group in data.get("sessions", []):
        if (group.get("partner_id") or partner_id) != partner_id:
            continue
        trainees = group.get("trainees", group.get("stagiaires", [])) or []
        yield {**group, "trainees": [t for t in trainees if isinstance(t, dict) and (include_cancelled or not is_cancelled(t))]}


def verified_email(row, trainees, key):
    proof = row.get("email_proof")
    if proof:
        for trainee in trainees:
            email = trainee.get("email") or trainee.get("mail")
            if email_proof(key, row["folder_id"], email) == proof:
                return email
        return ""  # The directory's verified contact supersedes older detail reads.
    return row.get("email") or ""


def match_unlinked(data, rows, partner_id, is_cancelled, as_folder, key):
    links = [l for l in data.get("wedof_links", []) if isinstance(l, dict)]
    attached = {str(l["external_id"]) for l in links if l.get("active") and l.get("external_id")}
    occupied = {(str(l.get("session_id")), str(l.get("trainee_id"))) for l in links if l.get("active")}
    corrected = {(str(l.get("external_id")), str(l.get("session_id")), str(l.get("trainee_id")))
                 for l in links if not l.get("active") and any(h.get("source") == "manual_correction"
                 for h in l.get("association_history", []) if isinstance(h, dict))}
    by_dates = defaultdict(list)
    for group in eligible_groups(data, partner_id, is_cancelled):
        dates = (session_date(group.get("date_start") or group.get("date_debut")),
                 session_date(group.get("date_end") or group.get("date_fin")))
        by_dates[dates].append(group)
    results = {}
    exact = defaultdict(list)
    for folder, row in rows.items():
        if folder in attached:
            continue
        dates = row.get("session_start_date"), row.get("session_end_date")
        candidates = by_dates.get(dates, ())
        trainees = (t for group in candidates for t in group["trainees"])
        match = match_folder({**as_folder(row), "email": verified_email(row, trainees, key)}, candidates)
        results[folder] = match
        if match["status"] == "exact_match":
            pair = match["session_id"], match["trainee_id"]
            exact[pair].append(match)
    for pair, matches in exact.items():
        for match in matches:
            if len(matches) > 1 or pair in occupied or (match["external_id"], *pair) in corrected:
                match.update(status="ambiguous_match", explanation="Association à vérifier manuellement.")
    return results


def synchronize(data, matches):
    created = 0
    for match in matches.values():
        if match["status"] != "exact_match":
            continue
        result = save_manual_wedof_link(data, external_id=match["external_id"], session_id=match["session_id"],
                    trainee_id=match["trainee_id"], state=match["state"], date_start=match["start_date"],
                    date_end=match["end_date"])
        if result == "created":
            data["wedof_links"][-1].update(source="automatic_exact_match", matching_rule=match["rule"],
                                           provider="integrale")
            created += 1
    return created


def snapshot_owners(private):
    owners = set()
    with private.connect() as db:
        for prefix in (record_key(""), accepted_key(""), pending_key("")):
            owners.update(r[0][len(prefix):] for r in db.execute(
                "SELECT name FROM private_records WHERE name GLOB ?", (prefix + "*",)))
    return owners


def nightly(store, now, snapshot, reconcile):
    """Called by the elected production scheduler. Replays after a restart are idempotent."""
    day = now.date().isoformat()
    if now.hour < 18 or not store.connector_key:
        return False
    with closing(store.connect()) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS edof_association_runs
                   (day TEXT PRIMARY KEY, examined INTEGER NOT NULL, created INTEGER NOT NULL)""")
        if db.execute("SELECT 1 FROM edof_association_runs WHERE day=?", (day,)).fetchone():
            return True
    # Dossiers synchronized manually also participate when the browser watch is closed.
    private = Vault(store.directory, store.connector_key)
    owners = snapshot_owners(private)
    combined, stamps = {}, {}
    available = False
    for owner in owners:
        saved = snapshot(owner)
        if not saved:
            continue
        available = True
        for folder, row in observed_rows(store, owner, saved).items():
            stamp = row.get("observed_at") or saved.get("checked") or 0
            if folder not in stamps or stamp >= stamps[folder]:
                combined[folder], stamps[folder] = row, stamp
    if not available:
        return False
    examined, created = reconcile(combined)
    with closing(store.connect()) as db, db:
        db.execute("INSERT OR IGNORE INTO edof_association_runs VALUES(?,?,?)", (day, examined, created))
    return True
