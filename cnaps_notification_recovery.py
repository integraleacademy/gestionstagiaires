"""Audited recovery of CNAPS alerts lost before the September 2026 repair.

Nothing runs at import/startup. An authenticated Intégrale administrator first
reviews a persisted preview, then explicitly processes it in small batches.
"""
import copy
import datetime as dt
import hashlib
import hmac
import html
import json
from pathlib import Path
import re
import threading
import time
import uuid

from flask import abort, redirect, render_template, request, session, url_for

from backup_chronology import backup_chronology_key


UNKNOWN_PREVIOUS = "Historique antérieur indisponible — notification de rattrapage ; date d’acceptation inconnue"
_recovery_lock = threading.Lock()
_brevo_read_lock = threading.Lock()
_last_brevo_read = 0.0


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _stamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0


def _text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value)))).strip().casefold()


def _fingerprint(row):
    return hashlib.sha256(json.dumps([row["key"], row["signature"], row["tracking_id"]],
                                     ensure_ascii=False).encode()).hexdigest()


def active_rows(host, data, rows):
    """Only current tracked dossiers; deduplicate the person/NUB aliases."""
    statuses = _mapping(data.get("cnaps_public_annuaire_statuses"))
    result = {}
    for row in host.enrich_cnaps_tracking_rows_with_enrollment(rows, data):
        nub = re.sub(r"\D", "", str(row.get("nub") or ""))[-7:]
        if len(nub) != 7 or not row.get("last_name"):
            continue
        key = host._cnaps_status_change_key(row["last_name"], nub)
        tracking_id = str(row.get("tracking_id") or "")
        status = statuses.get(key) or statuses.get(host._cnaps_tracking_monitor_key(
            tracking_id=tracking_id, first_name=row.get("first_name", ""), last_name=row["last_name"]))
        if not isinstance(status, dict) or host._cnaps_tracking_state_code(status) != "titles" or not status.get("signature"):
            continue
        result[key] = {"key": key, "first_name": row.get("first_name", ""), "last_name": row["last_name"],
                       "nub": nub, "tracking_id": tracking_id, "signature": status["signature"],
                       "checked_at": status.get("checked_at", ""), "status_since": status.get("status_since", ""),
                       "previous_status": UNKNOWN_PREVIOUS, "previous_source": "", "receipt": None,
                       "is_enrolled": bool(row.get("is_enrolled"))}
        result[key]["fingerprint"] = _fingerprint(result[key])
    return sorted(result.values(), key=lambda row: (row["last_name"].casefold(), row["first_name"].casefold()))


def inspect_backups(host, candidates):
    """Read canonical maps only: never merge other tenants or restore data.json."""
    paths = sorted(Path(host.BACKUP_DIR).glob("data_json.*.json"), key=backup_chronology_key, reverse=True)
    report = {"count": len(paths), "read": 0, "invalid": 0,
              "oldest": paths[-1].name if paths else "", "newest": paths[0].name if paths else ""}
    by_key = {row["key"]: row for row in candidates}
    for path in paths:
        try:
            with path.open(encoding="utf-8") as source:
                payload = json.load(source)
            if not isinstance(payload, dict):
                raise ValueError("Invalid snapshot")
        except (OSError, ValueError):
            report["invalid"] += 1
            continue
        report["read"] += 1
        statuses = _mapping(payload.get("cnaps_public_annuaire_statuses"))
        notifications = _mapping(payload.get("cnaps_status_change_notifications"))
        for key, row in by_key.items():
            entry = notifications.get(key)
            if (not row["receipt"] and isinstance(entry, dict) and entry.get("signature") == row["signature"]
                    and (entry.get("email_status") == "sent" or entry.get("sent_at"))):
                row["receipt"] = {**copy.deepcopy(entry), "email_status": "sent", "recovery_source": path.name}
            old = statuses.get(key) or statuses.get("TRACKING|" + row["tracking_id"])
            if not isinstance(old, dict) or row["previous_source"]:
                continue
            if (host._cnaps_tracking_state_code(old) in {"no_title", "nub_missing"}
                    and 0 < _stamp(old.get("checked_at")) < _stamp(row["status_since"])):
                row["previous_status"] = host._cnaps_tracking_state_display(old)
                row["previous_source"] = path.name
    return report


