"""Use the status operation sent by the official EDOF entry and full-completion forms."""
import datetime as dt
import json
from urllib.parse import urlsplit
from uuid import uuid4

import edof_directory as directory
from edof_declarations import begin_send, is_recorded, official_terms_match, verify_identity


def run_entry(context, witness, spec, storage, origin, prefix):
    if spec["intent"]["action"] != "entry_training":
        return {"code": "declaration_changed"}
    return _run_status(context, witness, spec, storage, origin, prefix)


def full_completion(intent):
    return (intent.get("action") == "service_done" and type(intent.get("rate")) is int
            and intent["rate"] == 100 and not intent.get("exit_confirmed")
            and not intent.get("pilot_ticket"))


def run_full_completion(context, witness, spec, storage, origin, prefix):
    if not full_completion(spec["intent"]):
        return {"code": "declaration_changed"}
    return _run_status(context, witness, spec, storage, origin, prefix)


def _run_status(context, witness, spec, storage, origin, prefix):
    folder = spec["folder_id"]
    intent = spec["intent"]
    entry = intent["action"] == "entry_training"
    if (spec["mode"] not in {"declare", "reconcile"}
            or not directory.ID_RE.fullmatch(folder) or not witness or witness.method != "GET"):
        return {"code": "declaration_changed"}
    source = urlsplit(witness.url)
    workspace = f"/edof-api/v1/api/private/siret/{directory.SIRET}/"
    if (source.scheme != "https" or source.netloc != origin or not source.path.startswith(workspace)
            or prefix != workspace + "organisms/current/registration-folders/"):
        return {"code": "declaration_changed"}

    target = f"https://{origin}{prefix}{folder}"
    headers = directory.private_headers(witness)

    def options():
        return dict(headers={**headers, "Current-Siret": directory.SIRET, "X-RequestID": str(uuid4())},
                    max_redirects=0, timeout=12000)

    def read():
        response = context.request.get(target, **options())
        try:
            directory.check_throttling(response)
            if response.url != target or response.status != 200:
                return None
            body = response.body()
            if len(body) > 2_000_000:
                return None
            raw = json.loads(body)
            row = directory.project(raw)
            info = raw.get("trainingActionInfo") or {}
            # Contract dates and actual entry are independent values on the dossier.
            row["session_start_date"] = directory.session_date(info.get("sessionStartDate"))
            row["session_end_date"] = directory.session_date(info.get("sessionEndDate"))
            row["start_date"] = directory.session_date(raw.get("beginDate"))
            row["end_date"] = directory.session_date(raw.get("endDate"))
            row["completion_rate"] = info.get("trainingCompletionRate")
            row["duration_hours"] = info.get("indicativeDuration")
            return row
        except (ValueError, TypeError):
            return None
        finally:
            response.dispose()

    current = read()
    if current is None:
        return {"code": "declaration_unverified" if spec["mode"] == "reconcile" else "declaration_read_unavailable"}
    if not verify_identity(current, spec):
        return {"code": "declaration_changed"}
    if is_recorded(current, intent):
        return {"code": "declaration_confirmed", "confirmed_state": current["state"]}
    state = directory.normalized(current["state"])
    already_out = not entry and state in {"terminated", "sortie declaree"}
    if spec["mode"] == "reconcile":
        if already_out and current["end_date"] == intent["actual_date"]:
            return {"code": "declaration_exit_confirmed"}
        return {"code": "declaration_unverified"}
    if not official_terms_match(current, intent):
        return {"code": "declaration_terms_mismatch"}
    if already_out:
        # An existing exit uses the portal's remaining service-only form.
        return None
    date = dt.date.fromisoformat(intent["actual_date"]).strftime("%d/%m/%Y")
    if entry:
        if state not in {"accepted", "accepte"}:
            return {"code": "declaration_changed"}
        payload = {"state": "IN_TRAINING", "date": date}
    else:
        if (state not in {"intraining", "in training", "en formation", "entree declaree"}
                or not current["start_date"] or current["start_date"] > intent["actual_date"]
                or not current["session_start_date"] <= intent["actual_date"] <= current["session_end_date"]):
            return {"code": "declaration_changed"}
        from edof_declaration_form import completion_hours_match
        if not completion_hours_match(intent, current):
            return {"code": "declaration_evidence_changed"}
        # The current portal sends both the exit and the full service in this one PUT.
        payload = {"state": "TERMINATED", "terminatedDate": date, "completed": True,
                   "achievementRate": 100, "terminatedReason": "8", "forceMajeureAbsence": False,
                   "absenceUnit": "", "absenceDuration": 0}
    # Reserve at the same durable boundary as the form. Once claimed, a timeout
    # or process restart permits only a GET until the result can be reconciled.
    if not begin_send(storage, spec):
        return {"code": "declaration_blocked"}
    response = context.request.put(target + "/status", data=payload, **options())
    try:
        directory.check_throttling(response)
        if response.url != target + "/status":
            return {"code": "declaration_unverified"}
        status = response.status
    finally:
        response.dispose()
    fresh = read()
    if fresh and verify_identity(fresh, spec):
        if is_recorded(fresh, intent):
            return {"code": "declaration_confirmed", "confirmed_state": fresh["state"]}
        if (not entry and directory.normalized(fresh["state"]) in {"terminated", "sortie declaree"}
                and fresh["end_date"] == intent["actual_date"]):
            return {"code": "declaration_exit_confirmed"}
        if status in {400, 401, 403, 404, 422} and fresh["state"] == current["state"]:
            return {"code": "declaration_refused"}
    return {"code": "declaration_unverified"}
