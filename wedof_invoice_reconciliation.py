"""Hourly, quota-bounded reconciliation of WEDOF CPF invoices."""

from __future__ import annotations

import datetime as dt
import os
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import jsonify


SERVICE_DONE_STATES = frozenset({"serviceDoneDeclared", "serviceDoneValidated"})
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_MAX_CANDIDATES = 10
RUNNING_TTL_MINUTES = 30
_GLOBAL_ERROR_CODES = frozenset({
    "wedof_connection_error",
    "wedof_governor_unavailable",
    "wedof_quota_exceeded",
    "wedof_rate_limited",
    "wedof_server_error",
    "wedof_timeout",
    "wedof_unauthorized",
})


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _as_datetime(value: Any) -> Optional[dt.datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _timestamp(value: Optional[dt.datetime] = None) -> str:
    current = value or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    return current.astimezone(dt.timezone.utc).isoformat()


def _active_link(data: Dict[str, Any], candidate: Dict[str, str]) -> Optional[Dict[str, Any]]:
    return next((
        item for item in data.get("wedof_links", [])
        if isinstance(item, dict)
        and item.get("active") is True
        and str(item.get("external_id") or "") == candidate["external_id"]
        and str(item.get("session_id") or "") == candidate["session_id"]
        and str(item.get("trainee_id") or "") == candidate["trainee_id"]
    ), None)


def _service_done_candidates(
    legacy_app: Any, data: Dict[str, Any], *, limit: int,
) -> Dict[str, Any]:
    """Select only linked, non-invoiced folders observed as service-done."""
    statuses = {
        str(item.get("external_id") or ""): str(item.get("wedof_state") or "")
        for item in data.get("wedof_automation_status", [])
        if isinstance(item, dict) and item.get("external_id")
    }
    cached_states = {
        str(item.get("external_id") or ""): str(item.get("state") or "")
        for item in data.get("wedof_folder_cache", [])
        if isinstance(item, dict) and item.get("external_id")
    }
    candidates: List[Dict[str, str]] = []
    selected_external_ids = set()
    for link in data.get("wedof_links", []) or []:
        if not isinstance(link, dict) or link.get("active") is not True:
            continue
        external_id = str(link.get("external_id") or "").strip()
        session_id = str(link.get("session_id") or "").strip()
        trainee_id = str(link.get("trainee_id") or "").strip()
        if not external_id or not session_id or not trainee_id:
            continue
        if external_id in selected_external_ids:
            continue

        session_obj, trainee = legacy_app._cpf_local_registration(
            data, session_id, trainee_id,
        )
        if not session_obj or not trainee:
            continue
        snapshot = dict(link)
        if isinstance(link.get("cpf_snapshot"), dict):
            snapshot.update(link["cpf_snapshot"])
        if legacy_app.has_generated_cpf_invoice(snapshot, trainee, session_obj, data):
            continue

        snapshot_state = str(snapshot.get("state") or "")
        observed_states = {
            snapshot_state,
            str(link.get("wedof_state") or ""),
            statuses.get(external_id, ""),
            cached_states.get(external_id, ""),
        }
        # A previous hourly GET is newer and more precise than a stale global
        # list. If it observed a terminal/non-service state, stop polling it.
        if link.get("cpf_invoice_last_checked_at") and snapshot_state not in SERVICE_DONE_STATES:
            continue
        if not observed_states.intersection(SERVICE_DONE_STATES):
            continue

        candidates.append({
            "external_id": external_id,
            "session_id": session_id,
            "trainee_id": trainee_id,
            "last_checked_at": str(link.get("cpf_invoice_last_checked_at") or ""),
        })
        selected_external_ids.add(external_id)

    # Empty timestamps sort first. Once every folder has been checked, the
    # oldest check is selected first so a capped batch rotates fairly.
    candidates.sort(key=lambda item: (item["last_checked_at"] != "", item["last_checked_at"], item["external_id"]))
    return {"total": len(candidates), "selected": candidates[:limit]}


def _claim_run(
    legacy_app: Any, *, current: dt.datetime, interval_minutes: int, limit: int,
) -> Dict[str, Any]:
    now_text = _timestamp(current)

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        state = data.setdefault("wedof_invoice_reconciliation", {})
        started = _as_datetime(state.get("last_started_at"))
        if state.get("status") == "running" and started:
            if current - started < dt.timedelta(minutes=RUNNING_TTL_MINUTES):
                return {"status": "already_running", "ok": True}
        if started and current - started < dt.timedelta(minutes=interval_minutes):
            return {
                "status": "not_due",
                "ok": True,
                "next_due_at": _timestamp(started + dt.timedelta(minutes=interval_minutes)),
            }

        candidates = _service_done_candidates(legacy_app, data, limit=limit)
        state.update({
            "status": "running",
            "last_started_at": now_text,
            "last_error_code": None,
            "candidate_count": candidates["total"],
            "selected_count": len(candidates["selected"]),
        })
        return {"status": "claimed", "ok": True, **candidates}

    return legacy_app._atomic_update_data(mutate)


def _record_link_error(
    legacy_app: Any, candidate: Dict[str, str], *, current: dt.datetime, code: str,
) -> None:
    now_text = _timestamp(current)

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        link = _active_link(data, candidate)
        if link:
            link["cpf_invoice_last_checked_at"] = now_text
            link["cpf_invoice_reconciliation_error"] = code
        return {"updated": bool(link)}

    legacy_app._atomic_update_data(mutate)


def _apply_remote_folder(
    legacy_app: Any, candidate: Dict[str, str], remote_folder: Dict[str, Any],
    *, current: dt.datetime,
) -> Dict[str, Any]:
    remote = legacy_app.extract_folder(remote_folder)
    external_id = str(remote.get("external_id") or "").strip()
    if external_id != candidate["external_id"]:
        raise legacy_app.WedofApiError("Le dossier WEDOF retourné ne correspond pas au dossier demandé.")
    if str(remote.get("type") or "").casefold() != "cpf":
        raise legacy_app.WedofApiError("Le dossier retourné n’est pas un dossier CPF.")
    now_text = _timestamp(current)

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        link = _active_link(data, candidate)
        if not link:
            return {"updated": False, "invoiced": False, "newly_invoiced": False}
        session_obj, trainee = legacy_app._cpf_local_registration(
            data, candidate["session_id"], candidate["trainee_id"],
        )
        if not session_obj or not trainee:
            return {"updated": False, "invoiced": False, "newly_invoiced": False}

        before_snapshot = dict(link)
        if isinstance(link.get("cpf_snapshot"), dict):
            before_snapshot.update(link["cpf_snapshot"])
        was_invoiced = legacy_app.has_generated_cpf_invoice(
            before_snapshot, trainee, session_obj, data,
        )
        snapshot = legacy_app._cpf_public_snapshot(remote)
        snapshot["synced_at"] = now_text
        link["cpf_snapshot"] = snapshot
        link["wedof_state"] = remote.get("state") or link.get("wedof_state")
        link["last_seen_at"] = now_text
        link["cpf_invoice_last_checked_at"] = now_text
        link.pop("cpf_invoice_reconciliation_error", None)
        link.pop("cpf_sync_error", None)
        legacy_app._upsert_wedof_folder_cache(data, remote_folder)
        legacy_app.sync_folder_automation_status(data, remote_folder, now=current)
        is_invoiced = legacy_app.has_generated_cpf_invoice(
            snapshot, trainee, session_obj, data,
        )
        return {
            "updated": True,
            "invoiced": is_invoiced,
            "newly_invoiced": is_invoiced and not was_invoiced,
        }

    return legacy_app._atomic_update_data(mutate)


def _finish_run(
    legacy_app: Any, *, current: dt.datetime, interval_minutes: int,
    candidate_count: int, selected_count: int, checked: int,
    newly_invoiced: int, still_pending: int, errors: int,
    stopped_early: bool, last_error_code: Optional[str],
) -> Dict[str, Any]:
    finished_at = _timestamp(current)
    status = "success" if not errors else "partial_success" if checked else "failed"
    summary = {
        "ok": status != "failed",
        "status": status,
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "checked": checked,
        "newly_invoiced": newly_invoiced,
        "still_pending": still_pending,
        "errors": errors,
        "remaining": max(0, candidate_count - checked - errors),
        "stopped_early": stopped_early,
        "last_error_code": last_error_code,
        "finished_at": finished_at,
        "next_due_at": _timestamp(current + dt.timedelta(minutes=interval_minutes)),
    }

    def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
        state = data.setdefault("wedof_invoice_reconciliation", {})
        state.update(summary)
        state["last_finished_at"] = finished_at
        if status == "success":
            state["last_success_at"] = finished_at
        history = data.setdefault("wedof_invoice_reconciliation_runs", [])
        history.append(dict(summary))
        data["wedof_invoice_reconciliation_runs"] = history[-100:]
        return summary

    return legacy_app._atomic_update_data(mutate)


def run_hourly_wedof_invoice_reconciliation(
    legacy_app: Any, *, now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Refresh a fair, bounded batch of linked service-done CPF folders."""
    if not legacy_app.read_env_bool(
        "WEDOF_INVOICE_RECONCILIATION_ENABLED", default=True,
    ):
        return {"ok": True, "status": "suspended"}

    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    current = current.astimezone(dt.timezone.utc)
    if legacy_app.is_wedof_maintenance_window(current).get("active"):
        return {"ok": True, "status": "skipped_maintenance_window"}

    interval_minutes = _bounded_int(
        "WEDOF_INVOICE_RECONCILIATION_INTERVAL_MINUTES",
        DEFAULT_INTERVAL_MINUTES, 30, 1440,
    )
    limit = _bounded_int(
        "WEDOF_INVOICE_RECONCILIATION_MAX_CANDIDATES",
        DEFAULT_MAX_CANDIDATES, 1, 20,
    )
    claim = _claim_run(
        legacy_app, current=current, interval_minutes=interval_minutes, limit=limit,
    )
    if claim.get("status") != "claimed":
        return claim

    selected = list(claim.get("selected") or [])
    checked = newly_invoiced = still_pending = errors = 0
    stopped_early = False
    last_error_code: Optional[str] = None
    client = None
    for candidate in selected:
        try:
            if client is None:
                client = legacy_app.WedofClient()
            remote_folder = client.get_registration_folder_interactive(
                candidate["external_id"],
                operation="cpf_invoice_hourly_reconciliation",
            )
            result = _apply_remote_folder(
                legacy_app, candidate, remote_folder, current=current,
            )
            if result.get("updated"):
                checked += 1
                newly_invoiced += int(bool(result.get("newly_invoiced")))
                still_pending += int(not bool(result.get("invoiced")))
        except (legacy_app.WedofApiError, legacy_app.WedofConfigurationError) as exc:
            errors += 1
            last_error_code = str(getattr(exc, "code", "wedof_api_error") or "wedof_api_error")
            _record_link_error(
                legacy_app, candidate, current=current, code=last_error_code,
            )
            legacy_app.app.logger.warning(
                "[WEDOF] hourly invoice reconciliation unavailable "
                "external_id=%s error_code=%s",
                candidate["external_id"], last_error_code,
            )
            if last_error_code in _GLOBAL_ERROR_CODES:
                stopped_early = True
                break
        except Exception:
            errors += 1
            last_error_code = "unexpected_error"
            stopped_early = True
            _record_link_error(
                legacy_app, candidate, current=current, code=last_error_code,
            )
            legacy_app.app.logger.exception(
                "[WEDOF] unexpected hourly invoice reconciliation failure "
                "external_id=%s", candidate["external_id"],
            )
            break

    result = _finish_run(
        legacy_app,
        current=current,
        interval_minutes=interval_minutes,
        candidate_count=int(claim.get("total") or 0),
        selected_count=len(selected),
        checked=checked,
        newly_invoiced=newly_invoiced,
        still_pending=still_pending,
        errors=errors,
        stopped_early=stopped_early,
        last_error_code=last_error_code,
    )
    legacy_app.app.logger.info(
        "[WEDOF] hourly invoice reconciliation completed "
        "candidates=%s selected=%s checked=%s newly_invoiced=%s errors=%s",
        result["candidate_count"], result["selected_count"], result["checked"],
        result["newly_invoiced"], result["errors"],
    )
    return result


def register_wedof_invoice_reconciliation(legacy_app: Any) -> None:
    """Attach the hourly read-only pass to the existing authenticated cron."""
    flask_app = legacy_app.app
    endpoint = "internal_cron_wedof_automation"
    current_view = flask_app.view_functions.get(endpoint)
    if current_view is None or getattr(current_view, "_wedof_invoice_reconciliation", False):
        return

    @wraps(current_view)
    def reconciled_view(*args: Any, **kwargs: Any):
        response = flask_app.make_response(current_view(*args, **kwargs))
        payload = response.get_json(silent=True)
        if response.status_code != 200 or not isinstance(payload, dict) or not payload.get("ok"):
            return response
        try:
            payload["invoice_reconciliation"] = run_hourly_wedof_invoice_reconciliation(
                legacy_app,
            )
        except Exception:
            flask_app.logger.exception(
                "[WEDOF] hourly invoice reconciliation could not start",
            )
            payload["invoice_reconciliation"] = {
                "ok": False,
                "status": "failed",
                "last_error_code": "unexpected_error",
            }
        return jsonify(payload), response.status_code

    reconciled_view._wedof_invoice_reconciliation = True
    flask_app.view_functions[endpoint] = reconciled_view
