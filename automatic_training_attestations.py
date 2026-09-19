"""Envoi durable des attestations d'entrée et de fin de formation.

Le moteur est appelé par le cron protégé existant. Il réserve chaque envoi de
façon atomique avant de générer le document et de contacter Brevo afin que deux
workers ne puissent pas envoyer deux fois la même attestation.
"""

import base64
import copy
import datetime as dt
import os
import time
import uuid
from zoneinfo import ZoneInfo


STATE_KEY = "training_attestation_automation"
SCHEDULER_KEY = "training_attestations_scheduler"
MAX_CATCH_UP_DAYS = 7
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3600

KINDS = {
    "entry": {
        "date_key": "date_start",
        "sent_key": "attestation_entree_aps_sent_at",
        "status_key": "attestation_entree_aps_status",
        "generated_key": "attestation_entree_aps_generated_at",
        "pdf_key": "attestation_entree_aps_pdf_path",
        "docx_key": "attestation_entree_aps_docx_path",
        "token_key": "attestation_entree_aps_pdf_token",
        "error_key": "attestation_entree_aps_last_error",
        "label": "Attestation d'entrée en formation",
    },
    "end": {
        "date_key": "date_end",
        "sent_key": "attestation_fin_aps_sent_at",
        "status_key": "attestation_fin_aps_status",
        "generated_key": "attestation_fin_aps_generated_at",
        "pdf_key": "attestation_fin_aps_pdf_path",
        "docx_key": "attestation_fin_aps_docx_path",
        "token_key": "attestation_fin_aps_pdf_token",
        "error_key": "attestation_fin_aps_last_error",
        "label": "Attestation de fin de formation",
    },
}


def _date(value):
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except (TypeError, ValueError):
        return None


