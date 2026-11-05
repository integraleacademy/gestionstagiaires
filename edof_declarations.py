"""Durable, one-per-folder/action declarations and verified EDOF receipts."""
from contextlib import closing
import datetime as dt
import json
import time
import uuid

from zoneinfo import ZoneInfo

from cpf_entry_pilot import blocks_pilot
from cpf_provider import ProviderStore, on_production_service
import edof_automation_audit as audit

from edof_directory import FIRST_SESSION, dated_snapshot, normalized
from edof_readonly_test import ID_RE
from edof_schedule import paper_entry, scheduled_at

MOTIFS = {
    "trainee_absent": "Absence ou abandon du stagiaire sans force majeure",
    "trainee_force": "Force majeure du stagiaire",
    "provider_postponed": "Interruption par l’organisme avec proposition de report",
    "provider_stopped": "Interruption par l’organisme sans proposition de report",
}
LABELS = {
    "queued": "En attente de transmission", "sending": "Envoi effectué ou en cours de vérification",
    "uncertain": "Réception à vérifier", "review": "À vérifier dans Gestion Stagiaires",
    "confirmed": "Enregistrée dans EDOF", "paused": "Suspendue après un changement de système",
}
REASONS = {
    "declaration_refused": "EDOF a refusé la déclaration. Son statut initial a été vérifié sur le dossier.",
    "declaration_form_changed": "Le formulaire renvoyé par EDOF ne correspond pas à l’opération demandée.",
    "declaration_read_unavailable": "EDOF n’a pas renvoyé la fiche. L’entrée est en attente. Une nouvelle lecture est prévue dans 15 minutes.",
    "declaration_changed": "Le statut, l’identité ou les dates du dossier ont changé sur EDOF.",
    "declaration_unverified": "La relecture du dossier ne confirme pas encore toutes les valeurs.",
    "declaration_blocked": "Un blocage a été enregistré pour ce dossier.",
    "declaration_evidence_changed": "Le justificatif de production a changé ou n’est plus disponible.",
}


