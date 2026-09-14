"""Durable J-25/J-15/J-10 reminders, invoked only by the protected scheduler."""
import copy
import datetime as dt
import time
import uuid
from zoneinfo import ZoneInfo

STAGES = (25, 15, 10)
HISTORY_KEY = "automatic_docs_reminder_history"


def _date(value):
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def phase_key(start, stage):
    return f"{start.isoformat()}:J-{stage}"


def phase_attempt(trainee, start, stage):
    return next((x for x in trainee.get(HISTORY_KEY, []) if x.get("phase_key") == phase_key(start, stage)), None)


def legacy_j15_sent(trainee, start):
    # The former implementation had a single J-15 timestamp. Keep it as proof
    # of that phase only; never turn it into a suppression of J-25 or J-10.
    sent = _date(trainee.get("docs_relance_auto_sent_at"))
    return not trainee.get(HISTORY_KEY) and sent and start - dt.timedelta(days=15) <= sent < start


def schedule(trainee, start, today, activated_on=None):
    active = next((stage for stage in reversed(STAGES) if today >= start - dt.timedelta(days=stage)), None)
    activation = _date(activated_on)
    rows = []
    for stage in STAGES:
        due = start - dt.timedelta(days=stage)
        attempt = phase_attempt(trainee, start, stage)
        state = "Prévue"
        if attempt:
            if attempt.get("pending"):
                state = "En cours / à vérifier"
            elif attempt.get("email_status") == "ACCEPTE" and attempt.get("sms_status") in {"ACCEPTE", "DESACTIVE"}:
                state = "Transmise"
            else:
                state = "Transmission à vérifier"
        elif stage == 15 and legacy_j15_sent(trainee, start):
            state = "Déjà traitée"
        elif today >= start or (activation and due < activation) or (due < today and stage != active):
            state = "Échéance passée"
        elif due <= today:
            state = "À envoyer"
        rows.append({"stage": stage, "date": due.isoformat(), "state": state,
                     "email_status": (attempt or {}).get("email_status", ""),
                     "sms_status": (attempt or {}).get("sms_status", "")})
    return rows


def due_stage(trainee, start, today, activated_on):
    if today >= start:
        return None
    rows = schedule(trainee, start, today, activated_on)
    # After an outage, send only the most recent phase still relevant. Never
    # catch up several old reminders together when activating the scheduler.
    active = next((x for x in reversed(rows) if x["date"] <= today.isoformat()), None)
    if not active or active["state"] in {"Échéance passée", "Déjà traitée", "Transmise", "Transmission à vérifier"}:
        return None
    return active["stage"]


