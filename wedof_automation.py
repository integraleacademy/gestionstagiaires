"""Planificateur WEDOF en lecture seule (dry-run exclusivement)."""

import datetime as dt
import logging
import os
import uuid
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from wedof_matching import extract_folder, normalize_date

PARIS_TZ = ZoneInfo("Europe/Paris")
AUTOMATABLE_STATES = {"accepted", "inTraining"}
SERVICE_DONE_STATES = {"serviceDoneDeclared", "serviceDoneValidated"}
ALL_STATES = ("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated")
RUN_HISTORY_LIMIT = 100
MAINTENANCE_TIMEZONE = "Europe/Paris"
MAINTENANCE_START_DEFAULT = "05:00"
MAINTENANCE_END_DEFAULT = "07:00"
logger = logging.getLogger(__name__)


def _maintenance_enabled() -> bool:
    """La fenêtre reste active sauf désactivation explicite."""
    value = os.environ.get("WEDOF_MAINTENANCE_WINDOW_ENABLED")
    return value is None or value.strip().casefold() not in {"false", "0", "no", "off"}


def _maintenance_time(name: str, default: str) -> tuple[dt.time, str]:
    value = (os.environ.get(name) or default).strip()
    try:
        if len(value) != 5:
            raise ValueError
        parsed = dt.datetime.strptime(value, "%H:%M").time()
        return parsed, value
    except (TypeError, ValueError):
        logger.warning("Configuration de fenêtre WEDOF invalide variable=%s; valeur par défaut appliquée", name)
        return dt.datetime.strptime(default, "%H:%M").time(), default


