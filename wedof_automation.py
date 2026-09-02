"""Planificateur WEDOF partagé par la simulation et l'automatisation réelle."""

import datetime as dt
import logging
import os
import uuid
from typing import Any, Callable, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from wedof_matching import extract_folder, normalize_date

PARIS_TZ = ZoneInfo("Europe/Paris")
AUTOMATABLE_STATES = {"accepted", "inTraining"}
SERVICE_DONE_STATES = {"serviceDoneDeclared", "serviceDoneValidated"}
ENTRY_DONE_STATES = {"inTraining", "terminated", *SERVICE_DONE_STATES}
ALL_STATES = ("accepted", "inTraining", "serviceDoneDeclared", "serviceDoneValidated")
RUN_HISTORY_LIMIT = 100
LIVE_CANDIDATE_LIMIT_DEFAULT = 30
MAINTENANCE_TIMEZONE = "Europe/Paris"
MAINTENANCE_START_DEFAULT = "05:00"
MAINTENANCE_END_DEFAULT = "07:00"
logger = logging.getLogger(__name__)

_CAPACITY_ERROR_CODES = {
    "wedof_quota_exceeded",
    "wedof_governor_unavailable",
    "wedof_rate_limited",
}


def _live_candidate_limit() -> int:
    """Borne un passage live pour conserver une marge sous le plafond horaire."""
    try:
        configured = int(os.environ.get(
            "WEDOF_LIVE_MAX_CANDIDATES_PER_RUN",
            str(LIVE_CANDIDATE_LIMIT_DEFAULT),
        ))
    except (TypeError, ValueError):
        configured = LIVE_CANDIDATE_LIMIT_DEFAULT
    return max(1, min(configured, 100))


def _capacity_error_code(exc: Exception) -> Optional[str]:
    code = str(getattr(exc, "code", "") or "")
    if code in _CAPACITY_ERROR_CODES:
        return code
    return "wedof_rate_limited" if getattr(exc, "http_status", None) == 429 else None


def _get_live_registration_folder(client: Any, external_id: str) -> Dict[str, Any]:
    """Utilise la voie prioritaire uniquement pendant une automatisation live."""
    priority_get = getattr(client, "get_registration_folder_for_automation", None)
    if callable(priority_get):
        return priority_get(external_id)
    return client.get_registration_folder(external_id)


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
    if isinstance(blocks, dict):
        return bool(_indexed_block(blocks, external_id, action))
    return any(isinstance(x, dict) and x.get("active") is True
               and str(x.get("external_id") or "") == external_id
               and x.get("action") in {action, "both"} for x in blocks)


def _active_blocks_by_key(blocks: Iterable[Dict[str, Any]]) -> Dict[tuple[str, str], Dict[str, Any]]:
    """Indexe les blocages actifs; ``both`` est résolu lors de la lecture."""
    return {(str(block.get("external_id") or ""), str(block.get("action") or "")): block
            for block in blocks if isinstance(block, dict) and block.get("active") is True}


def _indexed_block(index: Dict[tuple[str, str], Dict[str, Any]], external_id: str,
                   action: Optional[str]) -> Optional[Dict[str, Any]]:
    if not action:
        return None
    return index.get((external_id, action)) or index.get((external_id, "both"))


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


def _automation_remote_snapshot(folder: Dict[str, Any]) -> Dict[str, Any]:
    """Accepte un dossier WEDOF brut ou son instantané déjà extrait."""
    remote = extract_folder(folder)
    if remote.get("external_id") or not isinstance(folder, dict):
        return remote
    allowed = (
        "external_id", "state", "type", "start_date", "end_date",
        "training_duration",
    )
    return {key: folder.get(key) for key in allowed}


def _automation_evaluation_folder(remote: Dict[str, Any]) -> Dict[str, Any]:
    """Reconstruit le sous-ensemble WEDOF minimal attendu par evaluate_action."""
    training_info = {
        "startDate": remote.get("start_date"),
        "endDate": remote.get("end_date"),
    }
    if remote.get("training_duration") not in (None, ""):
        training_info["trainingDuration"] = remote.get("training_duration")
    return {
        "externalId": remote.get("external_id"),
        "state": remote.get("state"),
        "type": remote.get("type"),
        "trainingActionInfo": training_info,
    }