def _brevo_get(host, path, params=None):
    global _last_brevo_read
    if not host.BREVO_API_KEY:
        raise ValueError("La configuration Brevo est absente.")
    for attempt in range(4):
        with _brevo_read_lock:
            # Brevo's email-history endpoints use a tighter quota than sends.
            delay = max(0.0, 1.1 - (time.monotonic() - _last_brevo_read))
            if delay:
                time.sleep(delay)
            try:
                response = host.requests.get("https://api.brevo.com/v3/smtp/" + path,
                    headers={"api-key": host.BREVO_API_KEY, "accept": "application/json"}, params=params, timeout=15)
            finally:
                _last_brevo_read = time.monotonic()
        if response.status_code != 429 or attempt == 3:
            break
        try:
            retry_after = float(response.headers.get("Retry-After", 2 ** (attempt + 1)))
        except (ValueError, TypeError):
            retry_after = 2 ** (attempt + 1)
        if retry_after > 30:
            raise ValueError("Brevo demande d’attendre avant de consulter l’historique. Réessayez plus tard ; aucun mail déclenché.")
        time.sleep(max(2, retry_after))
    if response.status_code != 200:
        raise ValueError(f"Impossible de vérifier les traces Brevo (HTTP {response.status_code}). Aucun nouveau mail déclenché.")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Réponse Brevo invalide.")
    return payload


def inspect_brevo(host, candidates, today=None):
    """Match sent content by exact dossier/NUB/status, not a name alone.

    API documentation: developers.brevo.com/reference/get-transac-emails-list
    and /get-transac-email-content. Each list request spans at most one month.
    """
    today = today or dt.datetime.now(dt.timezone.utc).date()
    first = dt.date(2026, 6, 1)
    recipients = [host.CNAPS_STATUS_CHANGE_NOTIFICATION_TO, *host.CNAPS_STATUS_CHANGE_NOTIFICATION_CC]
    # Check the configured main recipient: one accepted message includes its CCs.
    primary = recipients[0]
    by_subject = {}
    for row in candidates:
        subject, _ = host.build_cnaps_status_change_email(row["first_name"], row["last_name"], row["nub"], row["signature"])
        by_subject.setdefault(_text(subject), []).append(row)
        by_subject.setdefault(_text(subject.replace("Changement de statut CNAPS", "Rattrapage CNAPS", 1)), []).append(row)
    examined = matching = 0
    seen = set()
    while first <= today:
        end = min(first + dt.timedelta(days=27), today)
        offset = 0
        while True:
            payload = _brevo_get(host, "emails", {"email": primary, "startDate": first.isoformat(),
                "endDate": end.isoformat(), "limit": 1000, "offset": offset, "sort": "desc"})
            emails = payload.get("transactionalEmails", [])
            if not isinstance(emails, list):
                raise ValueError("Liste des envois Brevo invalide.")
            examined += len(emails)
            for email in emails:
                if not isinstance(email, dict) or _text(email.get("email")) != _text(primary):
                    continue
                rows = by_subject.get(_text(email.get("subject")), [])
                message_uuid = str(email.get("uuid") or "")
                if not rows or not message_uuid or message_uuid in seen:
                    continue
                seen.add(message_uuid)
                if not re.fullmatch(r"[A-Za-z0-9_-]+", message_uuid):
                    raise ValueError("Identifiant de reçu Brevo invalide.")
                content = _brevo_get(host, "emails/" + message_uuid)
                body = _text(content.get("body"))
                for row in rows:
                    if row["receipt"]:
                        continue
                    if not body:
                        row["ambiguous_email"] = True
                    elif re.search(r"(?<!\d)" + re.escape(row["nub"]) + r"(?!\d)", body) and _text(row["signature"]) in body:
                        row["receipt"] = {"signature": row["signature"], "sent_at": email.get("date", ""),
                            "email_status": "sent", "email_message_id": email.get("messageId", ""),
                            "recovery_source": "brevo", "recovery_email_uuid": message_uuid}
                        matching += 1
            if len(emails) < 1000:
                break
            offset += len(emails)
            if offset >= 20000:
                raise ValueError("Trop de traces Brevo : analyse incomplète, aucun envoi déclenché.")
        first = end + dt.timedelta(days=1)
    return {"examined": examined, "matching": matching, "start": "2026-06-01", "end": today.isoformat(), "recipients": recipients}


