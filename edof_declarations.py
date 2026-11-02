"""Durable, one-per-folder/action declarations and verified EDOF receipts."""
from contextlib import closing
import datetime as dt
import json
import time
import uuid

from zoneinfo import ZoneInfo

from cpf_provider import ProviderStore

from edof_directory import normalized
from edof_readonly_test import ID_RE

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
    return db


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
    date = dt.date.fromisoformat(draft["actual_date"])
    if not row["session_start_date"] <= date.isoformat() <= row["session_end_date"] or date > dt.datetime.now(ZoneInfo("Europe/Paris")).date():
        raise ValueError("Vérifiez la date de la déclaration.")
    if not draft.get("evidence") or (action == "service_done" and (type(draft.get("rate")) is not int or not 0 <= draft["rate"] <= 100 or (draft["rate"] < 100 and draft.get("motif") not in MOTIFS))):
        raise ValueError("Vérifiez le justificatif, le taux et le motif de sortie.")
    stamp = time.time()
    intent = {**{k: row[k]
                 for k in ("first_name", "last_name", "session_start_date", "session_end_date")}, **draft}
    with closing(database(directory)) as db, db:
        db.execute("BEGIN IMMEDIATE")
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
        row = db.execute("""SELECT * FROM cpf_declarations WHERE
            (status='queued' AND revision=? AND
             (json_extract(intent,'$.pilot_ticket') IS NOT NULL) = ?) OR
            (status IN ('sending','uncertain') AND checks < 3 AND changed < ?
             AND (? = 'integrale' OR json_extract(intent,'$.pilot_ticket') IS NOT NULL))
            ORDER BY CASE WHEN status='queued' THEN 1 ELSE 0 END,changed LIMIT 1""",
                         (revision, provider == "wedof", time.time()-120, provider)).fetchone()
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
        row = db.execute("""UPDATE cpf_declarations SET status='sending', changed=?
            WHERE token=? AND folder=? AND revision=? AND status='queued' AND action=?
            AND COALESCE(json_extract(intent,'$.pilot_ticket'),'')=?""",
                         (time.time(), spec["operation"], spec["folder_id"], spec["revision"], spec["intent"]["action"], ticket))
        return row.rowcount == 1


def complete(directory, spec, code, confirmed_state=None):
    with closing(database(directory)) as db, db:
        row = db.execute("SELECT status FROM cpf_declarations WHERE token=?", (spec["operation"],)).fetchone()
        if not row or row["status"] in {"confirmed", "paused"}:
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
    completed = {"servicedonedeclared", "servicedonevalidated", "service fait declare", "service fait valide",
                 "billed", "invoiced", "paid", "facture", "paye"}
    if intent["action"] == "entry_training":
        return state in completed | {"intraining", "entree declaree", "en formation", "outoftraining", "sortie declaree"} and fields.get("start_date") == intent["actual_date"]
    if state not in completed or fields.get("end_date") != intent["actual_date"]:
        return False
    try:
        return float(fields["completion_rate"]) == intent["rate"]
    except (KeyError, TypeError, ValueError):
        return False


def authoritative_proofs(folders):
    from cpf_provider_bridge import production_request
    reply = production_request({"folders": folders}, path="/evidence")
    if reply.get("provider") != "integrale" or not isinstance(reply.get("evidence"), dict) or any(id_ not in reply["evidence"] for id_ in folders):
        raise ValueError("La production n’a pas confirmé les justificatifs.")
    return reply["evidence"]


def pilot_state(folder, mode="inspect", **values):
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


def discover(store, owner, snapshot):
    from integrale_edof_dashboard import ACTIONS, category, simulate
    from cpf_provider import on_test_service
    if not on_test_service():
        return
    revision = ProviderStore(store.directory).state()["revision"]
    now = dt.datetime.now(ZoneInfo("Europe/Paris"))
    due = {}
    for folder, row in snapshot["rows"].items():
        kind = category(row)
        if kind not in ACTIONS:
            continue
        date = row.get("session_start_date" if kind == "accepted" else "session_end_date")
        if simulate(kind, date, False, None, now) == "unconfirmed":
            due[folder] = (row, ACTIONS[kind])
    ids = list(due)
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        proofs = authoritative_proofs(batch)
        for folder in batch:
            row, action = due[folder]
            proof = proofs[folder]
            draft = proof.get(action)
            if draft and not {action, "both"}.intersection(proof.get("blocks", [])) and same_enrolment(row, proof):
                enqueue(store.directory, owner, revision, row, draft, "Gestion Stagiaires", automatic=True)


def check_before_job(store, spec):
    from cpf_provider import on_test_service
    if spec["mode"] != "declare":
        return True
    folder, action = spec["folder_id"], spec["intent"]["action"]
    if store.data_file:
        with open(store.data_file, encoding="utf-8") as source:
            data = json.load(source)
        if any(isinstance(b, dict) and b.get("active") and str(b.get("external_id")) == folder and
               b.get("action") in (action, "both") for b in data.get("wedof_automation_blocks", [])):
            complete(store.directory, spec, "declaration_blocked")
            return False
    if on_test_service():
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
        if spec["intent"].get("source") == "production":
            current = proof.get(action, {})
            if not same_enrolment(spec["intent"], proof) or not current or any(spec["intent"].get(k) != v for k, v in current.items()):
                complete(store.directory, spec, "declaration_evidence_changed")
                return False
    return True
