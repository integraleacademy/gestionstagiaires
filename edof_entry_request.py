"""Declare a confirmed entry using the same status operation as the EDOF form."""
import datetime as dt
import json
from urllib.parse import urlsplit
from uuid import uuid4

import edof_directory as directory
from edof_declarations import begin_send, is_recorded, verify_identity


def run_entry(context, witness, spec, storage, origin, prefix):
    folder = spec["folder_id"]
    intent = spec["intent"]
    if (spec["mode"] not in {"declare", "reconcile"} or intent["action"] != "entry_training"
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
    if spec["mode"] == "reconcile":
        return {"code": "declaration_unverified"}
    if directory.normalized(current["state"]) not in {"accepted", "accepte"}:
        return {"code": "declaration_changed"}
    payload = {"state": "IN_TRAINING", "date": dt.date.fromisoformat(intent["actual_date"]).strftime("%d/%m/%Y")}
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
        if status in {400, 401, 403, 404, 422} and fresh["state"] == current["state"]:
            return {"code": "declaration_refused"}
    return {"code": "declaration_unverified"}
