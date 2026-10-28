"""Review SSIAP results and diploma data without changing the enrolment record."""
import copy
import datetime as dt
import hmac
import json
import os
import re
import secrets

from flask import abort, jsonify, request, send_file, session, url_for

import ssiap_exam as exam
from identity_photos import photo_metadata


FIELDS = ("civility", "first_name", "last_name", "birth_date", "birth_city",
          "birth_department", "birth_country", "exam_date")
LABELS = {"first_name": "prénom", "last_name": "nom", "birth_date": "date de naissance",
          "birth_city": "ville de naissance", "birth_department": "département de naissance",
          "birth_country": "pays de naissance", "exam_date": "date d’examen"}


def french(services, country):
    return services._normalized_commune_name(country) in {"", "FRANCE", "FR", "FRA"}


def iso_date(services, value):
    formatted = services._diploma_date_fr(value)
    return dt.datetime.strptime(formatted, "%d/%m/%Y").date().isoformat() if formatted else ""


def values(services, training, trainee):
    result = {key: str(trainee.get("ssiap_diploma_" + key, trainee.get(key)) or "").strip()
              for key in FIELDS}
    result["civility"] = result["civility"] or "Monsieur"
    result["birth_country"] = result["birth_country"] or "France"
    result["birth_city"] = services.normalize_city(
        result["birth_city"] if "ssiap_diploma_birth_city" in trainee else result["birth_city"] or trainee.get("birth_place") or "")
    result["first_name"] = services._ssiap_diploma_first_name(result["first_name"])
    result["last_name"] = services.normalize_last_name(result["last_name"])
    result["birth_date"] = iso_date(services, result["birth_date"])
    result["exam_date"] = iso_date(services, services._ssiap_diploma_exam_date(training, trainee))
    if french(services, result["birth_country"]):
        department = result["birth_department"]
        if "ssiap_diploma_birth_department" not in trainee:
            department = department or trainee.get("department") or trainee.get("birth_postal_code") or trainee.get("birth_zip_code")
        result["birth_department"] = services._normalize_department_code(department)
    else:
        result["birth_department"] = ""
    result["result"] = services._ssiap_exam_status(trainee)
    return result


def missing(services, info):
    required = ["first_name", "last_name", "birth_date", "birth_city", "birth_country", "exam_date"]
    if french(services, info["birth_country"]) and not re.search(r"\((?:\d{2,3}|2A|2B)\)$", info["birth_city"]):
        required.append("birth_department")
    return [LABELS[key] for key in required if not info[key]]


def revision(services, training, trainee):
    return exam.digest({"values": values(services, training, trainee),
                        "number": trainee.get("ssiap_diploma_number", ""),
                        "included": exam.candidate_settings(training, trainee)["included"]})


def apply_info(trainee, info):
    trainee.update({"ssiap_diploma_" + key: info[key] for key in FIELDS})
    trainee["ssiap_exam_status"] = info["result"]


def clean(services, raw):
    if not isinstance(raw, dict):
        raise ValueError("Informations du diplôme invalides.")
    info = {}
    for key in FIELDS:
        value = str(raw.get(key) or "").strip()
        if len(value) > 120:
            raise ValueError("Un champ du diplôme dépasse 120 caractères.")
        if key in {"birth_date", "exam_date"} and value:
            parsed = iso_date(services, value)
            if not parsed:
                raise ValueError(f"Vérifiez la {LABELS[key]}.")
            value = parsed
        info[key] = value
    if info["civility"] not in {"Monsieur", "Madame"}:
        raise ValueError("Choisissez une civilité.")
    info["result"] = raw.get("result")
    if info["result"] not in services.SSIAP_EXAM_STATUSES:
        raise ValueError("Choisissez un résultat valide.")
    info["first_name"] = services._ssiap_diploma_first_name(info["first_name"])
    info["last_name"] = services.normalize_last_name(info["last_name"])
    info["birth_city"] = services.normalize_city(info["birth_city"])
    if french(services, info["birth_country"]):
        info["birth_country"] = "France"
        department = info["birth_department"]
        if department and not services._normalize_department_code(department):
            raise ValueError("Département invalide : utilisez un code comme 74, 2A ou 972.")
        info["birth_department"] = services._normalize_department_code(department)
    else:
        info["birth_department"] = ""
    return info


