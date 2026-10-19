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
from html import escape

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
    result = {"included": True, "grade": "", "written": "", "written_date": "", "practical": "",
              "practical_date": "", "reason": "", "independence": False, "ability": False,
              "evaluation_date": "", **stored}
    result["independence"] = result["independence"] is True and stored.get("jury_fingerprint") == digest(settings(training)["jury"])
    return result


def preserve_state(payload, canonical):
    """Only examination endpoints write this state; unrelated legacy saves cannot erase it."""
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
    result = {}
    for key in ("included", "independence", "ability"):
        if not isinstance(raw.get(key), bool):
            raise ValueError("Validez les options du candidat.")
        result[key] = raw[key]
    grade = str(raw.get("grade") if raw.get("grade") is not None else "").strip().replace(",", ".")
    if grade and (not re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", grade) or not 0 <= float(grade) <= 20):
        raise ValueError("La note doit être comprise entre 0 et 20.")
    result["grade"] = grade
    for key, options in (("written", {"", "valid", "failed"}), ("practical", {"", "fit", "unfit"})):
        if raw.get(key, "") not in options:
            raise ValueError("Résultat d’épreuve invalide.")
        result[key] = raw.get(key, "")
    for key in ("written_date", "practical_date", "evaluation_date"):
        result[key] = clean_date(raw.get(key), "Évaluation")
    result["reason"] = clean_text(raw.get("reason", ""), "Motivation", 650)
    if result["ability"] and not result["evaluation_date"]:
        raise ValueError("Renseignez la date de l’évaluation réalisée par le centre.")
    if result["independence"] and not config["jury"]:
        raise ValueError("Renseignez le jury avant de valider l’attestation d’indépendance.")
    result["jury_fingerprint"] = digest(config["jury"])
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


def build_mail(training, config, member, kind, count, logo_url):
    if kind not in {"invitation", "reminder"}:
        raise ValueError("Type de message invalide.")
    if not MAIL_RE.fullmatch(member.get("email", "")):
        raise ValueError("Renseignez une adresse e-mail valide pour ce membre du jury.")
    if not all(config.get(k) for k in ("date", "time", "location", "address")):
        raise ValueError("Renseignez la date, l’heure et le lieu de l’examen avant de préparer le mail.")
    if dt.date.fromisoformat(config["date"]) < dt.datetime.now(dt.timezone.utc).date():
        raise ValueError("La date de cet examen est passée. Vérifiez-la avant d’envoyer un message.")
    title = "Rappel de votre participation au jury" if kind == "reminder" else "Votre participation au jury"
    subject = f"{'Rappel' if kind == 'reminder' else 'Jury'} - Examen {config['level']} du {frdate(config['date'])} à {config['time']}"
    role = "président du jury" if member["role"] == "president" else "membre du jury"
    intro = ("Nous vous rappelons votre participation" if kind == "reminder" else "Nous avons le plaisir de vous transmettre les informations relatives à votre participation")
    lines = [f"Bonjour {member['first_name']} {member['last_name']},", "",
             f"{intro} en qualité de {role} à l’examen {config['level']} organisé par Intégrale Academy.", "",
             f"Date : {frdate(config['date'])}", f"Début de l’examen : {config['time']}"]
    if config["arrival_time"]:
        lines.append(f"Accueil du jury : {config['arrival_time']}")
    if config["end_time"]:
        lines.append(f"Fin prévisionnelle : {config['end_time']}")
    lines += [f"Lieu : {config['location']}", config["address"], f"Candidats présentés : {count}"]
    if config["instructions"]:
        lines += ["", "Informations pratiques", config["instructions"]]
    lines += ["", "Merci de nous confirmer votre présence en répondant à ce mail. En cas d’empêchement, merci de prévenir le centre dès que possible.",
              "", "Bien cordialement,", config["contact_name"], config["contact_phone"], config["contact_email"]]
    text = "\n".join(lines)
    paragraphs = "".join(f'<p style="margin:0 0 12px;line-height:1.65">{escape(line)}</p>' if line else '<div style="height:8px"></div>' for line in lines)
    html = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"></head><body style="margin:0;background:#eef2f7;font-family:Arial,sans-serif;color:#172b43"><table role="presentation" width="100%"><tr><td align="center" style="padding:24px 12px"><table role="presentation" width="100%" style="max-width:640px;background:white;border-radius:18px;overflow:hidden"><tr><td style="padding:28px;background:#0c1a2f;color:white"><img src="{escape(logo_url, quote=True)}" alt="Intégrale Academy" width="130"><p style="font-size:12px;letter-spacing:2px;color:#9ed4cb">EXAMEN {escape(config['level'])}</p><h1 style="font-size:27px;margin:10px 0">{title}</h1><p>{frdate(config['date'])} · {config['time']}</p></td></tr><tr><td style="padding:28px">{paragraphs}</td></tr></table></td></tr></table></body></html>'''
    return {"to": member["email"], "subject": subject, "html": html, "text": text,
            "reply_to": {"email": config["contact_email"], "name": config["contact_name"]}}


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
        return sorted([t for t in services._session_trainees_list(training) if not services._trainee_registration_is_cancelled(t)],
                      key=lambda t: (str(t.get("last_name", "")).casefold(), str(t.get("first_name", "")).casefold()))

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
        training = read(session_id)
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
                       history=state(training).get("mail_history", [])[-30:][::-1],
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
                elif payload.get("action") == "candidate":
                    trainee = find_candidate(training, payload.get("trainee_id"))
                    candidate = validate_candidate(payload.get("candidate"), settings(training))
                    candidate["validated_at"] = services._now_iso()
                    candidate["validated_by"] = str(session.get("admin_username") or session.get("admin_user_id") or "Administration")
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
                              services._training_center_signature_assets, app.root_path)
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
        return response_pdf(collective(training, candidates, settings(training), app.root_path), f"PV_collectif_SSIAP_{session_id}.pdf")

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
            history.append({"id": token["nonce"], "to": content["to"], "subject": content["subject"], "kind": token["kind"],
                            "status": "sending", "at": services._now_iso(), "jury_id": token["jury"]})
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