def build_folder_automation_status(
    folder: Dict[str, Any], *, now: Optional[dt.datetime] = None,
    blocks: Iterable[Dict[str, Any]] = (), linked: bool = False,
    existing: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Matérialise les deux étapes d'automatisation depuis un GET WEDOF vérifié.

    Le statut ``planned`` est ainsi une donnée persistante réelle, créée à
    partir des dates WEDOF. Le service fait reste explicitement en attente du
    passage à ``inTraining`` au lieu d'être présenté comme une programmation
    manquante.
    """
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    current = current.astimezone(PARIS_TZ)
    remote = _automation_remote_snapshot(folder)
    external_id = str(remote.get("external_id") or "").strip()
    if not external_id:
        return None

    start_date = normalize_date(remote.get("start_date"))
    end_date = normalize_date(remote.get("end_date"))
    _, entry_time = _target_time("WEDOF_ENTRY_TARGET_TIME", "18:00")
    _, service_time = _target_time("WEDOF_SERVICE_DONE_TARGET_TIME", "23:00")
    state = str(remote.get("state") or "").strip()
    row = {
        "external_id": external_id,
        "wedof_state": state,
        "wedof_type": str(remote.get("type") or ""),
        "wedof_date_start": start_date,
        "wedof_date_end": end_date,
        "last_checked_at": current.isoformat(),
        "local_link_status": "linked" if linked else "unlinked",
    }
    evaluation_folder = _automation_evaluation_folder(remote)
    previous = existing if isinstance(existing, dict) else {}

    def keep_confirmed(action: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
        known = previous.get(action) if isinstance(previous.get(action), dict) else {}
        if str(known.get("status") or "") in {"success", "executed", "already_done"}:
            return dict(known)
        return fallback

    if str(remote.get("type") or "").strip().casefold() != "cpf":
        row["entry_training"] = _action_record("anomaly", start_date, entry_time, current, "invalid_type")
        row["service_done"] = _action_record("anomaly", end_date, service_time, current, "invalid_type")
    elif state == "accepted":
        entry, _ = evaluate_action(evaluation_folder, "entry_training", now=current, blocks=blocks)
        waiting = _action_record("waiting_for_in_training", end_date, service_time, current)
        row["entry_training"] = keep_confirmed("entry_training", entry)
        row["service_done"] = keep_confirmed("service_done", waiting)
    elif state == "inTraining":
        completed = _action_record("completed_in_wedof", start_date, entry_time, current)
        service, _ = evaluate_action(evaluation_folder, "service_done", now=current, blocks=blocks)
        row["entry_training"] = keep_confirmed("entry_training", completed)
        row["service_done"] = keep_confirmed("service_done", service)
    elif state in SERVICE_DONE_STATES or state == "terminated":
        row["entry_training"] = keep_confirmed(
            "entry_training", _action_record("completed_in_wedof", start_date, entry_time, current),
        )
        row["service_done"] = keep_confirmed(
            "service_done", _action_record("completed_in_wedof", end_date, service_time, current),
        )
    else:
        row["entry_training"] = _action_record("not_applicable", start_date, entry_time, current)
        row["service_done"] = _action_record("not_applicable", end_date, service_time, current)
    return row


def sync_folder_automation_status(
    data: Dict[str, Any], folder: Dict[str, Any], *, now: Optional[dt.datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Insère ou actualise atomiquement l'état local d'un dossier déjà relu."""
    remote = _automation_remote_snapshot(folder)
    external_id = str(remote.get("external_id") or "").strip()
    if not external_id:
        return None
    rows = data.setdefault("wedof_automation_status", [])
    if not isinstance(rows, list):
        rows = []
        data["wedof_automation_status"] = rows
    existing = next((
        item for item in rows
        if isinstance(item, dict) and str(item.get("external_id") or "") == external_id
    ), None)
    linked = any(
        isinstance(link, dict) and link.get("active") is True
        and str(link.get("external_id") or "") == external_id
        for link in data.get("wedof_links", [])
    )
    row = build_folder_automation_status(
        folder,
        now=now,
        blocks=data.get("wedof_automation_blocks", data.get("wedof_automation_exceptions", [])),
        linked=linked,
        existing=existing,
    )
    if row is None:
        return None
    if existing is None:
        rows.append(row)
    else:
        existing.clear()
        existing.update(row)
        row = existing
    return row


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
    folder_cache = {
        str(item.get("external_id") or ""): item
        for item in data.get("wedof_folder_cache", [])
        if isinstance(item, dict) and item.get("external_id")
    }
    if succeeded_states:
        # Un état actualisé remplace son ancien instantané; un état indisponible reste intact.
        existing = {key: row for key, row in existing.items() if row.get("wedof_state") not in succeeded_states}
        folder_cache = {
            key: row for key, row in folder_cache.items()
            if row.get("state") not in succeeded_states
        }
        links = {str(x.get("external_id") or "") for x in data.get("wedof_links", []) if isinstance(x, dict) and x.get("active") is True}
        blocks = _active_blocks_by_key(
            data.get("wedof_automation_blocks", data.get("wedof_automation_exceptions", [])))
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
                folder_cache[external_id] = {**remote, "synced_at": started}
                row = build_folder_automation_status(
                    folder, now=current, blocks=blocks, linked=external_id in links,
                )
                if row is None:
                    continue
                # Le listing est déjà la source de cette réconciliation globale.
                # Les GET individuels sont réservés au cron live, uniquement
                # lorsqu'une action persistée est réellement arrivée à échéance.
                existing[external_id] = row
        data["wedof_automation_status"] = list(existing.values())
        data["wedof_folder_cache"] = list(folder_cache.values())

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


def _new_action(external_id: str, action: str, business_date: str, now: dt.datetime) -> Dict[str, Any]:
    timestamp = now.isoformat()
    return {"id": "WACTION-" + uuid.uuid4().hex[:8].upper(), "external_id": external_id,
            "action": action, "business_date": business_date, "status": "pending", "attempts": 0,
            "created_at": timestamp, "updated_at": timestamp, "processing_started_at": None,
            "executed_at": None, "wedof_state_before": None, "wedof_state_after": None,
            "last_http_status": None, "last_error_code": None}


def _set_dashboard_action(data: Dict[str, Any], external_id: str, action: str,
                          folder: Dict[str, Any], journal: Dict[str, Any], now: dt.datetime) -> None:
    remote = extract_folder(folder)
    rows = data.setdefault("wedof_automation_status", [])
    row = next((x for x in rows if isinstance(x, dict) and x.get("external_id") == external_id), None)
    if row is None:
        row = {"external_id": external_id}
        rows.append(row)
    row.update(wedof_state=remote.get("state"), wedof_type=remote.get("type"),
               wedof_date_start=normalize_date(remote.get("start_date")),
               wedof_date_end=normalize_date(remote.get("end_date")), last_checked_at=now.isoformat())
    row[action] = {"status": journal["status"], "planned_date": journal["business_date"],
                   "planned_time": "18:00" if action == "entry_training" else "23:00",
                   "executed_at": journal.get("executed_at"),
                   "wedof_state_before": journal.get("wedof_state_before"),
                   "wedof_state_after": journal.get("wedof_state_after"),
                   "last_error_code": journal.get("last_error_code")}


def _planned_datetime(record: Dict[str, Any], current: dt.datetime) -> Optional[dt.datetime]:
    raw = str(record.get("planned_at") or "").strip()
    if raw:
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=PARIS_TZ)
            return parsed.astimezone(PARIS_TZ)
        except ValueError:
            pass
    date_value = normalize_date(record.get("planned_date"))
    time_value = str(record.get("planned_time") or "").strip()
    if not date_value or not time_value:
        return None
    try:
        return dt.datetime.combine(
            dt.date.fromisoformat(date_value),
            dt.datetime.strptime(time_value, "%H:%M").time(),
            PARIS_TZ,
        )
    except ValueError:
        return None