def register(app, services, get_training):
    def rows(training):
        return [{"id": str(t["id"]), "values": values(services, training, t),
                 "revision": revision(services, training, t),
                 "included": exam.candidate_settings(training, t)["included"],
                 "number": str(t.get("ssiap_diploma_number") or ""),
                 **{key: value for key, value in photo_metadata(services, session_id=training['id'], trainee=t).items()
                    if key in {'photo_available', 'photo_url', 'photo_api'}},
                 "missing": missing(services, values(services, training, t))}
                for t in exam.active_candidates(services, training)]

    @app.get('/api/admin/sessions/<session_id>/ssiap-exam/diplomas')
    @services.admin_login_required
    def api_ssiap_diplomas(session_id):
        training = get_training(services.load_data(run_background_tasks=False), session_id)
        response = jsonify(ok=True, candidates=rows(training),
                           exam_number=exam.settings(training).get("exam_number", ""),
                           exam_date=exam.settings(training).get("date", ""),
                           csrf=session.setdefault("ssiap_exam_csrf", secrets.token_urlsafe(32)),
                           read_only=session.get("admin_role") == "viewer",
                           department_url=url_for("admin_ssiap_birth_department"))
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get('/api/admin/sessions/<session_id>/ssiap-exam/diplomas/preview')
    @app.post('/api/admin/sessions/<session_id>/ssiap-exam/diplomas')
    @services.admin_login_required
    def api_ssiap_diplomas_action(session_id):
        payload = ({"action": "letter_preview" if request.args.get("document") == "letter" else "preview", **({"trainee_id": request.args["trainee_id"]} if "trainee_id" in request.args else {})}
                   if request.method == "GET" else request.get_json(silent=True))
        if not isinstance(payload, dict):
            abort(400)
        csrf = session.get("ssiap_exam_csrf", "")
        if request.method != "GET" and (not csrf or not hmac.compare_digest(str(payload.get("csrf", "")), csrf)):
            abort(403)
        action = payload.get("action")
        if action not in {"save", "preview", "generate", "letter", "letter_preview"}:
            return jsonify(ok=False, error="Action invalide."), 400
        is_preview = action in {"preview", "letter_preview"}
        is_letter = action in {"letter", "letter_preview"}
        if not is_preview and session.get("admin_role") == "viewer":
            abort(403)
        training = get_training(services.load_data(run_background_tasks=False), session_id)
        current = {str(t["id"]): t for t in exam.active_candidates(services, training)}
        try:
            changes = payload.get("candidates", [])
            if not isinstance(changes, list) or len(changes) > len(current):
                raise ValueError("Liste de candidats invalide.")
            prepared = {}
            for change in changes:
                if not isinstance(change, dict) or str(change.get("id")) not in current:
                    abort(404)
                key = str(change["id"])
                if key in prepared:
                    raise ValueError("Candidat présent plusieurs fois.")
                info = clean(services, change.get("values"))
                # Resolve outside the data transaction; never hold its lock during network I/O.
                selected_preview = (str(payload.get("trainee_id")) == key if payload.get("trainee_id") is not None
                                    else info["result"] == "certified" and exam.candidate_settings(training, current[key])["included"])
                if (action == "save" or is_preview and selected_preview) and not info["birth_department"] and info["birth_city"] and french(services, info["birth_country"]):
                    info["birth_department"] = services._lookup_birth_department_code(info["birth_city"])
                prepared[key] = (info, change.get("revision"))

            if action == "save":
                def update(data):
                    canonical = get_training(data, session_id)
                    trainees = {str(t["id"]): t for t in exam.active_candidates(services, canonical)}
                    for key, (_, expected) in prepared.items():
                        if key not in trainees or expected != revision(services, canonical, trainees[key]):
                            return {"ok": False, "error": "Un dossier a changé depuis son ouverture. Actualisez les diplômes avant de réessayer.", "status": 409}
                    for key, (info, _) in prepared.items():
                        apply_info(trainees[key], info)
                    return {"ok": True, "candidates": rows(canonical)}
                result = services._atomic_update_data(update)
                status = result.pop("status", 200)
                return jsonify(result), status

            if not services.REPORTLAB_LIBRARY_AVAILABLE or (not is_letter and not os.path.exists(services.SSIAP_DIPLOMA_TEMPLATE)):
                return jsonify(ok=False, error="Le modèle ou le moteur PDF est indisponible."), 503
            candidate_id = payload.get("trainee_id")
            if is_letter and candidate_id is not None:
                raise ValueError("Le courrier doit reprendre l’ensemble des candidats certifiés de l’examen.")
            if candidate_id is not None and str(candidate_id) not in current:
                abort(404)
            candidates = []
            for key, original in current.items():
                trainee = copy.deepcopy(original)
                if is_preview and key in prepared:
                    apply_info(trainee, prepared[key][0])
                if candidate_id is not None:
                    if key != str(candidate_id):
                        continue
                elif services._ssiap_exam_status(trainee) != "certified" or not exam.candidate_settings(training, trainee)["included"]:
                    continue
                candidates.append(trainee)
            if not candidates and not (is_letter and is_preview):
                raise ValueError("Aucun candidat certifié et présenté à cet examen.")
            config = exam.settings(training)
            if is_letter and not is_preview:
                from ssiap_exam_pdf import signature_assets
                signature_assets(app.root_path)
                if not config.get("exam_number") or not config.get("date"):
                    raise ValueError("Renseignez le numéro et la date de l’examen dans Organisation et jury avant de générer le courrier SDIS.")
                expected_date = services._diploma_date_fr(config["date"])
                if any(services._ssiap_diploma_exam_date(training, t) != expected_date for t in candidates):
                    raise ValueError("La date d’examen de chaque diplôme doit correspondre à celle de cet examen avant de préparer le courrier SDIS.")
            if not is_preview:
                for trainee in candidates:
                    services._ssiap_birth_place_label(trainee)
                incomplete = [f"{t.get('first_name', '')} {t.get('last_name', '')} : {', '.join(missing(services, values(services, training, t)))}"
                              for t in candidates if missing(services, values(services, training, t))]
                if incomplete:
                    raise ValueError("Complétez les informations avant de générer : " + "; ".join(incomplete))
                canonical, diplomas = services._reserve_ssiap_diploma_numbers(session_id, candidate_id, require_exam_date_match=is_letter)
                config = exam.settings(exam.for_family(canonical, "ssiap"))
            else:
                diplomas = [services._ssiap_diploma_row(training, t, lookup_department=False) for t in candidates]
                for diploma in diplomas:
                    for field in ("name", "birth_date", "birth_place", "exam_date"):
                        diploma[field] = diploma[field] or "À renseigner"
                    diploma["number"] = diploma["number"] or ("À générer" if is_letter else "APERÇU")
            if is_letter:
                from ssiap_diploma_documents import sdis_letter
                content = sdis_letter(diplomas, config, app.root_path, preview=is_preview)
            else:
                content = services._build_ssiap_diplomas_pdf(diplomas, preview=is_preview)
            kind = "courrier-SDIS" if is_letter else "diplomes-SSIAP"
            response = send_file(content, mimetype="application/pdf", as_attachment=not is_preview,
                                 download_name=f"{'apercu-' if is_preview else ''}{kind}-{services.secure_filename(session_id)}.pdf")
            response.headers["Cache-Control"] = "private, no-store"
            if not is_preview:
                response.headers["X-SSIAP-Diploma-Numbers"] = json.dumps({row["trainee_id"]: row["number"] for row in diplomas})
            return response
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except LookupError:
            abort(404)
        except RuntimeError as exc:
            return jsonify(ok=False, error=str(exc)), 503
