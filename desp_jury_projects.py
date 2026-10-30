"""Authenticated DESP initial jury documents, separate from enrolment evidence."""
import copy
from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
import uuid
import zipfile
from zoneinfo import ZoneInfo

from flask import abort, flash, redirect, request, send_file, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge

KEY = "desp_jury_project"
MAX_BYTES = 15_000_000
EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".odt", ".odp"}
SIZE_ERROR = "Le total de vos documents dépasse 15 Mo. Réduisez ou compressez vos fichiers avant de les déposer à nouveau."


def supported(services, training):
    kind = str(services._session_get(training, "training_type", "") or "").strip().upper()
    name = str(services._session_get(training, "name", "") or "")
    return kind in {"DIRIGEANT INITIAL", "DESP INITIAL", "DIRIGEANT", "DESP"} and not re.search(r"\b(VAE|MAC|RECYCLAGE)\b", name, re.I)


def today():
    return datetime.now(ZoneInfo("Europe/Paris")).date()


def public_available(services, training):
    start = services._parse_iso_date(str(services._session_get(training, "dirigeant_in_person_start", "") or "").strip())
    return bool(start and (today() - start).days >= 7)


def state(trainee):
    value = trainee.get(KEY)
    return value if isinstance(value, dict) else {}


def documents(trainee):
    return [item for item in state(trainee).get("documents", [])
            if isinstance(item, dict) and item.get("slot") in (1, 2) and item.get("file")]


def preserve_state(payload, canonical, trainees, default_partner):
    """Unrelated stale page saves must not undo a deposit, replacement or deletion."""
    sessions = {(s.get("partner_id") or default_partner, str(s.get("id"))): s
                for s in canonical.get("sessions", [])}
    for training in payload.get("sessions", []):
        saved = sessions.get((training.get("partner_id") or default_partner, str(training.get("id"))), {})
        people = {str(t.get("id")): t for t in trainees(saved)}
        for trainee in trainees(training):
            current = state(people.get(str(trainee.get("id")), {}))
            if current and int(current.get("revision", 0)) >= int(state(trainee).get("revision", 0)):
                trainee[KEY] = copy.deepcopy(current)


def base_name(services, trainee):
    name = " ".join(filter(None, (services.normalize_first_name(trainee.get("first_name") or ""),
                                 services.normalize_last_name(trainee.get("last_name") or ""))))
    name = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', " ", name)
    return "Projet de cadrage " + (" ".join(name.split())[:150] or str(trainee["id"]))


def download_name(services, trainee, document):
    suffix = f" - {document['slot']}" if len(documents(trainee)) > 1 else ""
    return base_name(services, trainee) + suffix + Path(document["original_name"]).suffix.lower()


def view(services, training, trainee, *, token=None):
    if not supported(services, training) or (token and not public_available(services, training)):
        return None
    rows = documents(trainee)
    endpoint = "public_desp_project_download" if token else "admin_desp_project_download"
    args = {"token": token} if token else {"session_id": training["id"], "trainee_id": trainee["id"]}
    return {
        "documents": [{**row, "download_name": download_name(services, trainee, row),
                       "download_url": url_for(endpoint, slot=row["slot"], **args)} for row in rows],
        "revision": int(state(trainee).get("revision", 0)),
        "total_bytes": sum(row["size"] for row in rows),
        "max_bytes": MAX_BYTES,
        "accept": ",".join(sorted(EXTENSIONS)),
        "download_url": url_for(endpoint, **args) if rows else None,
        "upload_url": url_for("public_desp_project_upload", token=token) if token else None,
        "can_upload": bool(token and session.get("admin_role") != "viewer"
                           and not services._trainee_registration_is_cancelled(trainee)),
    }


def _root(services, training, trainee):
    partner = training.get("partner_id") or services.INTEGRALE_PARTNER_ID
    return (Path(services.get_partner_storage_path(partner, "stagiaires"))
            / services._safe_upload_identifier(training["id"], "session_id")
            / services._safe_upload_identifier(trainee["id"], "trainee_id") / KEY).resolve()


def _path(services, training, trainee, document, *, must_exist=True):
    root = _root(services, training, trainee)
    path = Path(services._detokenize_path(document["file"])).resolve()
    if path.parent != root or (must_exist and not path.is_file()):
        abort(404, description="Ce document n’est plus disponible.")
    return path


