"""Individual APS access for an Intégrale DESP VAE registration."""
import copy
import datetime as dt
import secrets
import uuid
from urllib.parse import quote

from flask import Blueprint, abort, jsonify, render_template, request, session
from itsdangerous import BadSignature, URLSafeTimedSerializer

from elearning_native import aps_enrolments
from vtc_elearning_activation import MAIL_RE

KEY = "desp_vae_aps_access"
SUBJECT = "Votre accès au parcours e-learning APS"


def is_vae(training):
    label = training.get("training_type") or training.get("type_formation") or ""
    return label.strip().upper() in {"DIRIGEANT VAE", "DESP VAE"}


def active(training, person):
    grant = person.get(KEY) or {}
    return bool(is_vae(training) and grant.get("session_id") == training.get("id") and grant.get("modules"))


def learner_session(training, person):
    if not active(training, person):
        return training
    return {**training, "aps_native_modules": person[KEY]["modules"], "aps_native_path_title": "Mon parcours APS",
            "aps_elearning_enabled": True, "individual_aps_access": True}


def preserve_state(payload, canonical, trainees):
    # Grants and delivery receipts are written by atomic transactions. A public
    # portal save from an older snapshot must not erase either.
    saved = {(s["id"], t["id"]): t for s in canonical.get("sessions", []) if is_vae(s)
             for t in trainees(s) if t.get(KEY)}
    for training in payload.get("sessions", []):
        if not is_vae(training):
            continue
        for person in trainees(training):
            previous = saved.get((training.get("id"), person.get("id")))
            if not previous:
                continue
            grant = previous[KEY]
            person[KEY] = copy.deepcopy(grant)
            if not person.get("public_token"):
                person["public_token"] = previous.get("public_token")
            receipt = next((item for item in previous.get("sent_email_history", [])
                            if item.get("vae_aps_delivery") == grant.get("delivery_id") and item.get("vae_aps_delivery")), None)
            history = person.get("sent_email_history") or []
            if receipt and not any(item.get("vae_aps_delivery") == grant["delivery_id"] for item in history):
                person["sent_email_history"] = [copy.deepcopy(receipt), *history][:200]


def register_routes(host):
    bp = Blueprint("desp_vae_access", __name__)
    route = "/admin/sessions/<session_id>/stagiaires/<trainee_id>/e-learning/aps"

    def find(data, sid, tid):
        training = host.find_session(data, sid)
        if (not training or not is_vae(training)
                or training.get("partner_id") not in (None, "", host.INTEGRALE_PARTNER_ID)
                or host._current_partner_id() not in ("", host.INTEGRALE_PARTNER_ID)):
            abort(404)
        person = next((t for t in host._session_trainees_list(training) if t.get("id") == tid), None)
        if not person:
            abort(404)
        if host._trainee_registration_is_cancelled(person):
            abort(409, "Cette inscription est annulée.")
        return training, person

    def signer():
        return URLSafeTimedSerializer(host.app.secret_key, salt="desp-vae-aps-access")

    def message(person, token):
        url = host.PUBLIC_STUDENT_PORTAL_BASE.rstrip("/") + "/espace/" + quote(token, safe="")
        return render_template("emails/desp_vae_aps_access.html", first_name=person.get("first_name"), access_url=url,
                               email_heading=SUBJECT, email_eyebrow="Intégrale Academy · DESP VAE")

    @bp.get(route + "/apercu")
    @host.admin_login_required
    @host.admin_write_required
    def preview(session_id, trainee_id):
        _, person = find(host.load_data(run_background_tasks=False), session_id, trainee_id)
        token = person.get("public_token") or person.get("token") or uuid.uuid4().hex
        email = (person.get("email") or "").strip()
        nonce = session.setdefault("vae_aps_nonce", secrets.token_urlsafe(24))
        ticket = signer().dumps([session_id, trainee_id, nonce, token, email])
        response = jsonify(subject=SUBJECT, html=message(person, token), email=email,
                           can_send=bool(MAIL_RE.fullmatch(email)), ticket=ticket,
                           mail_available=(person.get(KEY) or {}).get("email_status") not in {"sent", "sending", "unconfirmed"})
        response.headers["Cache-Control"] = "no-store"
        return response

    @bp.post(route)
    @host.admin_login_required
    @host.admin_write_required
    def activate(session_id, trainee_id):
        payload = request.get_json() or {}
        try:
            sid, tid, nonce, token, email = signer().loads(payload.get("ticket", ""), max_age=1800)
        except (BadSignature, TypeError, ValueError):
            return jsonify(error="Rouvrez la fenêtre pour confirmer cet accès."), 400
        if (sid, tid, nonce) != (session_id, trainee_id, session.get("vae_aps_nonce")):
            abort(403)
        send = payload.get("send") is True

        def claim(data):
            training, person = find(data, sid, tid)
            current_token = person.get("public_token") or person.get("token")
            if current_token and current_token != token or send and email != (person.get("email") or "").strip():
                return {"error": "Les coordonnées ont changé. Rouvrez la fenêtre pour les vérifier."}
            if send and not MAIL_RE.fullmatch(email):
                return {"error": "Renseignez une adresse e-mail valide dans la fiche."}
            person["public_token"] = token
            if not active(training, person):
                person[KEY] = {"session_id": sid, "modules": aps_enrolments.modules(),
                               "activated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                               "email_status": "not_sent"}
            grant = person[KEY]
            if not send or grant["email_status"] in {"sent", "sending", "unconfirmed"}:
                return {"status": grant["email_status"]}
            grant.update(email_status="sending", delivery_id=str(uuid.uuid4()))
            return {"delivery_id": grant["delivery_id"], "html": message(person, token)}

        result = host._atomic_update_data(claim)
        if "error" in result:
            return jsonify(**result), 409
        if "delivery_id" not in result:
            return jsonify(**result)

        try:
            delivery = host.brevo_send_email(email, SUBJECT, result["html"], metadata={
                "purpose": "desp_vae_aps_access", "idempotency_key": result["delivery_id"],
                "session_id": sid, "trainee_id": tid})
        except Exception:
            host.app.logger.exception("desp_vae_aps_mail_unconfirmed")
            delivery = {}
        code = delivery.get("status_code")
        rejected = delivery.get("not_sent") or isinstance(code, int) and 400 <= code < 500 and code != 408
        status = "sent" if delivery.get("ok") else "failed" if rejected else "unconfirmed"

        def finish(data):
            # A cancellation during the send must still retain its receipt.
            training = host.find_session(data, sid) or {}
            for person in host._session_trainees_list(training):
                grant = person.get(KEY) or {}
                if person.get("id") == tid and grant.get("delivery_id") == result["delivery_id"]:
                    grant["email_status"] = status
                    if status == "sent":
                        now = dt.datetime.now(dt.timezone.utc).isoformat()
                        grant.update(sent_at=now, sent_to=email)
                        receipt = {"to_email": email, "subject": SUBJECT, "html": result["html"],
                                   "sent_at": now, "vae_aps_delivery": result["delivery_id"]}
                        person["sent_email_history"] = [receipt, *(person.get("sent_email_history") or [])][:200]
                    break
            return {}

        host._atomic_update_data(finish)
        return jsonify(status=status)

    host.app.register_blueprint(bp)