def database(directory):
    db = ProviderStore(directory).connect()
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_declarations (
        folder TEXT NOT NULL, action TEXT NOT NULL, token TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
        revision INTEGER NOT NULL, actor TEXT NOT NULL, intent TEXT NOT NULL, status TEXT NOT NULL,
        created REAL NOT NULL, changed REAL NOT NULL, detail TEXT NOT NULL DEFAULT '',
        checks INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(folder,action))""")
    db.execute("CREATE TABLE IF NOT EXISTS edof_folder_holds(folder TEXT PRIMARY KEY)")
    audit.install_declarations(db)
    return db


def hold_folder(directory, folder, held):
    with closing(database(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if held:
            if db.execute("SELECT 1 FROM cpf_declarations WHERE folder=? AND status IN ('sending','uncertain')", (folder,)).fetchone():
                raise ValueError("Un envoi est déjà parti. Vérifiez sa réception dans cette fiche.")
            db.execute("INSERT OR IGNORE INTO edof_folder_holds VALUES(?)", (folder,))
            db.execute("UPDATE cpf_declarations SET status='paused', detail='declaration_blocked' WHERE folder=? AND status='queued'", (folder,))
        else:
            db.execute("DELETE FROM edof_folder_holds WHERE folder=?", (folder,))


def folder_holds(directory):
    with closing(database(directory)) as db:
        return {r[0] for r in db.execute("SELECT folder FROM edof_folder_holds")}


def records(directory, folder=None):
    with closing(database(directory)) as db:
        rows = db.execute("SELECT * FROM cpf_declarations WHERE folder=? ORDER BY created", (folder,)
                          ) if folder else db.execute("SELECT * FROM cpf_declarations ORDER BY changed DESC")
        return [{**dict(row), "intent": json.loads(row["intent"])} for row in rows]


def enqueue(directory, owner, revision, row, draft, actor, *, automatic=False):
    folder, action = row["folder_id"], draft["action"]
    if not ID_RE.fullmatch(folder) or action not in {"entry_training", "service_done"}:
        raise ValueError("Opération EDOF inconnue.")
    if not all(row.get(k) for k in ("first_name", "last_name", "session_start_date", "session_end_date")):
        raise ValueError("L’identité et les deux dates de session doivent être connues.")
    if row["session_start_date"] < FIRST_SESSION:
        raise ValueError("La session est antérieure au 1er janvier 2026.")
    date = dt.date.fromisoformat(draft["actual_date"])
    if not row["session_start_date"] <= date.isoformat() <= row["session_end_date"] or date > dt.datetime.now(ZoneInfo("Europe/Paris")).date():
        raise ValueError("Vérifiez la date de la déclaration.")
    if draft.get("source") == "edof_schedule":
        from integrale_edof_dashboard import category
        start = row["session_start_date"]
        if not (automatic and category(row) == "accepted" and paper_entry(action, start)
                and date.isoformat() == start and scheduled_at(action, start) <= dt.datetime.now(ZoneInfo("Europe/Paris"))):
            raise ValueError("Cette entrée automatique doit être échue et correspondre au dossier CPF accepté.")
    elif not (draft.get("evidence") or draft.get("operator_confirmed") is True):
        raise ValueError("Confirmez la réalisation de la formation.")
    if action == "service_done" and (type(draft.get("rate")) is not int or not 0 <= draft["rate"] <= 100 or (draft["rate"] < 100 and draft.get("motif") not in MOTIFS)):
        raise ValueError("Confirmez la réalisation et, pour une sortie, le taux et le motif éventuel.")
    stamp = time.time()
    intent = {**{k: row[k]
                 for k in ("first_name", "last_name", "session_start_date", "session_end_date")},
              "title": row.get("title", ""), **draft}
    with closing(database(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM edof_folder_holds WHERE folder=?", (folder,)).fetchone():
            if automatic:
                return "paused"
            raise ValueError("L’automatisation est bloquée sur ce dossier.")
        old = db.execute("SELECT * FROM cpf_declarations WHERE folder=? AND action=?",
                         (folder, action)).fetchone()
        if old and (old["status"] in {"sending", "uncertain", "confirmed"} or (old["status"] == "queued" and old["revision"] == revision)
                    or (automatic and old["status"] == "review")):
            return old["status"]
        db.execute("""INSERT INTO cpf_declarations(folder,action,token,owner,revision,actor,intent,status,created,changed)
            VALUES(?,?,?,?,?,?,?,'queued',?,?) ON CONFLICT(folder,action) DO UPDATE SET
            token=excluded.token, owner=excluded.owner, revision=excluded.revision, actor=excluded.actor,
            intent=excluded.intent,status='queued',changed=excluded.changed, detail='',checks=0""",
                   (folder, action, uuid.uuid4().hex, owner, revision, actor, json.dumps(intent, ensure_ascii=False), stamp, stamp))
    return "queued"


def next_job(store, revision, *, provider="integrale"):
    with closing(database(store.directory)) as db, db:
        db.execute("UPDATE cpf_declarations SET status='paused',changed=? WHERE status='queued' AND revision!=?",
                   (time.time(), revision))
        db.execute("""UPDATE cpf_declarations SET status='paused',changed=?
                   WHERE status='queued' AND COALESCE(json_extract(intent,'$.session_start_date'),'') < ?""",
                   (time.time(), FIRST_SESSION))
        row = db.execute("""SELECT * FROM cpf_declarations WHERE
            (status='queued' AND revision=? AND changed<=? AND
             (json_extract(intent,'$.pilot_ticket') IS NOT NULL) = ?) OR
            (status IN ('sending','uncertain') AND checks < 3 AND changed < ?
             AND (? = 'integrale' OR json_extract(intent,'$.pilot_ticket') IS NOT NULL))
            ORDER BY CASE WHEN status='queued' THEN 1 ELSE 0 END,changed LIMIT 1""",
                         (revision, time.time(), provider == "wedof", time.time()-120, provider)).fetchone()
        if not row:
            return None
        intent = json.loads(row["intent"])
        return {"mode": "declare" if row["status"] == "queued" else "reconcile", "folder_id": row["folder"],
                "first_name": intent["first_name"], "last_name": intent["last_name"], "owner": row["owner"],
                "operation": row["token"], "revision": row["revision"], "intent": intent}


def begin_send(directory, spec):
    # The on-disk fence is committed BEFORE Chromium releases its one business request.
    # A killed browser/worker can subsequently only reconcile by reading the dossier.
    with closing(database(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        selected = ProviderStore(directory).state(db)
        ticket = spec["intent"].get("pilot_ticket") or ""
        if ticket and spec["intent"]["action"] != "entry_training":
            return False
        if selected["provider"] != ("wedof" if ticket else "integrale") or selected["pending"] or selected["revision"] != spec["revision"]:
            return False
        if spec["intent"]["session_start_date"] < FIRST_SESSION or db.execute(
                "SELECT 1 FROM edof_folder_holds WHERE folder=?", (spec["folder_id"],)).fetchone():
            return False
        row = db.execute("""UPDATE cpf_declarations SET status='sending', changed=?
            WHERE token=? AND folder=? AND revision=? AND status='queued' AND action=?
            AND COALESCE(json_extract(intent,'$.pilot_ticket'),'')=?""",
                         (time.time(), spec["operation"], spec["folder_id"], spec["revision"], spec["intent"]["action"], ticket))
        if row.rowcount and spec["intent"].get("exit_confirmed"):
            db.execute("UPDATE cpf_declarations SET intent=json_set(intent,'$.exit_confirmed',json('true')) WHERE token=?",
                       (spec["operation"],))
        return row.rowcount == 1


def complete(directory, spec, code, confirmed_state=None):
    with closing(database(directory)) as db, db:
        row = db.execute("SELECT status, json_extract(intent,'$.source') AS source FROM cpf_declarations WHERE token=?", (spec["operation"],)).fetchone()
        if not row or row["status"] in {"confirmed", "paused"}:
            return
        if code == "declaration_blocked" and row["status"] == "queued" and row["source"] == "edof_schedule":
            db.execute("UPDATE cpf_declarations SET status='paused',detail=?,changed=? WHERE token=?",
                       (code, time.time(), spec["operation"]))
            return
        if code == "declaration_exit_confirmed" and row["status"] in {"sending","uncertain"}:
            # EDOF confirms only the exit. A new token may submit only the remaining service fait.
            db.execute("""UPDATE cpf_declarations SET status='queued', token=?,checks=0, detail=?,
                       intent=json_set(intent,'$.exit_confirmed',json('true')),changed=? WHERE token=?
                       AND action='service_done' AND json_extract(intent,'$.exit_confirmed') IS NULL""",
                       (uuid.uuid4().hex, code, time.time(), spec["operation"]))
            return
        if row["status"] == "queued" and code in {"timeout","browser_error","saved_session_unavailable","authentication_unconfirmed","day_login_used","day_login_wait","day_closed","portal_throttled","declaration_read_unavailable"}:
            # No official write crossed the send fence. Retry after the sign-in cooldown.
            db.execute("UPDATE cpf_declarations SET detail=?,changed=? WHERE token=?", (code,time.time()+900,spec["operation"]))
            return
        state = ("confirmed" if code == "declaration_confirmed" else
                 "uncertain" if row["status"] in {"sending", "uncertain"} and code != "declaration_refused" else "review")
        if state == "confirmed" and confirmed_state:
            db.execute("UPDATE cpf_declarations SET intent=json_set(intent,'$.confirmed_state',?) WHERE token=?",
                       (confirmed_state, spec["operation"]))
        db.execute("UPDATE cpf_declarations SET status=?,detail=?,changed=?,checks=checks+? WHERE token=?",
                   (state, code, time.time(), int(spec["mode"] == "reconcile"), spec["operation"]))


def request_recheck(directory, folder, action):
    with closing(database(directory)) as db, db:
        return db.execute("""UPDATE cpf_declarations SET checks=0,changed=0
                          WHERE folder=? AND action=? AND status IN ('sending','uncertain')""",
                          (folder, action)).rowcount


def verify_identity(fields, spec):
    intent = spec["intent"]
    return (fields.get("folder_id") == spec["folder_id"]
            and all(normalized(fields.get(k) or "") == normalized(intent.get(k) or "") and intent.get(k)
                    for k in ("first_name", "last_name"))
            and all(fields.get(k) == intent.get(k) and intent.get(k) for k in ("session_start_date", "session_end_date")))


def is_recorded(fields, intent):
    state = normalized(fields.get("state") or "")
    completed = {"servicedonedeclared", "servicedonedeclaredrevised", "servicedonevalidated", "servicedonevalidatedrevisionvsf", "service fait declare", "service fait valide",
                 "billed", "invoiced", "paid", "facture", "paye"}
    if intent["action"] == "entry_training":
        return state in completed | {"intraining", "in training", "entree declaree", "en formation", "outoftraining", "out of training", "terminated", "sortie declaree"} and fields.get("start_date") == intent["actual_date"]
    if state not in completed or fields.get("end_date") != intent["actual_date"]:
        return False
    try:
        return float(fields["completion_rate"]) == intent["rate"]
    except (KeyError, TypeError, ValueError):
        return False


def authoritative_proofs(folders):
    if on_production_service():
        import app as legacy
        from cpf_production_evidence import read_evidence
        return read_evidence(legacy, folders, data=legacy.load_data(run_background_tasks=False))
    from cpf_provider_bridge import production_request
    reply = production_request({"folders": folders}, path="/evidence")
    if reply.get("provider") != "integrale" or not isinstance(reply.get("evidence"), dict) or any(id_ not in reply["evidence"] for id_ in folders):
        raise ValueError("La production n’a pas confirmé les justificatifs.")
    return reply["evidence"]


def pilot_state(folder, mode="inspect", **values):
    if on_production_service():
        import app as legacy
        from cpf_entry_pilot import operate_pilot
        return operate_pilot(legacy, folder, mode, **values)
    from cpf_provider_bridge import production_request
    reply = production_request({"folder": folder, "mode": mode, **values}, path="/entry-pilot")
    pilot = reply.get("pilot") or {}
    if pilot.get("error"):
        raise ValueError(pilot["error"])
    if reply.get("provider") != "wedof" or pilot.get("folder") != folder:
        raise ValueError("L’exclusion de cette entrée n’est pas confirmée par la production.")
    return pilot


def matches_pilot(row, pilot):
    return (pilot.get("available") and pilot.get("start") == row.get("session_start_date")
            and pilot.get("end") == row.get("session_end_date"))


def same_enrolment(row, proof):
    return all(row.get(k) and normalized(row[k]) == normalized(proof.get(k) or "") for k in
               ("first_name", "last_name", "session_start_date", "session_end_date"))


def matches_linked_proof(row, proof, draft):
    """Compare evidence returned for this exact CPF number to the individual EDOF period."""
    if same_enrolment(row, proof):
        return True
    # A participant can join an existing group on the first day of their CPF
    # contract. The group's earlier start alone neither proves nor disproves entry.
    start = row.get("session_start_date")
    group_start = proof.get("session_start_date")
    recorded_start = (proof.get("entry_training") or {}).get("actual_date")
    return bool(draft.get("action") == "entry_training" and start and draft.get("actual_date") == start
                and group_start and group_start < start <= (row.get("session_end_date") or "")
                and row["session_end_date"] == proof.get("session_end_date")
                and (not recorded_start or recorded_start == start)
                and all(row.get(k) and normalized(row[k]) == normalized(proof.get(k) or "")
                        for k in ("first_name", "last_name")))


def training_proof(row, proof, action):
    draft = proof.get(action) or {}
    # Older versions of the production bridge return the first completed exercise
    # as a start date. It can corroborate day one but cannot move the course date.
    if (action == "entry_training" and draft.get("actual_date") != row.get("session_start_date")
            and (draft.get("evidence") or "").startswith("Activité pédagogique enregistrée en production,")):
        return {}
    return draft


def local_proofs(store, folders):
    from types import SimpleNamespace
    from cpf_production_evidence import read_evidence
    path = getattr(store, "data_file", None)
    if not path or not folders:
        return {}
    try:
        with open(path, encoding="utf-8") as source:
            data = json.load(source)
    except FileNotFoundError:
        return {}
    return read_evidence(SimpleNamespace(DATA_FILE=path), folders, data=data)


def discover(store, owner, snapshot, *, outcomes=None):
    from integrale_edof_dashboard import ACTIONS, category, local_operations, simulate
    from cpf_provider import on_test_service
    if not (on_test_service() or on_production_service()):
        return
    selection = ProviderStore(store.directory).state()
    if selection["pending"] or selection["provider"] != "integrale":
        return
    revision = selection["revision"]
    held = folder_holds(store.directory)
    existing = {(r["folder"], r["action"]):r["status"] for r in records(store.directory)
                if r["status"] in {"confirmed","sending","uncertain","review"} or r["status"] == "queued" and r["revision"] == revision}

    report = dict(entry_training=0, service_done=0, existing=0, blocked=0, missing=0, review=0)

    def record(folder, action, bucket, outcome):
        report[bucket] += 1
        if outcomes is not None:
            outcomes[folder] = (action, outcome)
        if outcome in {"blocked", "missing", "review"}:
            audit.decision(store.directory, owner, snapshot["rows"][folder], action, outcome)

    now = dt.datetime.now(ZoneInfo("Europe/Paris"))
    due = {}
    for folder, row in dated_snapshot(snapshot)["rows"].items():
        kind = category(row)
        if kind not in ACTIONS:
            continue
        date = row.get("session_start_date" if kind == "accepted" else "session_end_date")
        if simulate(kind, date, False, None, now) not in {"ready", "unconfirmed"}:
            continue
        action = ACTIONS[kind]
        status = existing.get((folder, action))
        if folder in held:
            record(folder, action, "blocked", "blocked")
        elif status:
            record(folder, action, "review" if status in {"review","uncertain"} else "existing", status)
        else:
            due[folder] = (row, action)
    ids = list(due)
    local = local_proofs(store, ids)
    drafts = local_operations(ProviderStore(store.directory)) if ids else {}
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        proofs = authoritative_proofs(batch)
        for folder in batch:
            row, action = due[folder]
            proof = proofs[folder]
            local_proof = local.get(folder, {})
            if {action, "both"}.intersection([*proof.get("blocks", []), *local_proof.get("blocks", [])]):
                record(folder, action, "blocked", "blocked")
                continue
            remote_draft = training_proof(row, proof, action)
            local_draft = training_proof(row, local_proof, action)
            saved = drafts.get(folder, {}).get("draft") or {}
            if paper_entry(action, row.get("session_start_date")):
                draft = {"action": action, "actual_date": row["session_start_date"], "source": "edof_schedule"}
            elif saved.get("source") == "admin" and saved.get("action") == action:
                if (not same_enrolment(row, saved) or (proof.get("first_name") and not matches_linked_proof(row, proof, saved))
                        or (saved.get("rate", 100) < 100 and saved.get("motif") not in MOTIFS)):
                    record(folder, action, "review", "review")
                    continue
                draft = saved
            elif remote_draft and matches_linked_proof(row, proof, remote_draft):
                draft = remote_draft
            elif (not remote_draft and local_draft and matches_linked_proof(row, local_proof, local_draft)
                  and (not proof.get("first_name") or matches_linked_proof(row, proof, local_draft))):
                draft = {**local_draft, "source":"local"}
            else:
                record(folder, action, "missing", "missing")
                continue
            try:
                status = enqueue(store.directory, owner, revision, row, draft, "Gestion Stagiaires", automatic=True)
            except ValueError:
                record(folder, action, "review", "review")
                continue
            if status == "queued":
                record(folder, action, action, status)
            elif status == "paused":
                record(folder, action, "blocked", "blocked")
            else:
                record(folder, action, "review" if status in {"review","uncertain"} else "existing", status)
    return report


def check_before_job(store, spec):
    from cpf_provider import on_test_service
    if spec["mode"] != "declare":
        return True
    folder, action = spec["folder_id"], spec["intent"]["action"]
    if store.data_file:
        with open(store.data_file, encoding="utf-8") as source:
            data = json.load(source)
        if any(isinstance(b, dict) and b.get("active") and str(b.get("external_id")) == folder and
               b.get("action") in (action, "both") and
                   blocks_pilot(b, spec["intent"].get("pilot_ticket")) for b in data.get("wedof_automation_blocks", [])):
            complete(store.directory, spec, "declaration_blocked")
            return False
    if on_test_service() or on_production_service():
        ticket = spec["intent"].get("pilot_ticket")
        if ticket:
            pilot = pilot_state(folder)
            intent = spec["intent"]
            if (action != "entry_training" or not matches_pilot(intent, pilot) or not pilot.get("reserved")
                    or pilot.get("ticket") != ticket):
                complete(store.directory, spec, "declaration_blocked")
                return False
            proof = pilot.get("proof") or {}
            if intent.get("source") == "production" and (not same_enrolment(intent, proof)
                    or not proof.get(action) or any(intent.get(k) != v for k, v in proof[action].items())):
                complete(store.directory, spec, "declaration_evidence_changed")
                return False
            claimed = pilot_state(folder, "claim", operation=ticket)
            if claimed.get("operation") != ticket or not claimed.get("reserved") or not matches_pilot(intent, claimed):
                complete(store.directory, spec, "declaration_blocked")
                return False
            return True
        proof = authoritative_proofs([folder])[folder]
        if {action, "both"}.intersection(proof.get("blocks", [])):
            complete(store.directory, spec, "declaration_blocked")
            return False
        source = spec["intent"].get("source")
        if spec["intent"].get("operator_confirmed") and proof.get("first_name") and not matches_linked_proof(spec["intent"], proof, spec["intent"]):
            complete(store.directory,spec,"declaration_changed")
            return False
        if source == "admin":
            from integrale_edof_dashboard import local_operations
            current = local_operations(ProviderStore(store.directory)).get(folder, {}).get("draft") or {}
            if (not same_enrolment(spec["intent"],current) or any(spec["intent"].get(k) != v for k,v in current.items())
                    or proof.get("first_name") and not matches_linked_proof(spec["intent"], proof, spec["intent"])):
                complete(store.directory, spec, "declaration_evidence_changed")
                return False
        if source in {"production", "local"}:
            if source == "local":
                if training_proof(spec["intent"],proof,action) or (proof.get("first_name") and not matches_linked_proof(spec["intent"], proof, spec["intent"])):
                    complete(store.directory, spec, "declaration_evidence_changed")
                    return False
                proof = local_proofs(store, [folder]).get(folder, {})
            current = training_proof(spec["intent"], proof, action)
            if current and source == "local":
                current = {**current, "source":"local"}
            if not matches_linked_proof(spec["intent"], proof, spec["intent"]) or not current or any(spec["intent"].get(k) != v for k, v in current.items()):
                complete(store.directory, spec, "declaration_evidence_changed")
                return False
    return True
