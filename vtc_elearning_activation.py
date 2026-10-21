"""Durable, individual VTC access, ten minutes after administrative enrolment.

Only newly created Intégrale trainees are scheduled. The existing JSON store is
the queue; no timer, browser session or deploy is needed to retain an échéance.
Network delivery happens outside the short atomic claim/finalize transactions.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import logging
import re
import threading
import uuid
from urllib.parse import quote

STATE_KEY = "vtc_elearning_auto"
DELAY = dt.timedelta(minutes=10)
MAIL_RE = re.compile(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+")


def clock(now=None):
    value = now or dt.datetime.now(dt.timezone.utc)
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def parse(value):
    try:
        return clock(dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def is_vtc(training):
    return "VTC" in str(training.get("training_type") or training.get("type_formation") or "").upper()


def eligible(host, training, trainee):
    return (is_vtc(training)
            and training.get("partner_id") in (None, "", host.INTEGRALE_PARTNER_ID)
            and not training.get("archived") and not training.get("cancelled")
            and not host._trainee_registration_is_cancelled(trainee))


def schedule_new_enrolment(host, training, trainee, *, now=None):
    """Creation only: never infer eligibility from historical creation dates."""
    if STATE_KEY in trainee or not eligible(host, training, trainee):
        return
    from elearning_native.vtc import curriculum_manifest
    manifest = curriculum_manifest()
    now = clock(now)
    trainee[STATE_KEY] = {
        "id": uuid.uuid4().hex, "revision": 1,
        "created_at": now.isoformat(), "due_at": (now + DELAY).isoformat(),
        "path_title": manifest["title"],
        "modules": [{"course_id": m["id"], "course_version": m["version"],
                     "title": m["title"], "required_minutes": m["required_minutes"]}
                    for m in manifest["modules"]],
        "activated_at": "", "email_status": "pending", "attempts": 0,
    }


def learner_session(training, trainee):
    """Return an individual view; never enable an entire shared session."""
    state = trainee.get(STATE_KEY)
    if not is_vtc(training) or not isinstance(state, dict):
        return training
    active = bool(state.get("activated_at") and state.get("modules"))
    return {**training, "aps_elearning_enabled": active,
            "aps_native_modules": copy.deepcopy(state.get("modules") or []) if active else [],
            "aps_native_course_id": "", "aps_native_path_title": state.get("path_title", ""),
            "vtc_auto_access_available": active}


def preserve_state(payload, canonical, trainees):
    """A stale public/admin save must not undo an activation or email receipt."""
    saved = {(s.get("partner_id") or "", t.get("id")): t
             for s in canonical.get("sessions", []) for t in trainees(s)
             if isinstance(t.get(STATE_KEY), dict)}
    for training in payload.get("sessions", []):
        for trainee in trainees(training):
            previous = saved.get((training.get("partner_id") or "", trainee.get("id")))
            if not previous:
                continue
            state = previous[STATE_KEY]
            incoming = trainee.get(STATE_KEY) or {}
            if state.get("revision", 0) > incoming.get("revision", 0):
                trainee[STATE_KEY] = copy.deepcopy(state)
            history = trainee.get("sent_email_history") or []
            for entry in previous.get("sent_email_history") or []:
                if entry.get("vtc_activation_id") == state["id"] and not any(
                        item.get("vtc_activation_id") == state["id"] for item in history):
                    history.insert(0, copy.deepcopy(entry))
                    trainee["sent_email_history"] = history[:200]


def _due(state, now):
    due = parse(state.get("due_at"))
    if not due or due > now or state.get("email_status") in {"sent", "needs_review"}:
        return False
    return all(not parse(state.get(k)) or parse(state[k]) <= now
               for k in ("next_attempt_at", "lease_until"))


def _find(host, data, session_id, trainee_id):
    training = host.find_session(data, session_id)
    person = next((t for t in host._session_trainees_list(training or {})
                   if t.get("id") == trainee_id), None)
    return training, person


def message(host, trainee):
    origin = host.PUBLIC_STUDENT_PORTAL_BASE.rstrip("/")
    link = origin + "/espace/" + quote(str(trainee["public_token"]), safe="")
    subject = "Votre espace e-learning VTC est prêt 🚘"
    first_name = str(trainee.get("first_name") or "").strip()
    body = host.app.jinja_env.get_template("emails/vtc_elearning_available.html").render(
        first_name=first_name, access_url=link,
        logo_url=origin + "/static/logo-integrale.png")
    text = (f"Bonjour {first_name},\n\nVotre espace e-learning Chauffeur VTC est disponible !\n\n"
            "Retrouvez vos cours illustrés, vidéos, exercices et entraînements à l’examen "
            "dans votre espace stagiaire. Vous pouvez commencer dès maintenant.\n\n"
            f"Accéder à mon espace stagiaire : {link}\n"
            "Puis cliquez sur « Accéder à mon parcours VTC ».\n\n"
            "Votre progression est enregistrée pour reprendre là où vous en étiez.\n"
            "Besoin d’aide ? 04 22 47 07 68\n\nL’équipe Intégrale Academy")
    return {"subject": subject, "html": body, "text": text}


def _process_one(host, session_id, trainee_id, now):
    lease = uuid.uuid4().hex

    def claim(data):
        training, trainee = _find(host, data, session_id, trainee_id)
        if not trainee or not eligible(host, training, trainee):
            return {}
        state = trainee.get(STATE_KEY) or {}
        if not _due(state, now):
            return {}
        state["revision"] += 1
        state["activated_at"] = state.get("activated_at") or now.isoformat()
        # Never regenerate an existing token; the normal public authentication stays in place.
        trainee["public_token"] = trainee.get("public_token") or uuid.uuid4().hex
        email = str(trainee.get("email") or "").strip()
        if not MAIL_RE.fullmatch(email):
            state.update(email_status="missing_email", next_attempt_at=(now + dt.timedelta(minutes=5)).isoformat())
            return {}
        # Resume an uncertain delivery only within the provider's idempotency
        # window. A long outage leaves a visible review status instead of duplicates.
        started = parse(state.get("uncertain_since"))
        if started and (now - started >= dt.timedelta(minutes=10)
                        or state.get("attempted_to") != email):
            state.update(email_status="needs_review", lease_until="")
            return {}
        state.update(email_status="sending", lease_token=lease,
                     lease_until=(now + dt.timedelta(minutes=2)).isoformat(),
                     uncertain_since=state.get("uncertain_since") or now.isoformat(),
                     attempted_to=email,
                     attempts=state.get("attempts", 0) + 1, last_attempt_at=now.isoformat())
        return {"trainee": copy.deepcopy(trainee), "email": email, "had_uncertain_attempt": bool(started)}

    claimed = host._atomic_update_data(claim)
    if not claimed:
        return
    trainee, email = claimed["trainee"], claimed["email"]
    content = message(host, trainee)
    delivery_key = "vtc-access-" + hashlib.sha256(trainee[STATE_KEY]["id"].encode()).hexdigest()
    try:
        result = host.brevo_send_email(email, content["subject"], content["html"],
            text_content=content["text"], metadata={"purpose": "vtc_elearning_activation",
                "idempotency_key": delivery_key, "session_id": session_id, "trainee_id": trainee_id})
        result = result if isinstance(result, dict) else {"ok": result is True}
    except Exception:
        host.app.logger.exception("vtc_elearning_email_unconfirmed trainee_id=%s", trainee_id)
        result = {"ok": False}
    accepted = result.get("ok") is True
    code = result.get("status_code")
    refused = result.get("not_sent") is True or (isinstance(code, int) and 400 <= code < 500 and code != 408)

    def finish(data):
        # A transfer during the network call must still retain the delivery receipt.
        for training in data.get("sessions", []):
            if training.get("partner_id") not in (None, "", host.INTEGRALE_PARTNER_ID):
                continue
            for person in host._session_trainees_list(training):
                state = person.get(STATE_KEY) or {}
                if state.get("lease_token") != lease:
                    continue
                state.update(revision=state["revision"] + 1,
                    email_status="sent" if accepted else "retry_pending",
                    lease_until="", message_id=str(result.get("message_id") or ""),
                    next_attempt_at=(now + dt.timedelta(seconds=300 if refused else 60)).isoformat())
                if accepted or (refused and not claimed["had_uncertain_attempt"]):
                    state["uncertain_since"] = ""
                if accepted:
                    state.update(sent_at=now.isoformat(), sent_to=email, next_attempt_at="")
                    history = person.setdefault("sent_email_history", [])
                    if not any(e.get("vtc_activation_id") == state["id"] for e in history):
                        history.insert(0, {"to_email": email, "subject": content["subject"],
                            "html": content["html"], "sent_at": now.isoformat(), "vtc_activation_id": state["id"]})
                        person["sent_email_history"] = history[:200]
        return {}

    host._atomic_update_data(finish)
    host.app.logger.info("vtc_elearning_activation trainee_id=%s email_status=%s", trainee_id,
                         "sent" if accepted else "retry_pending")


def process_due(host, *, now=None, data=None):
    now = clock(now)
    # Read the atomic JSON snapshot directly: no unrelated reminders, provider
    # calls or expensive normalisation during the frequent scheduler check.
    snapshot = data if data is not None else host._load_valid_json_payload(host.DATA_FILE)
    for training in (snapshot or {}).get("sessions", []):
        for trainee in host._session_trainees_list(training):
            if eligible(host, training, trainee) and _due(trainee.get(STATE_KEY) or {}, now):
                try:
                    _process_one(host, training["id"], trainee["id"], now)
                except Exception:
                    host.app.logger.exception("vtc_elearning_activation_failed trainee_id=%s", trainee.get("id"))


def start_worker(host):
    """Called after Gunicorn forks; resumes persisted deadlines after every deploy."""
    if host.app.testing or host.app.extensions.get("vtc_elearning_worker"):
        return
    stop = threading.Event()
    gunicorn_logger = logging.getLogger("gunicorn.error")
    logger = gunicorn_logger if gunicorn_logger.handlers else host.app.logger

    def run():
        logger.info("vtc_elearning_worker_started delay_seconds=600")
        while not stop.is_set():
            try:
                with host.app.app_context():
                    process_due(host)
            except Exception:
                logger.exception("vtc_elearning_worker_failed")
            stop.wait(15)

    worker = threading.Thread(target=run, name="vtc-elearning-activation", daemon=True)
    host.app.extensions["vtc_elearning_worker"] = {"thread": worker, "stop": stop}
    worker.start()