def _age(attempt, now):
    try:
        stamp = dt.datetime.fromisoformat(attempt["attempted_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return (now - stamp).total_seconds()
    except (KeyError, ValueError, TypeError):
        return 601


def run(services, *, now=None, dry_run=False, limit=5):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    local = now.astimezone(ZoneInfo("Europe/Paris"))
    today = local.date()
    report = {"ok": True, "status": "checked", "checked": 0, "due": 0,
              "processed": 0, "emails_accepted": 0, "sms_accepted": 0, "failed": 0}
    if not 9 <= local.hour < 20:
        report["status"] = "outside_sending_hours"
        return report
    data = services.load_data(run_background_tasks=False)
    activation = (data.get("document_reminders_scheduler") or {}).get("activated_on")
    if not dry_run and not activation:
        def initialize(current):
            state = current.setdefault("document_reminders_scheduler", {})
            state.setdefault("activated_on", today.isoformat())
            return {"activated_on": state["activated_on"]}
        activation = services._atomic_update_data(initialize)["activated_on"]
    activation = activation or today.isoformat()
    report["activated_on"] = activation

    def find(current, session_id, trainee_id):
        training = services.find_session(current, session_id)
        if not training:
            return None, None
        trainees = services._session_trainees_list(training)
        trainee = next((t for t in trainees if t.get("id") == trainee_id), None)
        if trainee is not None:
            training["trainees"] = trainees
            training.pop("stagiaires", None)
        return training, trainee

    candidates = []
    for training in data.get("sessions", []):
        start = services._session_start_date(training)
        if not start or not services._docs_relance_auto_enabled(training) or training.get("archived"):
            continue
        for trainee in services._session_trainees_list(training):
            report["checked"] += 1
            stage = due_stage(trainee, start, today, activation)
            if stage is None:
                continue
            preview, reason = services._manual_docs_preview(training, trainee, today=today, automatic_stage=stage)
            if not reason:
                candidates.append((training["id"], trainee["id"]))
    report["due"] = len(candidates)
    if dry_run:
        report["status"] = "dry_run"
        return report

    started = time.monotonic()
    for session_id, trainee_id in candidates:
        if report["processed"] >= limit or time.monotonic() - started > 120:
            break

        def reserve(current):
            training, trainee = find(current, session_id, trainee_id)
            if trainee is None or not services._docs_relance_auto_enabled(training):
                return {}
            start = services._session_start_date(training)
            if not start:
                return {}
            stage = due_stage(trainee, start, today, activation)
            if stage is None:
                return {}
            if any(x.get("pending") and _age(x, now) < 600 for x in trainee.get("manual_docs_reminder_history", [])):
                return {}
            preview, reason = services._manual_docs_preview(training, trainee, today=today, automatic_stage=stage)
            if reason:
                return {}
            attempt = phase_attempt(trainee, start, stage)
            if attempt and attempt.get("pending") and _age(attempt, now) < 600:
                return {}
            if attempt:
                # A crashed worker may have already handed an in-flight message
                # to the provider. Do not resend that channel without evidence.
                for channel in ("email", "sms"):
                    if attempt.get(f"{channel}_status") == "EN_COURS":
                        attempt[f"{channel}_status"] = "INCONNU"
                attempt["attempted_at"] = now.isoformat()
                attempt["pending"] = True
            else:
                old_j15 = legacy_j15_sent(trainee, start)
                attempt = {"id": uuid.uuid4().hex, "phase_key": phase_key(start, stage),
                           "automatic_stage": stage, "source": "automatic_documents_reminder",
                           "scheduled_for": (start - dt.timedelta(days=stage)).isoformat(),
                           "attempted_at": now.isoformat(), "pending": True,
                           "email_status": "EN_ATTENTE", "sms_status": "EN_ATTENTE"}
                if services._session_has_afc_marker(services._session_get(training, "name", "")) or services._trainee_requires_afc_medical_cert(trainee):
                    attempt["sms_status"] = "DESACTIVE"
                history = trainee.setdefault(HISTORY_KEY, [])
                if old_j15:
                    history.append({"id": "legacy-j15", "phase_key": phase_key(start, 15),
                                    "automatic_stage": 15, "pending": False,
                                    "email_status": "INCONNU", "sms_status": "INCONNU"})
                history.insert(0, attempt)
                del history[100:]
            for key in ("email", "phone", "subject", "text", "html", "sms", "deadline"):
                # Preserve an already attempted channel's exact message for its
                # history; new pending channels use the same frozen content.
                attempt.setdefault(key, preview[key])
            return {"attempt": copy.deepcopy(attempt)}

        reserved = services._atomic_update_data(reserve)
        if not reserved:
            continue
        attempt = reserved["attempt"]
        report["processed"] += 1
        for channel, address in (("email", "email"), ("sms", "phone")):
            status_key = f"{channel}_status"
            if attempt[status_key] != "EN_ATTENTE":
                continue
            attempt[status_key] = "EN_COURS" if attempt[address] else "ABSENT"

            def save(current):
                training, trainee = find(current, session_id, trainee_id)
                if trainee is None:
                    return {"ok": False}
                stored = next((x for x in trainee.get(HISTORY_KEY, []) if x.get("id") == attempt["id"]), None)
                if stored is None:
                    return {"ok": False}
                stored.update(attempt)
                if attempt.get("email_status") == "ACCEPTE":
                    entry = services._manual_docs_email_history_entry(attempt)
                    history = trainee.setdefault("sent_email_history", [])
                    if not services._email_history_contains(history, entry):
                        history.insert(0, entry)
                        del history[200:]
                if "ACCEPTE" in (attempt["email_status"], attempt["sms_status"]):
                    trainee["docs_last_relance_at"] = now.isoformat()
                trainee["updated_at"] = now.isoformat()
                return {"ok": True}

            # Claim each channel on disk before making any external request.
            if not services._atomic_update_data(save).get("ok"):
                report["failed"] += 1
                break
            if attempt[status_key] == "ABSENT":
                continue
            try:
                if channel == "email":
                    result = services.brevo_send_email(
                        attempt["email"], attempt["subject"], attempt["html"], text_content=attempt["text"],
                        metadata={"purpose": "automatic_documents_reminder", "stage": attempt["automatic_stage"],
                                  "session_id": session_id, "trainee_id": trainee_id},
                    )
                else:
                    result = services.brevo_send_sms(attempt["phone"], attempt["sms"])
                accepted = bool(result.get("ok")) if isinstance(result, dict) else bool(result)
                attempt[status_key] = "ACCEPTE" if accepted else "ECHEC"
                if accepted:
                    report["emails_accepted" if channel == "email" else "sms_accepted"] += 1
                    attempt[f"{channel}_sent_at"] = now.isoformat()
                    if channel == "email":
                        attempt["message_id"] = result.get("message_id", "") if isinstance(result, dict) else ""
                else:
                    attempt[f"{channel}_error"] = "Transmission non confirmée par le service d’envoi"
            except Exception:
                attempt[status_key] = "INCONNU"
                attempt[f"{channel}_error"] = "Service d’envoi interrompu ; vérifier avant de relancer"
                services.app.logger.exception("automatic_documents_reminder channel=%s stage=%s", channel, attempt["automatic_stage"])
            services._atomic_update_data(save)

        attempt["pending"] = False
        attempt["finished_at"] = now.isoformat()
        # Defined independently of the loop, including recovery where every
        # channel was already recorded before the previous worker stopped.
        def finish(current):
            training, trainee = find(current, session_id, trainee_id)
            if trainee is None:
                return {}
            stored = next((x for x in trainee.get(HISTORY_KEY, []) if x.get("id") == attempt["id"]), None)
            if stored is not None:
                stored.update(attempt)
                services.append_trainee_history_event(
                    trainee, f"Relance automatique J−{attempt['automatic_stage']}",
                    f"E-mail : {attempt['email_status']} · SMS : {attempt['sms_status']}", "mail", at=now.isoformat())
            return {}
        services._atomic_update_data(finish)
        if attempt["email_status"] != "ACCEPTE" or attempt["sms_status"] not in {"ACCEPTE", "DESACTIVE"}:
            report["failed"] += 1

    report["ok"] = report["failed"] == 0
    report["status"] = "completed" if report["ok"] else "completed_with_issues"
    def record_report(current):
        state = current.setdefault("document_reminders_scheduler", {})
        state.update({"last_run_at": now.isoformat(), "last_report": dict(report)})
        return {}
    if report["processed"]:
        services._atomic_update_data(record_report)
    services.app.logger.info("automatic_documents_reminder report=%s", report)
    return report