def _datetime(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _attempt_age_seconds(attempt, now):
    stamp = _datetime((attempt or {}).get("attempted_at"))
    return (now - stamp).total_seconds() if stamp else RETRY_DELAY_SECONDS + 1


def _state(trainee, kind, create=False):
    root = trainee.get(STATE_KEY)
    if not isinstance(root, dict):
        if not create:
            return {}
        root = {}
        trainee[STATE_KEY] = root
    current = root.get(kind)
    if not isinstance(current, dict):
        if not create:
            return {}
        current = {}
        root[kind] = current
    return current


def _has_template(services, training, kind):
    if kind == "entry":
        return services._automation_has_entry_attestation(training)
    return services._automation_has_end_attestation(training)


def _scheduled_date(services, training, kind):
    return _date(services._session_get(training, KINDS[kind]["date_key"], ""))


def _is_due(services, training, trainee, kind, today, activated_on, now):
    config = KINDS[kind]
    if trainee.get(config["sent_key"]) or not _has_template(services, training, kind):
        return False
    due = _scheduled_date(services, training, kind)
    activation = _date(activated_on) or today
    if not due or due > today:
        return False

    if kind == "entry":
        # On activation, recover only enrolments whose training is still in
        # progress. This catches missed starts without mailing old archives.
        end = _date(services._session_get(training, "date_end", ""))
        if due < activation and (not end or end < today):
            return False
    elif due < activation or (today - due).days > MAX_CATCH_UP_DAYS:
        return False

    attempt = _state(trainee, kind)
    status = str(attempt.get("email_status") or "").upper()
    if status in {"ACCEPTE", "INCONNU", "DESACTIVE"}:
        return False
    if attempt.get("pending") and _attempt_age_seconds(attempt, now) < 600:
        return False
    if status == "EN_COURS":
        return False
    if status == "ECHEC":
        return int(attempt.get("attempt_count") or 0) < MAX_ATTEMPTS and _attempt_age_seconds(attempt, now) >= RETRY_DELAY_SECONDS
    return True


def _find(services, current, session_id, trainee_id):
    training = services.find_session(current, session_id)
    if not training:
        return None, None
    trainees = services._session_trainees_list(training)
    trainee = next((item for item in trainees if str(item.get("id")) == str(trainee_id)), None)
    if trainee is not None:
        training["trainees"] = trainees
        training.pop("stagiaires", None)
    return training, trainee


def _mark_failure(services, session_id, trainee_id, kind, attempt_id, now, message):
    config = KINDS[kind]

    def save(current):
        _, trainee = _find(services, current, session_id, trainee_id)
        if trainee is None:
            return {}
        attempt = _state(trainee, kind, create=True)
        if str(attempt.get("id") or "") != attempt_id:
            return {}
        attempt.update({
            "pending": False,
            "email_status": "ECHEC",
            "error": message,
            "finished_at": now.isoformat(),
        })
        trainee[config["status_key"]] = "error"
        trainee[config["error_key"]] = message
        trainee["updated_at"] = now.isoformat()
        return {}

    services._atomic_update_data(save)


def _aggregate_history_entry(attempt):
    return {
        "to_email": attempt.get("email") or "",
        "subject": attempt.get("subject") or "",
        "html": attempt.get("html") or "",
        "sent_at": attempt.get("sent_at") or attempt.get("finished_at") or "",
        "source": "automatic_training_attestation",
        "attestation_kind": attempt.get("kind") or "",
        "message_id": attempt.get("message_id") or "",
        "automation_id": attempt.get("id") or "",
    }


def run(services, *, now=None, dry_run=False, limit=5):
    """Send due attestations and return a scheduler-friendly report."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    now = now.astimezone(dt.timezone.utc)
    local = now.astimezone(ZoneInfo("Europe/Paris"))
    today = local.date()
    report = {
        "ok": True,
        "status": "checked",
        "checked": 0,
        "due": 0,
        "processed": 0,
        "emails_accepted": 0,
        "entry_sent": 0,
        "end_sent": 0,
        "failed": 0,
        "skipped_cancelled": 0,
    }
    if not 9 <= local.hour < 20:
        report["status"] = "outside_sending_hours"
        return report

    data = services.load_data(run_background_tasks=False)
    activation = (data.get(SCHEDULER_KEY) or {}).get("activated_on")
    if not dry_run and not activation:
        def initialize(current):
            scheduler = current.setdefault(SCHEDULER_KEY, {})
            scheduler.setdefault("activated_on", today.isoformat())
            return {"activated_on": scheduler["activated_on"]}

        activation = services._atomic_update_data(initialize)["activated_on"]
    activation = activation or today.isoformat()
    report["activated_on"] = activation

    candidates = []
    for training in data.get("sessions", []):
        if training.get("archived") or not services._automation_document_config(training).get("enabled"):
            continue
        for trainee in services._session_trainees_list(training):
            report["checked"] += 1
            if services._trainee_registration_is_cancelled(trainee):
                report["skipped_cancelled"] += 1
                continue
            for kind in ("entry", "end"):
                if _is_due(services, training, trainee, kind, today, activation, now):
                    candidates.append((str(training.get("id") or ""), str(trainee.get("id") or ""), kind))
    report["due"] = len(candidates)
    if dry_run:
        report["status"] = "dry_run"
        return report

    started = time.monotonic()
    for session_id, trainee_id, kind in candidates:
        if report["processed"] >= limit or time.monotonic() - started > 120:
            break
        config = KINDS[kind]

        def reserve(current):
            training, trainee = _find(services, current, session_id, trainee_id)
            if trainee is None or training.get("archived") or services._trainee_registration_is_cancelled(trainee):
                return {}
            if not _is_due(services, training, trainee, kind, today, activation, now):
                return {}
            previous = _state(trainee, kind, create=True)
            if str(previous.get("email_status") or "").upper() == "EN_COURS":
                # A provider may already have accepted the message before a
                # worker stopped. Never risk an automatic duplicate.
                previous.update({"pending": False, "email_status": "INCONNU", "error": "Envoi interrompu ; vérifier avant de relancer"})
                return {}
            attempt = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "source": "automatic_training_attestation",
                "scheduled_for": _scheduled_date(services, training, kind).isoformat(),
                "attempted_at": now.isoformat(),
                "attempt_count": int(previous.get("attempt_count") or 0) + 1,
                "pending": True,
                "email_status": "EN_ATTENTE",
                "email": str(trainee.get("email") or "").strip(),
            }
            trainee[STATE_KEY][kind] = attempt
            trainee[config["status_key"]] = "pending"
            trainee[config["error_key"]] = ""
            trainee["updated_at"] = now.isoformat()
            return {"training": copy.deepcopy(training), "trainee": copy.deepcopy(trainee), "attempt": copy.deepcopy(attempt)}

        reserved = services._atomic_update_data(reserve)
        if not reserved:
            continue
        report["processed"] += 1
        attempt = reserved["attempt"]
        training = reserved["training"]
        trainee = reserved["trainee"]
        attempt_id = str(attempt["id"])

        if not attempt["email"]:
            _mark_failure(services, session_id, trainee_id, kind, attempt_id, now, "Adresse e-mail stagiaire manquante")
            report["failed"] += 1
            continue

        try:
            if kind == "entry":
                docx_path, pdf_path = services._generate_aps_entry_attestation_files(training, trainee, session_id, trainee_id)
                subject, html_content = services._build_aps_entry_attestation_email(
                    str(trainee.get("first_name") or ""), services._session_get(training, "date_start", ""), training,
                )
            else:
                docx_path, pdf_path = services._generate_aps_end_attestation_files(training, trainee, session_id, trainee_id)
                subject, html_content = services._build_aps_end_attestation_email(
                    str(trainee.get("first_name") or ""), services._session_get(training, "date_end", ""), training,
                )
            with open(pdf_path, "rb") as handle:
                encoded_pdf = base64.b64encode(handle.read()).decode("ascii")
        except Exception as exc:
            message = str(exc) or "Génération de l’attestation impossible"
            services.app.logger.exception("automatic_training_attestation generation kind=%s", kind)
            _mark_failure(services, session_id, trainee_id, kind, attempt_id, now, message)
            report["failed"] += 1
            continue

        # Last atomic gate immediately before Brevo: an enrolment cancelled
        # while the PDF was being produced must never be mailed.
        def claim(current):
            _, current_trainee = _find(services, current, session_id, trainee_id)
            if current_trainee is None:
                return {"send": False}
            stored = _state(current_trainee, kind, create=True)
            if str(stored.get("id") or "") != attempt_id:
                return {"send": False}
            if services._trainee_registration_is_cancelled(current_trainee):
                stored.update({
                    "pending": False,
                    "email_status": "DESACTIVE",
                    "error": "Automatisation désactivée : l'inscription est annulée.",
                    "finished_at": now.isoformat(),
                })
                current_trainee[config["status_key"]] = "disabled"
                current_trainee[config["error_key"]] = ""
                current_trainee["updated_at"] = now.isoformat()
                return {"send": False, "cancelled": True}
            if current_trainee.get(config["sent_key"]):
                stored.update({"pending": False, "email_status": "ACCEPTE"})
                return {"send": False}
            stored.update({
                "email_status": "EN_COURS",
                "subject": subject,
                "html": html_content,
                "pdf_path": pdf_path,
                "docx_path": docx_path,
            })
            return {"send": True}

        claimed = services._atomic_update_data(claim)
        if not claimed.get("send"):
            continue

        attempt.update({
            "email_status": "EN_COURS",
            "subject": subject,
            "html": html_content,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
        })
        try:
            result = services.brevo_send_email(
                attempt["email"],
                subject,
                html_content,
                attachments=[{"name": os.path.basename(pdf_path), "content": encoded_pdf}],
                metadata={
                    "purpose": "automatic_training_attestation",
                    "attestation_kind": kind,
                    "session_id": session_id,
                    "trainee_id": trainee_id,
                },
            )
            accepted = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
            attempt["email_status"] = "ACCEPTE" if accepted else "ECHEC"
            attempt["error"] = "" if accepted else str((result or {}).get("error") if isinstance(result, dict) else "") or "Transmission non confirmée par Brevo"
            attempt["message_id"] = str((result or {}).get("message_id") or "") if isinstance(result, dict) else ""
        except Exception:
            accepted = False
            attempt["email_status"] = "INCONNU"
            attempt["error"] = "Service d'envoi interrompu ; vérifier avant de relancer"
            services.app.logger.exception("automatic_training_attestation send kind=%s", kind)

        finished_at = now.isoformat()
        attempt.update({"pending": False, "finished_at": finished_at})
        if accepted:
            attempt["sent_at"] = finished_at

        def finish(current):
            _, current_trainee = _find(services, current, session_id, trainee_id)
            if current_trainee is None:
                return {}
            stored = _state(current_trainee, kind, create=True)
            if str(stored.get("id") or "") != attempt_id:
                return {}
            stored.update(attempt)
            if accepted:
                current_trainee[config["status_key"]] = "sent"
                current_trainee[config["generated_key"]] = current_trainee.get(config["generated_key"]) or finished_at
                current_trainee[config["sent_key"]] = finished_at
                current_trainee[config["pdf_key"]] = pdf_path
                current_trainee[config["docx_key"]] = docx_path
                current_trainee[config["token_key"]] = services._store_public_file_token(pdf_path)
                current_trainee[config["error_key"]] = ""
                history = current_trainee.setdefault("sent_email_history", [])
                if not any(item.get("automation_id") == attempt_id for item in history if isinstance(item, dict)):
                    history.insert(0, _aggregate_history_entry(attempt))
                    del history[200:]
                services.append_trainee_history_event(
                    current_trainee,
                    f"{config['label']} envoyée automatiquement",
                    f"E-mail accepté pour {attempt['email']}",
                    "mail",
                    at=finished_at,
                )
            else:
                current_trainee[config["status_key"]] = "error"
                current_trainee[config["error_key"]] = attempt["error"]
            current_trainee["updated_at"] = finished_at
            return {}

        services._atomic_update_data(finish)
        if accepted:
            report["emails_accepted"] += 1
            report[f"{kind}_sent"] += 1
        else:
            report["failed"] += 1

    report["ok"] = report["failed"] == 0
    report["status"] = "completed" if report["ok"] else "completed_with_issues"

    def record_report(current):
        scheduler = current.setdefault(SCHEDULER_KEY, {})
        scheduler.update({"last_run_at": now.isoformat(), "last_report": dict(report)})
        return {}

    services._atomic_update_data(record_report)
    services.app.logger.info("automatic_training_attestation report=%s", report)
    return report