def _due_live_candidates(
    data: Dict[str, Any], current: dt.datetime,
) -> list[tuple[str, str, Dict[str, Any]]]:
    """Sélectionne les actions suivies arrivées à échéance, par priorité métier."""
    cached_by_id = {
        str(item.get("external_id") or ""): item
        for item in data.get("wedof_folder_cache", [])
        if isinstance(item, dict) and item.get("external_id")
    }
    actions = {
        (str(item.get("external_id") or ""), str(item.get("action") or "")): item
        for item in data.get("wedof_automation_actions", [])
        if isinstance(item, dict)
    }
    candidates = []
    for row in data.get("wedof_automation_status", []):
        if not isinstance(row, dict):
            continue
        external_id = str(row.get("external_id") or "").strip()
        state = str(row.get("wedof_state") or row.get("state") or "")
        action = (
            "entry_training" if state == "accepted"
            else "service_done" if state == "inTraining"
            else ""
        )
        if not external_id or not action:
            continue
        journal = actions.get((external_id, action), {})
        if journal.get("status") in {"success", "already_done"}:
            continue
        if (journal.get("status") == "error"
                and journal.get("last_http_status") in {400, 401, 403, 404}):
            # Une erreur fonctionnelle définitive ne doit pas occuper à chaque
            # heure une place réservée aux dossiers encore exécutables.
            continue
        record = row.get(action) if isinstance(row.get(action), dict) else {}
        if record.get("status") in {"anomaly", "not_applicable"}:
            # Une nouvelle donnée vérifiée (webhook, rattachement ou
            # réconciliation) recalculera ce statut. Le cron ne doit pas relire
            # indéfiniment un dossier inexploitable.
            continue
        due_at = _planned_datetime(record, current)
        needs_reconciliation = journal.get("status") in {
            "processing", "uncertain_after_timeout",
        }
        if needs_reconciliation or (due_at is not None and due_at <= current):
            cached = cached_by_id.get(external_id) or {
                "external_id": external_id,
                "state": state,
                "type": row.get("wedof_type"),
                "start_date": row.get("wedof_date_start"),
                "end_date": row.get("wedof_date_end"),
            }
            candidates.append((
                0 if needs_reconciliation else 1,
                due_at or current,
                external_id,
                action,
                cached,
            ))
    candidates.sort(key=lambda item: (item[0], item[1], item[2].casefold(), item[3]))
    return [(external_id, action, cached)
            for _, _, external_id, action, cached in candidates]


