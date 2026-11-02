"""Reserve a single CPF entry on the production disk while WeDoF remains active."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
from uuid import uuid4
from zoneinfo import ZoneInfo

from cpf_provider import ProviderUnavailable

ACTION = "entry_training"
PILOT = "integrale_entry"


@contextmanager
def automation_lock(legacy):
    # A running WeDoF cron may already have taken a snapshot of the dossier.
    with open(legacy.WEDOF_AUTOMATION_LOCK_FILE, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProviderUnavailable("Le traitement WeDoF est en cours. Réessayez après sa fin.") from None
        yield


def active_holds(data, folder):
    return [b for b in data.get("wedof_automation_blocks", []) if isinstance(b, dict)
            and b.get("external_id") == folder and b.get("active") and b.get("action") in (ACTION, "both")]


def snapshot(data, folder):
    status = next((s for s in data.get("wedof_automation_status", []) if isinstance(s, dict)
                   and str(s.get("external_id")) == folder), {})
    holds = active_holds(data, folder)
    ours = next((b for b in holds if b.get("source") == PILOT and b.get("action") == ACTION), {})
    attempts = [a for a in data.get("wedof_automation_actions", []) if isinstance(a, dict)
                and str(a.get("external_id")) == folder and a.get("action") == ACTION]
    uncertain_or_sent = any(a.get("status") in {"processing", "uncertain_after_timeout", "success", "already_done"}
                            for a in attempts)
    entry = status.get(ACTION) or {}
    return {"folder": folder, "state": status.get("wedof_state"), "start": status.get("wedof_date_start"),
            "end": status.get("wedof_date_end"), "hour": entry.get("planned_time"),
            "available": status.get("wedof_state") == "accepted" and str(status.get("wedof_type")).lower() == "cpf"
            and entry.get("status") not in {"success", "already_done", "executed"} and not uncertain_or_sent
            and not any(b is not ours for b in holds),
            "reserved": bool(ours), "ticket": ours.get("pilot_ticket", ""), "operation": ours.get("pilot_operation", "")}


def change(data, folder, mode, actor, operation=""):
    state = snapshot(data, folder)
    ours = next((b for b in active_holds(data, folder) if b.get("source") == PILOT), None)
    if mode == "release":
        if not ours or state["operation"]:
            raise ValueError("Une entrée en cours de vérification ne peut pas être rendue à WeDoF.")
        ours.update(active=False, updated_at=datetime.now(ZoneInfo("Europe/Paris")).isoformat())
    elif not state["available"]:
        raise ValueError("WeDoF ne confirme pas une entrée disponible pour ce dossier.")
    elif mode == "reserve" and not ours:
        now = datetime.now(ZoneInfo("Europe/Paris")).isoformat()
        data.setdefault("wedof_automation_blocks", []).append({
            "id": "WBLOCK-" + uuid4().hex[:12], "external_id": folder, "action": ACTION, "active": True,
            "source": PILOT, "reason_code": "other", "comment": "Entrée réservée à Intégrale EDOF",
            "created_at": now, "updated_at": now, "actor": actor, "pilot_ticket": uuid4().hex})
    elif mode == "claim":
        if not ours or state["ticket"] != operation or state["operation"] not in ("", operation):
            raise ValueError("L’exclusion WeDoF de cette entrée n’est pas confirmée.")
        ours["pilot_operation"] = operation
    return data


def register_pilot(legacy, bp, store, public_state, folder_pattern):
    from flask import g, jsonify, request
    from cpf_production_evidence import read_evidence
    from cpf_provider import provider_operation

    @bp.post("/entry-pilot")
    def entry_pilot():
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(error="invalid_request"), 400
        folder, mode = body.get("folder"), body.get("mode")
        operation, actor = body.get("operation", ""), body.get("actor", "")
        if (not isinstance(folder, str) or not folder_pattern.fullmatch(folder)
                or mode not in ("inspect", "reserve", "claim", "release")
                or not isinstance(actor, str) or len(actor) > 254
                or mode == "claim" and (not isinstance(operation, str) or len(operation) != 32
                                        or any(c not in "0123456789abcdef" for c in operation))):
            return jsonify(error="invalid_request"), 400
        with provider_operation("wedof"):
            if mode == "inspect":
                data = legacy.load_data(run_background_tasks=False)
            else:
                try:
                    with automation_lock(legacy):
                        data = legacy._atomic_update_data(lambda current: change(current, folder, mode, actor, operation))
                except ProviderUnavailable:
                    raise
                except ValueError as exc:
                    return jsonify(**public_state(store.state()), pilot={"error": str(exc)}), 200
            state = snapshot(data, folder)
            if mode == "inspect":
                proof = read_evidence(legacy, [folder], data=data)[folder]
                state["proof"] = {key: value for key, value in proof.items() if key in
                                  ("first_name", "last_name", "session_start_date", "session_end_date", ACTION)}
            return jsonify(**public_state(store.state()), pilot=state)

    @legacy.app.before_request
    def protect_entry_hold():
        if request.endpoint not in {"admin_wedof_automation_unblock", "admin_wedof_automation_block"}:
            return
        from flask import session
        if not session.get("admin_logged_in") or request.form.get("action") != ACTION:
            return
        # Serialize manual changes with reserve/claim and refuse edits to the pilot-owned hold.
        lock = automation_lock(legacy)
        try:
            lock.__enter__()
        except ProviderUnavailable as exc:
            return jsonify(error=str(exc)), 409
        g.cpf_entry_lock = lock
        folder = request.form.get("external_id")
        if any(b.get("source") == PILOT for b in active_holds(legacy.load_data(run_background_tasks=False), folder)):
            return jsonify(error="Cette entrée est réservée. Gérez sa réservation sur la fiche Intégrale EDOF."), 409

    @legacy.app.teardown_request
    def release_manual_lock(error):
        lock = g.pop("cpf_entry_lock", None)
        if lock is not None:
            lock.__exit__(None, None, None)