def register(app, services):
    def pair(data, *, token=None, session_id=None, trainee_id=None):
        if token:
            training, trainee = services.find_session_and_trainee_by_token(data, token)
        else:
            training = services.find_session(data, session_id)
            trainee = next((t for t in services._session_trainees_list(training or {})
                            if str(t.get("id")) == trainee_id), None)
        if not training or not trainee or not supported(services, training):
            abort(404)
        if token and not public_available(services, training):
            abort(404)
        return training, trainee

    def back(token, message, category="error"):
        flash(message, "desp_project_" + category)
        return redirect(url_for("public_trainee_space", token=token) + "#projet-cadrage")

    @app.post("/espace/<token>/projet-cadrage")
    @services.admin_write_required
    def public_desp_project_upload(token):
        if not services._public_is_authed(token):
            return redirect(url_for("public_trainee_login", token=token))
        training, trainee = pair(services.load_data(run_background_tasks=False), token=token)
        if services._trainee_registration_is_cancelled(trainee):
            abort(403)
        new_paths = []
        old_paths = []
        try:
            # Bound multipart overhead too, with the same useful message even for huge uploads.
            if request.content_length and request.content_length > MAX_BYTES + 128 * 1024:
                raise ValueError(SIZE_ERROR)
            if not services.trainee_checks.valid_request():
                abort(403)
            incoming = [(key, f) for key, f in request.files.items(multi=True) if f.filename]
            if len(incoming) > 2 or any(key not in {"file_1", "file_2"} for key, _ in incoming) or len({key for key, _ in incoming}) != len(incoming):
                raise ValueError("Vous pouvez déposer 1 ou 2 documents au maximum.")
            replacements = {}
            total = 0
            for key, upload in incoming:
                filename = re.split(r"[/\\]", upload.filename)[-1][:200]
                extension = Path(filename).suffix.lower()
                if extension not in EXTENSIONS:
                    raise ValueError("Choisissez un document PDF, Word, PowerPoint ou OpenDocument.")
                content = upload.stream.read(MAX_BYTES - total + 1)
                total += len(content)
                if total > MAX_BYTES:
                    raise ValueError(SIZE_ERROR)
                if not content:
                    raise ValueError("Un document est vide. Choisissez un fichier contenant votre projet.")
                replacements[int(key[-1])] = (filename, content)
            removed = {slot for slot in (1, 2) if request.form.get(f"remove_{slot}") == "1"}
            try:
                revision = int(request.form.get("revision", ""))
            except ValueError:
                raise ValueError("Rechargez la page avant d’enregistrer vos documents.")
            if not replacements and not removed:
                raise ValueError("Choisissez 1 ou 2 documents à déposer.")
            root = _root(services, training, trainee)

            def mutate(data):
                current_training, current = pair(data, token=token)
                if _root(services, current_training, current) != root or services._trainee_registration_is_cancelled(current):
                    abort(403)
                if int(state(current).get("revision", 0)) != revision:
                    raise ValueError("Vos documents ont changé dans un autre onglet. Rechargez la page puis recommencez.")
                existing = documents(current)
                retained = [row for row in existing if row["slot"] not in removed | replacements.keys()]
                retained_bytes = sum(_path(services, current_training, current, row).stat().st_size for row in retained)
                if retained_bytes + total > MAX_BYTES:
                    raise ValueError(SIZE_ERROR)
                now = services._now_iso()
                rows = list(retained)
                root.mkdir(parents=True, exist_ok=True)
                for slot, (filename, content) in replacements.items():
                    path = root / (uuid.uuid4().hex + Path(filename).suffix.lower())
                    new_paths.append(path)
                    path.write_bytes(content)
                    rows.append({"slot": slot, "file": services._tokenize_path(str(path)),
                                 "original_name": filename, "size": len(content), "uploaded_at": now})
                old_paths.extend(_path(services, current_training, current, row, must_exist=False)
                                 for row in existing if row not in retained)
                current[KEY] = {"revision": revision + 1, "updated_at": now,
                                "documents": sorted(rows, key=lambda row: row["slot"])}
                current["updated_at"] = now
                services.append_trainee_history_event(current, "Projet de cadrage mis à jour",
                                                     f"{len(rows)} document(s) pour le jury DESP", "document")
                return {"count": len(rows)}

            result = services._atomic_update_data(mutate, partner_id=training.get("partner_id") or services.INTEGRALE_PARTNER_ID)
        except (ValueError, RequestEntityTooLarge) as error:
            for path in new_paths:
                path.unlink(missing_ok=True)
            return back(token, SIZE_ERROR if isinstance(error, RequestEntityTooLarge) else str(error))
        except Exception:
            for path in new_paths:
                path.unlink(missing_ok=True)
            raise
        # The new record is durable before superseded files are removed.
        for path in old_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                app.logger.warning("Could not remove a superseded DESP project document")
        return back(token, "Vos documents pour le jury ont bien été enregistrés." if result["count"]
                    else "Vos documents ont été retirés.", "success")

    def download(training, trainee):
        rows = documents(trainee)
        selected = request.args.get("slot")
        if selected is not None:
            rows = [row for row in rows if str(row["slot"]) == selected]
        if not rows:
            abort(404)
        if len(rows) == 1:
            response = send_file(_path(services, training, trainee, rows[0]), as_attachment=True,
                                 download_name=download_name(services, trainee, rows[0]))
        else:
            output = BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
                for row in rows:
                    archive.write(_path(services, training, trainee, row), download_name(services, trainee, row))
            output.seek(0)
            response = send_file(output, as_attachment=True, mimetype="application/zip",
                                 download_name=base_name(services, trainee) + ".zip")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/espace/<token>/projet-cadrage/download")
    def public_desp_project_download(token):
        if not services._public_is_authed(token):
            return redirect(url_for("public_trainee_login", token=token))
        return download(*pair(services.load_data(run_background_tasks=False), token=token))

    @app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/projet-cadrage/download")
    @services.admin_login_required
    def admin_desp_project_download(session_id, trainee_id):
        return download(*pair(services.load_data(run_background_tasks=False), session_id=session_id, trainee_id=trainee_id))