def _mark_capacity_blocked(
    data: Dict[str, Any], external_id: str, action: str,
    current: dt.datetime, error_code: str,
) -> None:
    """Expose un arrêt de capacité sans supprimer ni invalider l'échéance."""
    row = next((
        item for item in data.get("wedof_automation_status", [])
        if isinstance(item, dict)
        and str(item.get("external_id") or "") == external_id
    ), None)
    if row is None:
        return
    record = row.get(action) if isinstance(row.get(action), dict) else None
    if record is None:
        date_key = "wedof_date_start" if action == "entry_training" else "wedof_date_end"
        record = _action_record(
            "quota_blocked",
            normalize_date(row.get(date_key)),
            "18:00" if action == "entry_training" else "23:00",
            current,
            error_code,
        )
        row[action] = record
    else:
        record.update(
            status="quota_blocked",
            last_error_code=error_code,
            last_evaluated_at=current.isoformat(),
        )


def run_live_automation(client: Any, data: Dict[str, Any], *, now: Optional[dt.datetime] = None,
                        persist_reservation: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Exécute les actions dues. L'appelant détient le verrou interprocessus."""
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    current = current.astimezone(PARIS_TZ)
    if is_wedof_maintenance_window(current)["active"]:
        result = record_maintenance_skip(data, now=current)
        result["mode"] = "live"
        data["wedof_automation_runs"][-1]["mode"] = "live"
        return result
    actions = data.setdefault("wedof_automation_actions", [])
    counts = {"entry_success": 0, "service_done_success": 0, "already_done": 0,
              "blocked": 0, "errors": 0, "uncertain": 0, "quota_blocked": 0,
              "candidates": 0, "selected": 0, "processed": 0, "remaining": 0}
    # Aucun listing WEDOF ici : le cache/webhook fournit les échéances et seul
    # le dossier réellement dû est relu avant une éventuelle mutation.
    all_candidates = _due_live_candidates(data, current)
    candidate_limit = _live_candidate_limit()
    candidates = all_candidates[:candidate_limit]
    counts["candidates"] = len(all_candidates)
    counts["selected"] = len(candidates)
    counts["remaining"] = len(all_candidates)
    stop_reason = None
    for external_id, action, listed in candidates:
        counts["processed"] += 1
        counts["remaining"] = max(0, len(all_candidates) - counts["processed"])
        # La donnée persistante est relue avant toute réservation et même avant le GET distant.
        block = _indexed_block(_active_blocks_by_key(data.get("wedof_automation_blocks", [])), external_id, action)
        existing = next((x for x in actions if isinstance(x, dict) and
                         x.get("external_id") == external_id and x.get("action") == action), None)
        if block:
            journal = existing or _new_action(external_id, action, "", current)
            if not existing:
                actions.append(journal)
            if journal.get("status") not in {"success", "already_done"}:
                journal.update(status="blocked", updated_at=current.isoformat(), last_error_code="manual_block")
                counts["blocked"] += 1
            sync_folder_automation_status(data, listed, now=current)
            continue
        if (existing and existing.get("status") == "error"
                and existing.get("last_http_status") in {400, 401, 403, 404}):
            continue
        expected_done = ENTRY_DONE_STATES if action == "entry_training" else SERVICE_DONE_STATES
        try:
            fresh = _get_live_registration_folder(client, external_id)
            remote = extract_folder(fresh)
        except Exception as exc:
            counts["errors"] += 1
            capacity_code = _capacity_error_code(exc)
            if capacity_code:
                _mark_capacity_blocked(data, external_id, action, current, capacity_code)
                counts["quota_blocked"] += 1
                stop_reason = capacity_code
                break
            continue
        # Reconcile durable success/uncertainty/processing before considering a POST.
        if existing and existing.get("status") in {"success", "already_done"}:
            sync_folder_automation_status(data, fresh, now=current)
            continue
        if remote.get("state") in expected_done:
            journal = existing or _new_action(external_id, action,
                normalize_date(remote.get("start_date" if action == "entry_training" else "end_date")) or "", current)
            if not existing: actions.append(journal)
            journal.update(status="already_done", updated_at=current.isoformat(),
                           wedof_state_after=remote.get("state"), last_error_code=None)
            _set_dashboard_action(data, external_id, action, fresh, journal, current)
            sync_folder_automation_status(data, fresh, now=current)
            counts["already_done"] += 1
            continue
        record, payload = evaluate_action(fresh, action, now=current,
                                          blocks=data.get("wedof_automation_blocks", []))
        if record["status"] == "planned" or record["status"] == "anomaly":
            sync_folder_automation_status(data, fresh, now=current)
            continue
        business_date = record.get("planned_date") or ""
        journal = existing or _new_action(external_id, action, business_date, current)
        if not existing: actions.append(journal)
        if record["status"] == "blocked":
            journal.update(status="blocked", updated_at=current.isoformat(), last_error_code="manual_block")
            _set_dashboard_action(data, external_id, action, fresh, journal, current)
            sync_folder_automation_status(data, fresh, now=current)
            counts["blocked"] += 1
            continue
        # An uncertain or abandoned processing action is always reconciled above; unchanged state
        # remains uncertain and is never blindly posted again.
        if journal.get("status") in {"processing", "uncertain_after_timeout"}:
            journal.update(status="uncertain_after_timeout", updated_at=current.isoformat(),
                           wedof_state_after=remote.get("state"), last_error_code="unconfirmed_previous_attempt")
            _set_dashboard_action(data, external_id, action, fresh, journal, current)
            counts["uncertain"] += 1
            continue
        journal.update(status="processing", attempts=int(journal.get("attempts") or 0) + 1,
                       processing_started_at=current.isoformat(), updated_at=current.isoformat(),
                       wedof_state_before=remote.get("state"), wedof_state_after=None,
                       last_http_status=None, last_error_code=None)
        _set_dashboard_action(data, external_id, action, fresh, journal, current)
        if persist_reservation:
            persist_reservation(data)
        # Un administrateur peut bloquer entre la sélection/réservation et la mutation distante.
        if _indexed_block(_active_blocks_by_key(data.get("wedof_automation_blocks", [])), external_id, action):
            journal.update(status="blocked", updated_at=current.isoformat(), last_error_code="manual_block",
                           processing_started_at=None)
            _set_dashboard_action(data, external_id, action, fresh, journal, current)
            counts["blocked"] += 1
            continue
        try:
            if action == "entry_training":
                client.declare_registration_folder_in_training(external_id, business_date)
            else:
                duration = extract_folder(fresh).get("training_duration")
                reliable = duration if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0 else None
                client.declare_registration_folder_service_done(external_id, business_date, training_duration=reliable)
            verified = _get_live_registration_folder(client, external_id)
            after = extract_folder(verified).get("state")
            if after not in expected_done:
                raise RuntimeError("wedof_state_not_confirmed")
            journal.update(status="success", executed_at=current.isoformat(), updated_at=current.isoformat(),
                           wedof_state_after=after, last_error_code=None)
            counts["entry_success" if action == "entry_training" else "service_done_success"] += 1
            _set_dashboard_action(data, external_id, action, verified, journal, current)
            sync_folder_automation_status(data, verified, now=current)
        except Exception as exc:
            http_status = getattr(exc, "http_status", None)
            code = getattr(exc, "code", "wedof_state_not_confirmed")
            journal.update(last_http_status=http_status, last_error_code=code, updated_at=current.isoformat())
            capacity_code = _capacity_error_code(exc)
            if capacity_code:
                journal.update(status="quota_blocked", last_error_code=capacity_code,
                               processing_started_at=None)
                _set_dashboard_action(data, external_id, action, fresh, journal, current)
                counts["errors"] += 1
                counts["quota_blocked"] += 1
                stop_reason = capacity_code
                break
            # Timeout/connection ambiguity and 409 require one GET reconciliation, never another POST.
            if getattr(exc, "ambiguous", False) or http_status == 409:
                try:
                    verified = _get_live_registration_folder(client, external_id)
                    after = extract_folder(verified).get("state")
                except Exception:
                    verified, after = fresh, remote.get("state")
                journal["wedof_state_after"] = after
                if after in expected_done:
                    journal.update(status="success" if getattr(exc, "ambiguous", False) else "already_done",
                                   executed_at=current.isoformat() if getattr(exc, "ambiguous", False) else None)
                    counts["entry_success" if action == "entry_training" else "service_done_success"] += bool(getattr(exc, "ambiguous", False))
                    counts["already_done"] += not bool(getattr(exc, "ambiguous", False))
                else:
                    journal["status"] = "uncertain_after_timeout" if getattr(exc, "ambiguous", False) else "error"
                    counts["uncertain" if getattr(exc, "ambiguous", False) else "errors"] += 1
                _set_dashboard_action(data, external_id, action, verified, journal, current)
                if journal.get("status") in {"success", "already_done"}:
                    sync_folder_automation_status(data, verified, now=current)
            else:
                journal["status"] = "error"
                counts["errors"] += 1
                _set_dashboard_action(data, external_id, action, fresh, journal, current)
    run_status = "quota_blocked" if stop_reason else "success"
    run = {"run_id": "WRUN-" + uuid.uuid4().hex[:12].upper(), "started_at": current.isoformat(),
           "finished_at": dt.datetime.now(PARIS_TZ).isoformat(), "mode": "live", "status": run_status,
           "candidate_limit": candidate_limit, "stop_reason": stop_reason, **counts}
    data["wedof_automation_runs"] = (data.get("wedof_automation_runs", []) + [run])[-RUN_HISTORY_LIMIT:]
    return {"ok": True, "mode": "live", "status": run_status,
            "candidate_limit": candidate_limit, "stop_reason": stop_reason, **counts}


_DASHBOARD_SCHEDULED_STATUSES = {
    "planned", "dry_run_due", "dry_run_due_late", "quota_blocked",
}


def _dashboard_automation_sort_key(row: Dict[str, Any]) -> tuple:
    """Put the next actionable WEDOF automation first, with a stable fallback."""
    external_id = str(row.get("external_id") or "").strip()
    is_scheduled = (
        row.get("automation_status") in _DASHBOARD_SCHEDULED_STATUSES
        and bool(row.get("automation_action"))
        and not row.get("automation_blocked")
    )
    planned_date = normalize_date(row.get("planned_date")) if is_scheduled else None
    raw_time = str(row.get("planned_time") or "").strip()
    try:
        planned_time = dt.time.fromisoformat(raw_time).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        planned_time = None
    if planned_date and planned_time:
        return (0, planned_date, planned_time, external_id.casefold(), external_id)
    return (1, "9999-12-31", "23:59:59", external_id.casefold(), external_id)


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
    blocks_by_key = _active_blocks_by_key(exceptions)
    seen = set()
    for item in folders:
        if not isinstance(item, dict): continue
        remote = extract_folder(item); external_id = str(remote.get("external_id") or ""); seen.add(external_id)
        state, history = remote.get("state", ""), status_by_id.get(external_id, {})
        action = (history.get("entry_training", {}) if state == "accepted"
                  else history.get("service_done", {}) if state in {"inTraining", *SERVICE_DONE_STATES}
                  else {})
        value = action.get("status") or ("completed_in_wedof" if state in SERVICE_DONE_STATES else "planned")
        automation_action = "entry_training" if state == "accepted" else "service_done" if state == "inTraining" else None
        block = _indexed_block(blocks_by_key, external_id, automation_action)
        underlying = value
        if block:
            value = "blocked"
        anomaly = (state not in AUTOMATABLE_STATES | SERVICE_DONE_STATES or not external_id or
                   remote.get("type", "").casefold() != "cpf" or not normalize_date(remote.get("start_date")) or
                   not normalize_date(remote.get("end_date")) or value in {"anomaly", "blocked", "dry_run_due_late"})
        link, association = links_by_id.get(external_id), associations_by_id.get(external_id, {})
        date_start = (history.get("wedof_date_start") or normalize_date(remote.get("start_date")) or
                      (link or {}).get("wedof_date_start"))
        date_end = (history.get("wedof_date_end") or normalize_date(remote.get("end_date")) or
                    (link or {}).get("wedof_date_end"))
        linked = link is not None
        rows.append({**remote, "wedof_type": remote.get("type") or "",
                     "tab": "anomaly" if anomaly else {"accepted":"accepted", "inTraining":"training"}.get(state, "service"),
                     "wedof_date_start": date_start, "wedof_date_end": date_end,
                     "start_date": date_start, "end_date": date_end,
                     "automation_status": value, "automation_planned": value == "planned",
                     "automation_action": automation_action, "automation_blocked": bool(block),
                     "active_block": block, "underlying_automation_status": underlying if block else None,
                     "block_reason_code": (block or {}).get("reason_code"), "block_comment": (block or {}).get("comment"),
                     "block_created_at": (block or {}).get("created_at"), "block_updated_at": (block or {}).get("updated_at"),
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
        action = (status.get("entry_training", {}) if state == "accepted"
                  else status.get("service_done", {}) if state in {"inTraining", *SERVICE_DONE_STATES}
                  else {})
        value = action.get("status") or ("completed_in_wedof" if state in SERVICE_DONE_STATES else "not_applicable")
        automation_action = "entry_training" if state == "accepted" else "service_done" if state == "inTraining" else None
        block = _indexed_block(blocks_by_key, str(status.get("external_id") or ""), automation_action)
        underlying = value
        if block: value = "blocked"
        tab = "anomaly" if value in {"anomaly", "blocked", "dry_run_due_late"} else {"accepted":"accepted", "inTraining":"training"}.get(state, "service")
        external_id = str(status.get("external_id") or "")
        link, association = links_by_id.get(external_id), associations_by_id.get(external_id, {})
        date_start = status.get("wedof_date_start") or (link or {}).get("wedof_date_start")
        date_end = status.get("wedof_date_end") or (link or {}).get("wedof_date_end")
        rows.append({**status, "state": state, "wedof_type": status.get("wedof_type") or "",
                     "tab": "anomaly" if block else tab, "automation_status": value, "automation_planned": value == "planned",
                     "automation_action": automation_action, "automation_blocked": bool(block),
                     "active_block": block, "underlying_automation_status": underlying if block else None,
                     "block_reason_code": (block or {}).get("reason_code"), "block_comment": (block or {}).get("comment"),
                     "block_created_at": (block or {}).get("created_at"), "block_updated_at": (block or {}).get("updated_at"),
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
    # Le suivi des rattachements a démarré avec les formations de juin 2026. Les
    # dossiers antérieurs restent consultables dans leurs onglets WEDOF, mais ne
    # doivent pas gonfler l'indicateur opérationnel des rattachements à traiter.
    unlinked_tracking_start = "2026-06-01"
    for row in rows:
        row["unlinked_since_tracking_start"] = (
            not row["linked"]
            # Un dossier terminé reste dans l'historique WEDOF, mais son
            # rattachement n'est plus une opération à traiter. L'indicateur
            # doit donc refléter les seuls dossiers encore actifs.
            and row.get("state") in {"accepted", "inTraining"}
            and bool(row.get("wedof_date_start"))
            and row["wedof_date_start"] >= unlinked_tracking_start
        )

    rows.sort(key=_dashboard_automation_sort_key)

    stats = {"accepted":sum(x["tab"]=="accepted" for x in rows), "training":sum(x["tab"]=="training" for x in rows),
             "service":sum(x["tab"]=="service" for x in rows), "anomaly":sum(x["tab"]=="anomaly" for x in rows),
             "planned":sum(x["automation_status"] in {"planned", "quota_blocked"} for x in rows), "entry_success":sum(x["entry_success"] for x in rows), "service_success":sum(x["service_success"] for x in rows),
             "blocked":sum(x["automation_blocked"] for x in rows),
             "unlinked":sum(x["unlinked_since_tracking_start"] for x in rows)}
    return {"rows": rows, "stats": stats}