def is_wedof_maintenance_window(now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Retourne la configuration et indique si l'heure de Paris est suspendue.

    La borne de début est incluse et celle de fin exclue. Une fenêtre dont le
    début est postérieur à la fin traverse minuit.
    """
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    current = current.astimezone(PARIS_TZ)
    start, start_text = _maintenance_time("WEDOF_MAINTENANCE_START_TIME", MAINTENANCE_START_DEFAULT)
    end, end_text = _maintenance_time("WEDOF_MAINTENANCE_END_TIME", MAINTENANCE_END_DEFAULT)
    local_time = current.time().replace(tzinfo=None)
    in_range = (start <= local_time < end) if start < end else (
        local_time >= start or local_time < end) if start > end else False
    return {"active": _maintenance_enabled() and in_range, "start_time": start_text,
            "end_time": end_text, "timezone": MAINTENANCE_TIMEZONE}


def record_maintenance_skip(data: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Enregistre uniquement le run technique, sans toucher aux instantanés métier."""
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    current = current.astimezone(PARIS_TZ)
    window = is_wedof_maintenance_window(current)
    timestamp = current.isoformat()
    run = {"run_id": "WRUN-" + uuid.uuid4().hex[:12].upper(), "started_at": timestamp,
           "finished_at": timestamp, "mode": "dry_run", "status": "skipped_maintenance_window",
           "technical_error": None}
    data["wedof_automation_runs"] = (data.get("wedof_automation_runs", []) + [run])[-RUN_HISTORY_LIMIT:]
    return {"ok": True, "partial": False, "status": "skipped_maintenance_window", "mode": "dry_run",
            "maintenance_window": {key: window[key] for key in ("start_time", "end_time", "timezone")}}


def automation_dashboard_state(data: Dict[str, Any]) -> str:
    """Qualifie la fiabilité de l'instantané persistant, sans déduire WEDOF des liens locaux."""
    runs = [run for run in data.get("wedof_automation_runs", []) if isinstance(run, dict)]
    sync_states = (data.get("wedof_automation_sync") or {}).get("states") or {}
    has_success = any(run.get("status") in {"success", "partial_success"} for run in runs)
    has_success = has_success or any(
        isinstance(state, dict) and bool(state.get("last_success_at"))
        for state in sync_states.values()
    )
    if not has_success:
        return "never_synchronized"
    last_status = runs[-1].get("status") if runs else None
    if last_status == "skipped_maintenance_window":
        return "maintenance_skipped"
    if last_status == "partial_success":
        return "partial_sync"
    if last_status == "failed":
        return "stale"
    return "synchronized"


def next_automatic_attempt(now: Optional[dt.datetime] = None) -> dt.datetime:
    """Retourne le prochain passage horaire à :05 qui n'est pas en maintenance."""
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    current = current.astimezone(PARIS_TZ)
    candidate = current.replace(minute=5, second=0, microsecond=0)
    if candidate <= current:
        candidate += dt.timedelta(hours=1)
    while is_wedof_maintenance_window(candidate)["active"]:
        candidate += dt.timedelta(hours=1)
    return candidate


def _target_time(name: str, default: str) -> tuple[dt.time, str]:
    value = (os.environ.get(name) or default).strip()
    try:
        parsed = dt.datetime.strptime(value, "%H:%M").time()
        if len(value) != 5:
            raise ValueError
        return parsed, value
    except ValueError:
        logger.warning("Configuration horaire WEDOF invalide variable=%s; valeur par défaut appliquée", name)
        return dt.datetime.strptime(default, "%H:%M").time(), default


def _action_record(status: str, date_value: Optional[str], time_value: str, now: dt.datetime,
                   error: Optional[str] = None) -> Dict[str, Any]:
    planned_at = None
    if date_value:
        planned_at = dt.datetime.combine(dt.date.fromisoformat(date_value), dt.datetime.strptime(time_value, "%H:%M").time(), PARIS_TZ).isoformat()
    return {"status": status, "planned_date": date_value, "planned_time": time_value,
            "planned_at": planned_at, "last_evaluated_at": now.isoformat(),
            "executed_at": None, "last_error_code": error}


def _is_blocked(blocks: Iterable[Dict[str, Any]], external_id: str, action: str) -> bool:
    return any(isinstance(x, dict) and x.get("active") is True
               and str(x.get("external_id") or "") == external_id
               and x.get("action") in {action, "both"} for x in blocks)


def evaluate_action(folder: Dict[str, Any], action: str, *, now: Optional[dt.datetime] = None,
                    blocks: Iterable[Dict[str, Any]] = ()) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Évalue une action uniquement avec les champs WEDOF; renvoie aussi le payload simulé."""
    current = (now or dt.datetime.now(PARIS_TZ)).astimezone(PARIS_TZ)
    remote = extract_folder(folder)
    external_id = str(remote.get("external_id") or "").strip()
    expected_state = "accepted" if action == "entry_training" else "inTraining"
    date_field = "start_date" if action == "entry_training" else "end_date"
    env_name = "WEDOF_ENTRY_TARGET_TIME" if action == "entry_training" else "WEDOF_SERVICE_DONE_TARGET_TIME"
    target, target_text = _target_time(env_name, "18:00" if action == "entry_training" else "23:00")
    raw_date = remote.get(date_field)
    date_value = normalize_date(raw_date)
    error = None
    if not external_id: error = "missing_external_id"
    elif str(remote.get("type") or "").strip().casefold() != "cpf": error = "invalid_type"
    elif remote.get("state") != expected_state: error = "inconsistent_state"
    elif not raw_date: error = "missing_wedof_date"
    elif not date_value: error = "invalid_wedof_date"
    if error:
        return _action_record("anomaly", date_value, target_text, current, error), None
    if _is_blocked(blocks, external_id, action):
        return _action_record("blocked", date_value, target_text, current, "manual_block"), None
    scheduled = dt.date.fromisoformat(date_value)
    if scheduled > current.date() or (scheduled == current.date() and current.time().replace(tzinfo=None) < target):
        status = "planned"
    elif scheduled == current.date():
        status = "dry_run_due"
    else:
        status = "dry_run_due_late"
    payload = None
    if status.startswith("dry_run_due"):
        if action == "entry_training":
            payload = {"date": date_value}
        else:
            payload = {"absenceDuration": 0, "forceMajeureAbsence": False, "date": date_value}
            duration = remote.get("training_duration")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
                payload["trainingDuration"] = duration
    return _action_record(status, date_value, target_text, current), payload


def build_automation_candidate(folder: Dict[str, Any], action: str, *, now: Optional[dt.datetime] = None,
                               exceptions: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """API de compatibilité du contrat initial."""
    remote = extract_folder(folder)
    mapped = "entry_training" if action in {"entry", "entry_training"} else "service_done"
    current = (now or dt.datetime.now(PARIS_TZ)).astimezone(PARIS_TZ)
    wedof_date = normalize_date(remote.get("start_date" if mapped == "entry_training" else "end_date"))
    blocked = any(isinstance(x, dict) and x.get("active") is True and str(x.get("external_id") or "") == remote["external_id"] for x in exceptions)
    scheduled = dt.date.fromisoformat(wedof_date) if wedof_date else None
    due = bool(scheduled and (scheduled <= current.date() if mapped == "entry_training" else scheduled < current.date()))
    eligible = bool(remote["external_id"] and str(remote["type"]).casefold() == "cpf" and
                    remote["state"] == ("accepted" if mapped == "entry_training" else "inTraining") and due and not blocked)
    return {"external_id": remote["external_id"], "wedof_state": remote["state"],
            "wedof_date": wedof_date, "action": action,
            "automation_status": "eligible" if eligible else "excepted" if blocked else "pending",
            "local_link_status": "independent", "eligible": eligible,
            "requires_remote_reread": True}


def run_dry_run(client: Any, data: Dict[str, Any], *, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Analyse chaque état indépendamment et conserve les dernières données connues."""
    current = (now or dt.datetime.now(PARIS_TZ)).astimezone(PARIS_TZ)
    started = current.isoformat()
    run_id = "WRUN-" + uuid.uuid4().hex[:12].upper()
    folders_by_state: Dict[str, Any] = {}
    state_errors: Dict[str, str] = {}
    sync = data.setdefault("wedof_automation_sync", {})
    sync_states = sync.setdefault("states", {})
    for state in ALL_STATES:
        state_sync = sync_states.setdefault(state, {"status": "unknown", "last_attempt_at": None,
                                                      "last_success_at": None, "last_error_code": None})
        state_sync["last_attempt_at"] = started
        try:
            folders_by_state[state] = client.list_registration_folders(state)
            state_sync.update(status="success", last_success_at=started, last_error_code=None)
        except Exception as exc:
            code = getattr(exc, "code", "wedof_api_error")
            state_errors[state] = code if isinstance(code, str) else "wedof_api_error"
            state_sync.update(status="error", last_error_code=state_errors[state])
            logger.warning("Analyse WEDOF état=%s erreur=%s", state, state_errors[state])

    failed_states = [state for state in ALL_STATES if state in state_errors]
    succeeded_states = set(ALL_STATES) - set(failed_states)
    existing = {str(x.get("external_id") or ""): x for x in data.get("wedof_automation_status", []) if isinstance(x, dict)}
    if succeeded_states:
        # Un état actualisé remplace son ancien instantané; un état indisponible reste intact.
        existing = {key: row for key, row in existing.items() if row.get("wedof_state") not in succeeded_states}
        links = {str(x.get("external_id") or "") for x in data.get("wedof_links", []) if isinstance(x, dict) and x.get("active") is True}
        blocks = data.get("wedof_automation_blocks", data.get("wedof_automation_exceptions", []))
        for state, folders in folders_by_state.items():
            for folder in folders:
                remote = extract_folder(folder)
                external_id = str(remote.get("external_id") or "").strip()
                if not external_id:
                    existing["__anomaly_" + uuid.uuid4().hex] = {"external_id": "", "wedof_state": state,
                        "wedof_type": remote.get("type") or "", "last_checked_at": started,
                        "local_link_status": "unlinked", "entry_training": _action_record("anomaly", None, "18:00", current, "missing_external_id"),
                        "service_done": _action_record("not_applicable", None, "23:00", current)}
                    continue
                row = {"external_id": external_id, "wedof_state": state, "wedof_type": remote.get("type") or "",
                       "wedof_date_start": normalize_date(remote.get("start_date")),
                       "wedof_date_end": normalize_date(remote.get("end_date")),
                       "last_checked_at": started, "local_link_status": "linked" if external_id in links else "unlinked"}
                row["entry_training"] = _action_record("not_applicable", normalize_date(remote.get("start_date")), "18:00", current)
                row["service_done"] = _action_record("not_applicable", normalize_date(remote.get("end_date")), "23:00", current)
                action = "entry_training" if state == "accepted" else "service_done" if state == "inTraining" else None
                if action:
                    record, payload = evaluate_action(folder, action, now=current, blocks=blocks)
                    if record["status"].startswith("dry_run_due"):
                        try:
                            reread = client.get_registration_folder(external_id)
                            check = extract_folder(reread)
                            if str(check.get("external_id") or "") != external_id:
                                raise ValueError("external_id_conflict")
                            record, payload = evaluate_action(reread, action, now=current, blocks=blocks)
                        except Exception:
                            record = _action_record("anomaly", record["planned_date"], record["planned_time"], current, "remote_reread_failed")
                    row[action] = record
                existing[external_id] = row
        data["wedof_automation_status"] = list(existing.values())

    statuses = data.get("wedof_automation_status", [])
    counts = {"planned": 0, "due": 0, "late": 0, "blocked": 0, "anomalies": 0}
    for row in statuses:
        for action in ("entry_training", "service_done"):
            value = row.get(action, {}).get("status")
            key = {"dry_run_due": "due", "dry_run_due_late": "late", "anomaly": "anomalies"}.get(value, value)
            if key in counts: counts[key] += 1
    total_failure = len(failed_states) == len(ALL_STATES)
    partial = bool(failed_states) and not total_failure
    status = "failed" if total_failure else "partial_success" if partial else "success"
    finished = dt.datetime.now(PARIS_TZ).isoformat()
    run = {"run_id": run_id, "started_at": started, "finished_at": finished, "mode": "dry_run",
           "folders_by_state": {state: len(folders_by_state.get(state, [])) for state in ALL_STATES}, **counts,
           "status": status, "failed_states": failed_states, "state_errors": state_errors,
           "technical_error": None}
    data["wedof_automation_runs"] = (data.get("wedof_automation_runs", []) + [run])[-RUN_HISTORY_LIMIT:]
    sync.update(last_attempt_at=started, status=status)
    return {"ok": not total_failure, "partial": partial, "status": status, "mode": "dry_run",
            "failed_states": failed_states, "state_errors": state_errors,
            "accepted": len(folders_by_state.get("accepted", [])),
            "in_training": len(folders_by_state.get("inTraining", [])),
            "service_done_declared": len(folders_by_state.get("serviceDoneDeclared", [])),
            "service_done_validated": len(folders_by_state.get("serviceDoneValidated", [])), **counts}


def build_automation_dashboard(folders: Iterable[Dict[str, Any]], *, links: Iterable[Dict[str, Any]] = (),
                               statuses: Iterable[Dict[str, Any]] = (), exceptions: Iterable[Dict[str, Any]] = (),
                               local_associations: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Construit les lignes sans accès réseau et sans déduire de dates depuis les sessions locales."""
    links_by_id = {str(x.get("external_id") or ""): x for x in links
                   if isinstance(x, dict) and x.get("active") is True}
    associations_by_id = {str(x.get("external_id") or ""): x for x in local_associations
                          if isinstance(x, dict)}
    rows = []
    status_by_id = {str(x.get("external_id") or ""): x for x in statuses if isinstance(x, dict)}
    seen = set()
    for item in folders:
        if not isinstance(item, dict): continue
        remote = extract_folder(item); external_id = str(remote.get("external_id") or ""); seen.add(external_id)
        state, history = remote.get("state", ""), status_by_id.get(external_id, {})
        action = history.get("entry_training", {}) if state == "accepted" else history.get("service_done", {})
        value = action.get("status") or "planned"
        anomaly = (state not in AUTOMATABLE_STATES | SERVICE_DONE_STATES or not external_id or
                   remote.get("type", "").casefold() != "cpf" or not normalize_date(remote.get("start_date")) or
                   not normalize_date(remote.get("end_date")) or value in {"anomaly", "blocked", "dry_run_due_late"})
        link, association = links_by_id.get(external_id), associations_by_id.get(external_id, {})
        date_start = (history.get("wedof_date_start") or normalize_date(remote.get("start_date")) or
                      (link or {}).get("wedof_date_start"))
        date_end = (history.get("wedof_date_end") or normalize_date(remote.get("end_date")) or
                    (link or {}).get("wedof_date_end"))
        linked = link is not None
        rows.append({**remote, "tab": "anomaly" if anomaly else {"accepted":"accepted", "inTraining":"training"}.get(state, "service"),
                     "wedof_date_start": date_start, "wedof_date_end": date_end,
                     "start_date": date_start, "end_date": date_end,
                     "automation_status": value, "automation_planned": value == "planned",
                     "planned_date": action.get("planned_date") or (remote.get("start_date") if state == "accepted" else remote.get("end_date")),
                     "planned_time": action.get("planned_time") or ("18:00" if state == "accepted" else "23:00"),
                     "session_id": (link or {}).get("session_id"), "session": association.get("session_label", "Non rattachée"),
                     "trainee_id": (link or {}).get("trainee_id"), "trainee": association.get("trainee_label", "Non rattaché"),
                     "linked": linked, "association": association.get("association_label", "À rattacher localement"),
                     "association_source": (link or {}).get("source"),
                     "association_orphan": bool(association.get("orphaned")), "matching_status": item.get("status"),
                     "entry_success": history.get("entry_training", {}).get("status") == "success",
                     "service_success": history.get("service_done", {}).get("status") == "success",
                     "wedof_state_label": {"inTraining":"En formation — état WEDOF", "serviceDoneDeclared":"Service fait déclaré dans WEDOF", "serviceDoneValidated":"Service fait validé dans WEDOF"}.get(state, "")})
    for status in status_by_id.values():
        if not isinstance(status, dict): continue
        if str(status.get("external_id") or "") in seen: continue
        state = status.get("wedof_state")
        action = status.get("entry_training", {}) if state == "accepted" else status.get("service_done", {})
        value = action.get("status", "not_applicable")
        tab = "anomaly" if value in {"anomaly", "blocked", "dry_run_due_late"} else {"accepted":"accepted", "inTraining":"training"}.get(state, "service")
        external_id = str(status.get("external_id") or "")
        link, association = links_by_id.get(external_id), associations_by_id.get(external_id, {})
        date_start = status.get("wedof_date_start") or (link or {}).get("wedof_date_start")
        date_end = status.get("wedof_date_end") or (link or {}).get("wedof_date_end")
        rows.append({**status, "state": state, "tab": tab, "automation_status": value, "automation_planned": value == "planned",
                     "wedof_date_start": date_start, "wedof_date_end": date_end,
                     "start_date": date_start, "end_date": date_end,
                     "planned_date": action.get("planned_date"), "planned_time": action.get("planned_time"),
                     "session_id": (link or {}).get("session_id"), "session": association.get("session_label", "Non rattachée"),
                     "trainee_id": (link or {}).get("trainee_id"), "trainee": association.get("trainee_label", "Non rattaché"),
                     "linked": link is not None, "association": association.get("association_label", "À rattacher localement"),
                     "association_source": (link or {}).get("source"),
                     "association_orphan": bool(association.get("orphaned")),
                     "entry_success": status.get("entry_training", {}).get("status") == "success", "service_success": status.get("service_done", {}).get("status") == "success",
                     "wedof_state_label": {"inTraining":"En formation — état WEDOF", "serviceDoneDeclared":"Service fait déclaré dans WEDOF", "serviceDoneValidated":"Service fait validé dans WEDOF"}.get(state, "")})
    stats = {"accepted":sum(x["tab"]=="accepted" for x in rows), "training":sum(x["tab"]=="training" for x in rows),
             "service":sum(x["tab"]=="service" for x in rows), "anomaly":sum(x["tab"]=="anomaly" for x in rows),
             "planned":sum(x["automation_status"]=="planned" for x in rows), "entry_success":sum(x["entry_success"] for x in rows), "service_success":sum(x["service_success"] for x in rows),
             "unlinked":sum(not x["linked"] for x in rows)}
    return {"rows": rows, "stats": stats}