def make_plan(host):
    rows, error = host.fetch_cnapsv3_tracking_requests()
    if error:
        raise ValueError("La liste CNAPS est momentanément indisponible.")
    data = host.load_data(run_background_tasks=False)
    candidates = active_rows(host, data, rows)
    notifications = _mapping(data.get("cnaps_status_change_notifications"))
    for row in candidates:
        entry = notifications.get(row["key"])
        row["existing"] = isinstance(entry, dict) and entry.get("signature") == row["signature"]
    recoverable = [row for row in candidates if not row["existing"]]
    backups = inspect_backups(host, recoverable)
    brevo = inspect_brevo(host, recoverable) if recoverable else {"examined": 0, "matching": 0}
    return {"id": uuid.uuid4().hex, "created_at": host._now_iso(), "rows": candidates,
            "backups": backups, "brevo": brevo,
            "recipients": [host.CNAPS_STATUS_CHANGE_NOTIFICATION_TO, *host.CNAPS_STATUS_CHANGE_NOTIFICATION_CC]}


def apply_batch(host, data, plan, allowed_keys, limit=10):
    """Called under the canonical transaction; no network I/O here."""
    results = {"created": [], "restored": [], "skipped": []}
    notifications = data.setdefault("cnaps_status_change_notifications", {})
    if not isinstance(notifications, dict):
        notifications = data["cnaps_status_change_notifications"] = {}
    statuses = _mapping(data.get("cnaps_public_annuaire_statuses"))
    for row in plan["rows"]:
        if len(results["created"]) + len(results["restored"]) >= limit:
            break
        key = row["key"]
        existing = notifications.get(key)
        if isinstance(existing, dict) and existing.get("signature") == row["signature"]:
            continue
        if row.get("ambiguous_email") and not row.get("receipt"):
            results["skipped"].append(key)
            continue
        current = statuses.get(key) or statuses.get("TRACKING|" + row["tracking_id"])
        if (key not in allowed_keys or not isinstance(current, dict) or current.get("signature") != row["signature"]
                or host._cnaps_tracking_state_code(current) != "titles"
                or _stamp(host._now_iso()) - _stamp(current.get("checked_at")) > 3600):
            results["skipped"].append(key)
            continue
        if not host._create_cnaps_status_change_notification(data, first_name=row["first_name"],
                last_name=row["last_name"], nub=row["nub"], tracking_id=row["tracking_id"],
                previous_status=row["previous_status"], new_status=row["signature"], send_email=False):
            continue
        entry = notifications[key]
        entry.update(recovery_batch_id=plan["id"], recovery_at=host._now_iso(),
                     recovery_previous_source=row["previous_source"], recovery_fingerprint=row["fingerprint"])
        if row.get("receipt"):
            # Restore the proven email receipt/review state; never send it again.
            entry.update(row["receipt"])
            entry["updated_at"] = host._now_iso()
            results["restored"].append(key)
        else:
            results["created"].append(key)
    host._append_activity_log(data, "cnaps_notifications_recovered", "cnaps_recovery", plan["id"],
                             host.INTEGRALE_PARTNER_ID, results)
    return results


def verify_delivery(host, data, plan):
    """Read provider delivery events per actual recipient, without sending."""
    receipts = {}
    since = str(plan["created_at"])[:10]
    for recipient in plan["recipients"]:
        offset = 0
        while True:
            payload = _brevo_get(host, "statistics/events", {"email": recipient, "startDate": since,
                "endDate": dt.datetime.now(dt.timezone.utc).date().isoformat(), "limit": 5000, "offset": offset})
            events = payload.get("events", [])
            if not isinstance(events, list):
                raise ValueError("Traces de remise Brevo invalides.")
            for event in events:
                if not isinstance(event, dict) or _text(event.get("email")) != _text(recipient):
                    continue
                event_name = str(event.get("event") or "").lower()
                if event_name not in {"delivered", "opened", "clicks", "unique_opened", "hard_bounce", "soft_bounce", "blocked", "invalid", "error", "deferred"}:
                    continue
                key = str(event.get("messageId") or "")
                target = receipts.setdefault(key, {})
                if recipient not in target or event_name in {"delivered", "opened", "clicks", "unique_opened"}:
                    target[recipient] = "delivered" if event_name in {"delivered", "opened", "clicks", "unique_opened"} else event_name
            if len(events) < 5000:
                break
            offset += len(events)
            if offset >= 25000:
                raise ValueError("Vérification de remise incomplète.")
    def merge(latest):
        count = 0
        for item in _mapping(latest.get("cnaps_status_change_notifications")).values():
            if not isinstance(item, dict) or item.get("recovery_batch_id") != plan["id"]:
                continue
            delivery = receipts.get(str(item.get("email_message_id") or ""))
            if delivery:
                item["email_delivery"] = delivery
                item["updated_at"] = host._now_iso()
                count += 1
        return count
    return host._atomic_update_data(merge)


