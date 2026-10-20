"""SSIAP examination workspace, explicitly previewed jury mail and candidate evidence."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import hmac
import io
import json
import os
import re
import secrets
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request, session, send_file, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature

DEFAULTS = {
    "level": "SSIAP 1", "date": "", "time": "", "end_time": "", "arrival_time": "",
    "location": "Intégrale Academy", "address": "54 chemin du Carreou, 83480 PUGET SUR ARGENS",
    "contact_name": "Intégrale Academy", "contact_email": "ecole@integraleacademy.com",
    "contact_phone": "04 22 47 07 68", "approval": "Agrément SSIAP n°8323 délivré par la Préfecture du Var le 29/05/2026",
    "instructions": "", "equipment": "", "jury": [],
}
LIMITS = {"level": 12, "location": 160, "address": 300, "contact_name": 120,
          "contact_email": 254, "contact_phone": 40, "approval": 250,
          "instructions": 3000, "equipment": 1500}
MAIL_RE = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+")
DOC_GROUPS = [("identity", "Pièce d’identité", {"id"}),
              ("first_aid", "SST ou secourisme", {"attestation_secourisme_ssiap"}),
              ("medical", "Certificat médical", {"certificat_medical_ssiap", "certificat_medical_ssiap_afc"})]


def supported(training):
    label = str(training.get("training_type") or training.get("type") or "").upper()
    name = str(training.get("name") or training.get("nom") or "").upper()
    return "SSIAP" in label or "AFC" in label or "AFC" in name


def state(training):
    value = training.get("ssiap_exam")
    return value if isinstance(value, dict) else {}


def settings(training):
    # An AFC's generic exam_date belongs to APS, not necessarily to SSIAP.
    afc = "AFC" in (str(training.get("training_type") or "") + " " + str(training.get("name") or "")).upper()
    date = training.get("ssiap_exam_date") or ("" if afc else training.get("exam_date")) or ""
    match = re.search(r"SSIAP\s*([123])", str(training.get("training_type") or ""), re.I)
    return {**DEFAULTS, "date": date, "level": "SSIAP " + (match.group(1) if match else "1"),
            **state(training).get("config", {})}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


def candidate_settings(training, trainee):
    stored = state(training).get("candidates", {}).get(str(trainee["id"]), {})
    return {"included": stored.get("included", True) is not False}


def preserve_state(payload, canonical):
    """Only examination endpoints write this state; unrelated legacy saves cannot erase it."""
    if isinstance(canonical.get("ssiap_jury_directory"), dict):
        payload["ssiap_jury_directory"] = copy.deepcopy(canonical["ssiap_jury_directory"])
    by_id = {str(s.get("id")): s for s in canonical.get("sessions", [])}
    for training in payload.get("sessions", []):
        current = by_id.get(str(training.get("id")), {})
        if isinstance(current.get("ssiap_exam"), dict):
            training["ssiap_exam"] = copy.deepcopy(current["ssiap_exam"])


def frdate(value):
    try:
        return dt.date.fromisoformat(str(value)[:10]).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return "À renseigner"


def clean_date(value, label):
    value = str(value or "").strip()
    if value:
        try:
            return dt.date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError(f"{label} : date invalide.")
    return ""


def clean_text(value, label, limit):
    if not isinstance(value, (str, int, float)):
        raise ValueError(f"{label} : texte invalide.")
    value = str(value).strip()
    if len(value) > limit or "\x00" in value:
        raise ValueError(f"{label} : {limit} caractères maximum.")
    return value


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ValueError("Paramètres invalides.")
    result = {k: clean_text(raw.get(k, DEFAULTS[k]), k, limit) for k, limit in LIMITS.items()}
    if result["level"] not in {"SSIAP 1", "SSIAP 2", "SSIAP 3"}:
        raise ValueError("Niveau SSIAP invalide.")
    result["date"] = clean_date(raw.get("date"), "Examen")
    for key in ("time", "end_time", "arrival_time"):
        value = str(raw.get(key) or "").strip()
        if value and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("Horaire invalide.")
        result[key] = value
    if result["time"] and result["end_time"] and result["end_time"] <= result["time"]:
        raise ValueError("L’heure de fin doit suivre l’heure de début.")
    if result["time"] and result["arrival_time"] and result["arrival_time"] > result["time"]:
        raise ValueError("L’accueil du jury doit précéder le début de l’examen.")
    jury = raw.get("jury", [])
    if not isinstance(jury, list) or len(jury) > 12:
        raise ValueError("12 membres du jury au maximum.")
    result["jury"] = []
    ids = set()
    for item in jury:
        if not isinstance(item, dict):
            raise ValueError("Membre du jury invalide.")
        member = {k: clean_text(item.get(k, ""), k, limit) for k, limit in
                  (("id", 40), ("first_name", 80), ("last_name", 80), ("email", 254),
                   ("phone", 40), ("company", 160), ("role", 20))}
        member["id"] = member["id"] or secrets.token_hex(12)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,40}", member["id"]) or member["id"] in ids:
            raise ValueError("Identifiant du jury invalide ou dupliqué.")
        ids.add(member["id"])
        if not member["first_name"] or not member["last_name"]:
            raise ValueError("Renseignez le nom et le prénom de chaque membre du jury.")
        if member["role"] not in {"president", "member"}:
            raise ValueError("Précisez le rôle du membre du jury.")
        if member["email"] and not MAIL_RE.fullmatch(member["email"]):
            raise ValueError("Adresse e-mail du jury invalide.")
        member["last_name"] = member["last_name"].upper()
        result["jury"].append(member)
    if sum(m["role"] == "president" for m in result["jury"]) > 1:
        raise ValueError("Désignez un seul président du jury.")
    if result["contact_email"] and not MAIL_RE.fullmatch(result["contact_email"]):
        raise ValueError("Adresse e-mail du centre invalide.")
    return result


def validate_candidate(raw, config):
    if not isinstance(raw, dict):
        raise ValueError("Candidat invalide.")
    if not isinstance(raw.get("included"), bool):
        raise ValueError("Précisez si ce candidat est présenté à l’examen.")
    return {"included": raw["included"]}


def jury_directory(data, internal_partner_id):
    """Reusable contacts, including jurors recorded before the directory existed."""
    saved = copy.deepcopy(data.get("ssiap_jury_directory") or {})
    for training in data.get("sessions", []):
        if training.get("partner_id") not in (None, "", internal_partner_id):
            continue
        for member in settings(training)["jury"]:
            if member.get("id") and member.get("first_name") and member.get("last_name"):
                saved.setdefault(member["id"], member)
    unique = {}
    for member in saved.values():
        key = (member.get("email") or "").casefold() or member.get("id")
        if key and (key not in unique or member.get("updated_at", "") > unique[key].get("updated_at", "")):
            unique[key] = member
    return sorted(unique.values(), key=lambda m: (m.get("last_name", "").casefold(), m.get("first_name", "").casefold()))


def remember_jury(data, members, now, previous=()):
    directory = data.setdefault("ssiap_jury_directory", {})
    previous = {m['id']: m for m in previous}
    fields = ('first_name', 'last_name', 'email', 'phone', 'company', 'role')
    for member in members:
        # Stable directory identity; session copies remain snapshots of each exam.
        match = next((key for key, item in directory.items() if key == member["id"] or
                      (member["email"] and item.get("email", "").casefold() == member["email"].casefold())), member["id"])
        old = previous.get(member['id'], {})
        if match not in directory or any(member.get(k) != old.get(k) for k in fields):
            directory[match] = {**copy.deepcopy(member), "id": match, "updated_at": now}


def mail_status(training, member):
    result = {}
    for kind in ("invitation", "reminder"):
        entries = [entry for entry in state(training).get("mail_history", [])
                   if entry.get("kind") == kind and entry.get("jury_id") == member.get("id")
                   and entry.get('exam_date', settings(training)['date']) == settings(training)['date']
                   and entry.get("to", "").casefold() == member.get("email", "").casefold()]
        latest = entries[-1] if entries else {}
        successful = [entry for entry in entries if entry.get("status") == "sent"]
        last_sent = successful[-1] if successful else {}
        result[kind] = {"status": latest.get("status", "not_sent"),
                        "at": latest.get("finished_at") or latest.get("at", ""),
                        "last_sent_at": last_sent.get("finished_at") or last_sent.get("at", ""),
                        "sent_count": len(successful)}
    return result


def documents(services, trainee):
    groups = []
    for key, label, accepted in DOC_GROUPS:
        tokens = []
        review = []
        for document in trainee.get("documents") or []:
            if document.get("key") not in accepted:
                continue
            files = document.get("files") if isinstance(document.get("files"), list) else []
            tokens.extend([*files, document.get("file")])
            if str(document.get("status") or "").upper() in {"NON CONFORME", "À CONTRÔLER", "A CONTRÔLER"}:
                review.append(str(document.get("status")))
        if key == "first_aid":
            tokens.append((trainee.get("deliverables") or {}).get("carte_sst"))
        paths, seen, missing = [], set(), False
        for token in tokens:
            if not isinstance(token, str) or not token.strip() or token in seen:
                continue
            seen.add(token)
            if not services._partner_can_access_upload_token(token):
                missing = True
                continue
            path = services._detokenize_path(token)
            if os.path.isfile(path):
                paths.append(path)
            else:
                missing = True
        groups.append({"key": key, "label": label, "paths": paths,
                       "available": bool(paths) and not missing, "missing_file": missing,
                       "review": ", ".join(sorted(set(review)))})
    return groups


def photo_path(services, trainee):
    tokens = [trainee.get('identity_photo')]
    for document in trainee.get('documents') or []:
        if document.get('key') == 'photo':
            tokens.extend([document.get('file'), *(document.get('files') or [])])
    for token in tokens:
        if not isinstance(token, str) or not token or not services._partner_can_access_upload_token(token):
            continue
        path = services._detokenize_path(token)
        if os.path.isfile(path) and os.path.getsize(path) <= 25 * 1024 * 1024:
            return path
    return ''


def active_candidates(services, training):
    return sorted([t for t in services._session_trainees_list(training) if not services._trainee_registration_is_cancelled(t)],
                  key=lambda t: (str(t.get('last_name', '')).casefold(), str(t.get('first_name', '')).casefold()))


def build_mail(training, config, member, kind, count, logo_url, *, today=None):
    if kind not in {"invitation", "reminder"}:
        raise ValueError("Type de message invalide.")
    if not MAIL_RE.fullmatch(member.get("email", "")):
        raise ValueError("Renseignez une adresse e-mail valide pour ce membre du jury.")
    if not all(config.get(k) for k in ("date", "time", "location", "address")):
        raise ValueError("Renseignez la date, l’heure et le lieu de l’examen avant de préparer le mail.")
    if dt.date.fromisoformat(config["date"]) < (today or dt.datetime.now(ZoneInfo("Europe/Paris")).date()):
        raise ValueError("La date de cet examen est passée. Vérifiez-la avant d’envoyer un message.")
    from ssiap_exam_mail import render_mail
    return render_mail(config, member, kind, count, logo_url)


def register(app, services):
    def get_training(data, session_id):
        training = services.find_session(data, session_id)
        if not training or not supported(training):
            abort(404)
        # The official seal below belongs to Intégrale Academy only.
        if training.get("partner_id") not in (None, "", services.INTEGRALE_PARTNER_ID):
            abort(404)
        return training

    def read(session_id):
        return get_training(services.load_data(run_background_tasks=False), session_id)

    def active(training):
        return active_candidates(services, training)

    def find_candidate(training, trainee_id):
        trainee = next((t for t in active(training) if t.get("id") == trainee_id), None)
        if not trainee:
            abort(404)
        return trainee

    def csrf_payload():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400)
        token = session.get("ssiap_exam_csrf", "")
        if not token or not hmac.compare_digest(str(payload.get("csrf", "")), token):
            abort(403)
        return payload

    def response_pdf(content, filename):
        response = send_file(io.BytesIO(content), mimetype="application/pdf", as_attachment=request.args.get("download") == "1", download_name=filename)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    def mail(training, jury_id, kind):
        config = settings(training)
        member = next((m for m in config["jury"] if m["id"] == jury_id), None)
        if not member:
            raise ValueError("Membre du jury introuvable.")
        count = sum(candidate_settings(training, t)["included"] for t in active(training))
        return build_mail(training, config, member, kind, count,
                          url_for("static", filename="logo-integrale.png", _external=True))

    @app.get('/api/admin/sessions/<session_id>/ssiap-exam')
    @services.admin_login_required
    def api_ssiap_exam(session_id):
        from ssiap_exam_reminders import schedule
        all_data = services.load_data(run_background_tasks=False)
        training = get_training(all_data, session_id)
        rows = []
        for trainee in active(training):
            docs = documents(services, trainee)
            rows.append({"id": trainee["id"], "first_name": trainee.get("first_name", ""), "last_name": trainee.get("last_name", ""),
                         "candidate": candidate_settings(training, trainee), "result": services._ssiap_exam_status(trainee),
                         "documents": [{k: v for k, v in d.items() if k != "paths"} for d in docs],
                         "dossier_url": url_for('admin_ssiap_exam_dossier', session_id=session_id, trainee_id=trainee["id"]),
                         "pv_url": url_for('admin_ssiap_exam_individual', session_id=session_id, trainee_id=trainee["id"]),
                         "edit_url": url_for('admin_trainee_page', session_id=session_id, trainee_id=trainee["id"])})
        return jsonify(ok=True, config=settings(training), revision=state(training).get("revision", 0), candidates=rows,
                       read_only=session.get("admin_role") == "viewer", csrf=session.setdefault("ssiap_exam_csrf", secrets.token_urlsafe(32)),
                       excluded_count=sum(services._trainee_registration_is_cancelled(t) for t in services._session_trainees_list(training)),
                       history=state(training).get("mail_history", [])[-60:][::-1],
                       directory=jury_directory(all_data, services.INTEGRALE_PARTNER_ID),
                       mail_status={m["id"]: mail_status(training, m) for m in settings(training)["jury"]},
                       automatic_reminders=schedule(services, training),
                       attendance_url=url_for('admin_ssiap_exam_attendance', session_id=session_id),
                       collective_url=url_for('admin_ssiap_exam_collective', session_id=session_id))

    @app.post('/api/admin/sessions/<session_id>/ssiap-exam')
    @services.admin_login_required
    @services.admin_write_required
    def api_ssiap_exam_save(session_id):
        payload = csrf_payload()
        def update(data):
            training = get_training(data, session_id)
            current = copy.deepcopy(state(training))
            if payload.get("revision") != current.get("revision", 0):
                return {"ok": False, "error": "Ces informations ont changé. Fermez puis rouvrez la modale avant de réessayer.", "status": 409}
            try:
                if payload.get("action") == "config":
                    current["config"] = validate_config(payload.get("config"))
                    remember_jury(data, current["config"]["jury"], services._now_iso(), settings(training)["jury"])
                elif payload.get("action") == "candidate":
                    trainee = find_candidate(training, payload.get("trainee_id"))
                    candidate = validate_candidate(payload.get("candidate"), settings(training))
                    current.setdefault("candidates", {})[trainee["id"]] = candidate
                else:
                    raise ValueError("Action invalide.")
            except ValueError as exc:
                return {"ok": False, "error": str(exc), "status": 400}
            current["revision"] = current.get("revision", 0) + 1
            current["updated_at"] = services._now_iso()
            training["ssiap_exam"] = current
            return {"ok": True, "revision": current["revision"]}
        result = services._atomic_update_data(update)
        return jsonify(result), result.pop("status", 200)

    @app.get('/admin/sessions/<session_id>/ssiap-exam/candidates/<trainee_id>/dossier.pdf')
    @services.admin_login_required
    def admin_ssiap_exam_dossier(session_id, trainee_id):
        from ssiap_exam_pdf import dossier
        training = read(session_id)
        trainee = find_candidate(training, trainee_id)
        try:
            content = dossier(training, trainee, settings(training), candidate_settings(training, trainee), documents(services, trainee),
                              app.root_path, photo_path(services, trainee))
        except (ValueError, RuntimeError) as exc:
            return str(exc), 422
        return response_pdf(content, f"Dossier_examen_SSIAP_{services.secure_filename(trainee.get('last_name', ''))}_{trainee_id}.pdf")

    @app.get('/admin/sessions/<session_id>/ssiap-exam/candidates/<trainee_id>/pv.pdf')
    @services.admin_login_required
    def admin_ssiap_exam_individual(session_id, trainee_id):
        from ssiap_exam_pdf import individual
        training = read(session_id)
        trainee = find_candidate(training, trainee_id)
        try:
            content = individual(training, trainee, settings(training), candidate_settings(training, trainee), app.root_path)
        except ValueError as exc:
            return str(exc), 422
        return response_pdf(content, f"PV_individuel_SSIAP_{trainee_id}.pdf")

    @app.get('/admin/sessions/<session_id>/ssiap-exam/pv-collectif.pdf')
    @services.admin_login_required
    def admin_ssiap_exam_collective(session_id):
        from ssiap_exam_pdf import collective
        training = read(session_id)
        candidates = [t for t in active(training) if candidate_settings(training, t)["included"]]
        try:
            content = collective(training, candidates, settings(training), app.root_path)
        except (ValueError, RuntimeError) as exc:
            return str(exc), 422
        return response_pdf(content, f"PV_collectif_SSIAP_{session_id}.pdf")

    @app.get('/admin/sessions/<session_id>/ssiap-exam/presence.pdf')
    @services.admin_login_required
    def admin_ssiap_exam_attendance(session_id):
        from ssiap_exam_pdf import attendance
        training = read(session_id)
        candidates = [t for t in active(training) if candidate_settings(training, t)['included']]
        content = attendance(training, candidates, settings(training), app.root_path)
        return response_pdf(content, f'Feuille_presence_examen_SSIAP_{session_id}.pdf')

    @app.get('/api/admin/sessions/<session_id>/ssiap-exam/jury/<jury_id>/<kind>/preview')
    @services.admin_login_required
    def api_ssiap_exam_mail_preview(session_id, jury_id, kind):
        try:
            content = mail(read(session_id), jury_id, kind)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        token = URLSafeTimedSerializer(app.secret_key, salt="ssiap-exam-mail").dumps({
            "session": session_id, "jury": jury_id, "kind": kind, "fingerprint": digest(content), "nonce": secrets.token_hex(20)})
        return jsonify(ok=True, **content, preview_token=token)

    @app.post('/api/admin/sessions/<session_id>/ssiap-exam/mail/send')
    @services.admin_login_required
    @services.admin_write_required
    def api_ssiap_exam_mail_send(session_id):
        payload = csrf_payload()
        try:
            token = URLSafeTimedSerializer(app.secret_key, salt="ssiap-exam-mail").loads(str(payload.get("preview_token", "")), max_age=3600)
        except BadSignature:
            return jsonify(ok=False, error="Aperçu expiré. Prévisualisez à nouveau le mail."), 409
        if token.get("session") != session_id:
            abort(403)
        def reserve(data):
            training = get_training(data, session_id)
            try:
                content = mail(training, token["jury"], token["kind"])
            except ValueError as exc:
                return {"ok": False, "error": str(exc), "status": 409}
            if not hmac.compare_digest(digest(content), token["fingerprint"]):
                return {"ok": False, "error": "Les informations ont changé. Prévisualisez à nouveau le mail.", "status": 409}
            history = training.setdefault("ssiap_exam", {}).setdefault("mail_history", [])
            if any(entry.get("id") == token["nonce"] for entry in history):
                return {"ok": False, "error": "Cet envoi a déjà été pris en compte. Consultez l’historique.", "status": 409}
            if any(entry.get('status') == 'sending' and entry.get('kind') == token['kind']
                   and entry.get('to', '').casefold() == content['to'].casefold()
                   and entry.get('exam_date') == settings(training)['date'] for entry in history):
                return {'ok': False, 'error': 'Un envoi est déjà en cours pour ce membre du jury. Consultez l’historique.', 'status': 409}
            history.append({"id": token["nonce"], "to": content["to"], "subject": content["subject"], "kind": token["kind"],
                            "status": "sending", "at": services._now_iso(), "jury_id": token["jury"],
                            "exam_date": settings(training)['date'], "source": "manual"})
            return {"ok": True, "content": content}
        result = services._atomic_update_data(reserve)
        if not result["ok"]:
            return jsonify(result), result.pop("status", 409)
        content = result["content"]
        try:
            sent = services.brevo_send_email(content["to"], content["subject"], content["html"], text_content=content["text"],
                metadata={"purpose": "ssiap_exam_" + token["kind"], "session_id": session_id},
                reply_to=content["reply_to"])
            ok = sent.get("ok") is True if isinstance(sent, dict) else sent is True
            message_id = str(sent.get("message_id") or "") if isinstance(sent, dict) else ""
        except Exception:
            app.logger.exception("SSIAP jury email delivery failed")
            ok, message_id = False, ""
        def finish(data):
            training = get_training(data, session_id)
            for entry in state(training).get("mail_history", []):
                if entry.get("id") == token["nonce"]:
                    entry.update(status="sent" if ok else "failed", finished_at=services._now_iso(), message_id=message_id)
            return {}
        services._atomic_update_data(finish)
        return jsonify(ok=ok, error="" if ok else "L’envoi n’a pas été confirmé par le service mail. Consultez l’historique avant de réessayer."), 200 if ok else 502