def register_cnaps_notification_recovery(host):
    app = host.app
    endpoint = "admin_cnaps_notification_recovery"
    if endpoint in app.view_functions:
        return
    plan_path = Path(host.PERSIST_DIR) / "cnaps_notification_recovery_plan.json"

    @app.route("/admin/tools/cnaps-notification-recovery", methods=["GET", "POST"], endpoint=endpoint)
    @host.admin_login_required
    @host.admin_write_required
    def recovery():
        if (session.get("admin_role") not in {"admin", "super_admin"}
                or host._current_partner_id() not in {"", host.INTEGRALE_PARTNER_ID}):
            abort(403)
        csrf = session.setdefault("cnaps_recovery_csrf", uuid.uuid4().hex)
        error = ""
        code = 200
        plan = None
        if plan_path.exists():
            with plan_path.open(encoding="utf-8") as source:
                plan = json.load(source)
        if request.method == "POST":
            if not hmac.compare_digest(str(request.form.get("csrf") or ""), csrf):
                abort(403)
            if not _recovery_lock.acquire(blocking=False):
                abort(409)
            try:
                action = request.form.get("action")
                if action == "scan":
                    plan = make_plan(host)
                    plan_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = plan_path.with_suffix(".tmp")
                    with temporary.open("w", encoding="utf-8") as target:
                        json.dump(plan, target, ensure_ascii=False)
                        target.flush()
                        host.os.fsync(target.fileno())
                    temporary.replace(plan_path)
                elif action in {"apply", "verify"}:
                    if not plan or not hmac.compare_digest(str(request.form.get("plan_id") or ""), plan["id"]):
                        raise ValueError("L’analyse a changé. Rechargez la page.")
                    if plan["recipients"] != [host.CNAPS_STATUS_CHANGE_NOTIFICATION_TO, *host.CNAPS_STATUS_CHANGE_NOTIFICATION_CC]:
                        raise ValueError("Les destinataires ont changé. Relancez l’analyse.")
                    if action == "apply":
                        if _stamp(host._now_iso()) - _stamp(plan["created_at"]) > 7200:
                            raise ValueError("Cette analyse a expiré. Relancez l’analyse.")
                        rows, fetch_error = host.fetch_cnapsv3_tracking_requests()
                        if fetch_error:
                            raise ValueError("Liste CNAPS indisponible. Aucun envoi déclenché.")
                        latest = host.load_data(run_background_tasks=False)
                        allowed = {row["key"] for row in active_rows(host, latest, rows)}
                        if not host._force_backup_snapshot(host.DATA_FILE, reason="pre-cnaps-notification-recovery"):
                            raise ValueError("Impossible de sauvegarder avant le rattrapage.")
                        host._atomic_update_data(lambda data: apply_batch(host, data, plan, allowed))
                        host._deliver_pending_cnaps_notifications()
                    else:
                        verify_delivery(host, host.load_data(run_background_tasks=False), plan)
                else:
                    abort(400)
                return redirect(url_for(endpoint))
            except (ValueError, host.requests.RequestException) as exc:
                error = str(exc) if isinstance(exc, ValueError) else "Service de messagerie indisponible. Réessayez plus tard."
                code = 409
            finally:
                _recovery_lock.release()
        notifications = _mapping(host.load_data(run_background_tasks=False).get("cnaps_status_change_notifications")) if plan else {}
        display = []
        for row in (plan or {}).get("rows", []):
            notification = _mapping(notifications.get(row["key"]))
            same = notification.get("signature") == row["signature"]
            display.append({**row, "email_status": notification.get("email_status", "") if same else "",
                "notified": same, "delivery": notification.get("email_delivery", {}) if same else {},
                "message_id": notification.get("email_message_id", "") if same else ""})
        response = host.make_response(render_template("admin_cnaps_notification_recovery.html", plan=plan,
            rows=display, csrf=csrf, error=error, pending=sum(not r["notified"] and (not r.get("ambiguous_email") or r.get("receipt")) for r in display)), code)
        response.headers["Cache-Control"] = "no-store"
        return response
