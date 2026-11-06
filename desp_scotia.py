"""Complete, tenant-scoped DESP initial examination dossiers, assembled on demand."""
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from flask import abort, jsonify, request, send_file, url_for
from pypdf import PdfReader, PdfWriter
from werkzeug.exceptions import HTTPException

import desp_jury_projects as projects
from document_conversion import convert_upload, _validate_pdf

GROUPS = (
    ("candidate_info_sheet", "Fiche de renseignement candidat"),
    ("desp_exam_sworn_statement", "Attestation sur l’honneur de prise en compte de l’examen DESP"),
    ("project", "Projet de cadrage"),
    ("elearning", "Attestation e-learning"),
)
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DOSSIER_BYTES = 75 * 1024 * 1024


def _tokens(trainee, key):
    result = []
    for document in trainee.get("documents") or []:
        if not isinstance(document, dict) or document.get("key") != key:
            continue
        files = document.get("files") if isinstance(document.get("files"), list) else []
        for value in [document.get("file"), *files]:
            if isinstance(value, str) and value.strip() and value not in result:
                result.append(value)
    return result


def _saved_sheet(trainee):
    sheet = trainee.get("candidate_sheet")
    return isinstance(sheet, dict) and any(str(value or "").strip() for value in sheet.values())


def _read_file(host, training, trainee, token, *, project=None):
    if not host._partner_can_access_upload_token(token):
        raise ValueError("Fichier inaccessible.")
    path = (projects._path(host, training, trainee, project) if project
            else Path(host._detokenize_path(token)))
    if not path.is_file():
        raise ValueError("Fichier introuvable : déposez-le à nouveau.")
    with path.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Fichier trop volumineux : réduisez sa taille.")
    if project:
        if path.suffix.lower() != ".pdf" or Path(project.get("original_name", "")).suffix.lower() != ".pdf":
            raise ValueError("Remplacez ce projet par un PDF.")
        _validate_pdf(raw)
        return raw
    # Historical candidate/attestation scans may be JPEG or PNG. Preserve every
    # page and convert them locally; never silently drop an unreadable attachment.
    if path.suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png"}:
        raise ValueError("Remplacez cette pièce par un PDF ou une image JPEG/PNG.")
    return convert_upload(raw, path.name)[0]


def certificate_path(host, training, trainee):
    root = Path(host.get_partner_storage_path(
        training.get("partner_id") or host.INTEGRALE_PARTNER_ID, "stagiaires"))
    return (root / host._safe_upload_identifier(training["id"], "session_id")
            / host._safe_upload_identifier(trainee["id"], "trainee_id")
            / "desp_exam" / "attestation-elearning.pdf")


def inspect(host, training, trainee, *, include_content=False):
    groups, parts, total = [], [], 0
    for key, label in GROUPS:
        error, content = "", []
        try:
            if key == "elearning":
                path = certificate_path(host, training, trainee)
                if not path.is_file():
                    raise ValueError("Attestation e-learning à déposer.")
                with path.open("rb") as source:
                    raw = source.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError("Attestation trop volumineuse.")
                _validate_pdf(raw)
                content = [raw]
            elif key == "project":
                entries = sorted(projects.documents(trainee), key=lambda item: item["slot"])
                if not entries:
                    raise ValueError("Au moins un PDF de projet est requis.")
                if len(entries) > 2 or len({item["slot"] for item in entries}) != len(entries):
                    raise ValueError("Vérifiez les documents du projet de cadrage.")
                content = [_read_file(host, training, trainee, row["file"], project=row) for row in entries]
            else:
                tokens = _tokens(trainee, key)
                if tokens:
                    content = [_read_file(host, training, trainee, token) for token in tokens]
                elif key == "candidate_info_sheet" and _saved_sheet(trainee):
                    # This item is normally an online form, not an uploaded file.
                    if include_content:
                        from desp_scotia_sheet import build
                        content = [build(host._build_candidate_sheet_data(training, trainee),
                                         host, trainee)]
                else:
                    raise ValueError("Pièce manquante." if key != "candidate_info_sheet"
                                     else "Fiche candidat à compléter et enregistrer.")
            total += sum(len(raw) for raw in content)
            if total > MAX_DOSSIER_BYTES:
                raise ValueError("Le dossier dépasse 75 Mo. Réduisez la taille des pièces.")
        except (ValueError, OSError, HTTPException) as exc:
            error = str(exc) if isinstance(exc, ValueError) else "Fichier introuvable ou inaccessible."
        groups.append({"key": key, "label": label, "available": not error, "error": error})
        if include_content and not error:
            parts.extend(content)
    return groups, parts


def register(app, host):
    def training_or_404(session_id):
        training = host.find_session(host.load_data(run_background_tasks=False), session_id)
        if not training or not projects.supported(host, training):
            abort(404)
        return training

    def candidate(session_id, trainee_id):
        training = training_or_404(session_id)
        trainee = next((t for t in host._registered_trainees(training)
                        if str(t.get("id")) == trainee_id), None)
        if not trainee:
            abort(404)
        return training, trainee

    @app.get("/api/admin/sessions/<session_id>/desp-attestations")
    @host.admin_login_required
    def api_desp_certificates(session_id):
        training = training_or_404(session_id)
        rows = []
        for trainee in sorted(host._registered_trainees(training),
                              key=lambda t: (str(t.get("last_name") or "").casefold(),
                                             str(t.get("first_name") or "").casefold())):
            url = url_for("admin_desp_certificate", session_id=session_id, trainee_id=trainee["id"])
            rows.append({"name": " ".join(filter(None, [host.normalize_first_name(trainee.get("first_name") or ""),
                                                        host.normalize_last_name(trainee.get("last_name") or "")])),
                         "url": url, "available": certificate_path(host, training, trainee).is_file()})
        return jsonify(candidates=rows), 200, {"Cache-Control": "private, no-store"}

    @app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/attestation-elearning.pdf")
    @host.admin_login_required
    def admin_desp_certificate(session_id, trainee_id):
        path = certificate_path(host, *candidate(session_id, trainee_id))
        if not path.is_file():
            abort(404)
        response = send_file(path, mimetype="application/pdf", download_name="Attestation e-learning.pdf")
        response.headers.update({"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
        return response

    @app.post("/admin/sessions/<session_id>/stagiaires/<trainee_id>/attestation-elearning.pdf")
    @host.admin_login_required
    @host.admin_write_required
    def admin_desp_certificate_upload(session_id, trainee_id):
        path = certificate_path(host, *candidate(session_id, trainee_id))
        if request.content_length and request.content_length > projects.MAX_BYTES + 128 * 1024:
            return jsonify(error="Le PDF doit peser au maximum 15 Mo."), 413
        if not host.trainee_checks.valid_request():
            abort(403)
        upload = request.files.get("certificate")
        if not upload or Path(upload.filename or "").suffix.lower() != ".pdf":
            return jsonify(error="Sélectionnez une attestation au format PDF."), 400
        raw = upload.stream.read(projects.MAX_BYTES + 1)
        if len(raw) > projects.MAX_BYTES:
            return jsonify(error="Le PDF doit peser au maximum 15 Mo."), 413
        try:
            _validate_pdf(raw)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            staged = Path(temp.name)
        try:
            staged.write_bytes(raw)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
        return jsonify(ok=True)

    @app.get("/api/admin/sessions/<session_id>/desp-scotia")
    @host.admin_login_required
    def api_desp_scotia(session_id):
        training = training_or_404(session_id)
        candidates = []
        for trainee in sorted(host._registered_trainees(training),
                              key=lambda t: (str(t.get("last_name") or "").casefold(),
                                             str(t.get("first_name") or "").casefold())):
            groups, _ = inspect(host, training, trainee)
            ready = all(group["available"] for group in groups)
            candidates.append({
                "id": trainee["id"],
                "name": " ".join(filter(None, [host.normalize_first_name(trainee.get("first_name") or ""),
                                                host.normalize_last_name(trainee.get("last_name") or "")])),
                "documents": groups, "ready": ready,
                "download_url": url_for("admin_desp_scotia_download", session_id=session_id,
                                        trainee_id=trainee["id"]) if ready else None,
                "edit_url": url_for("admin_trainee_page", session_id=session_id, trainee_id=trainee["id"]),
            })
        response = jsonify(ok=True, candidates=candidates)
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/admin/sessions/<session_id>/stagiaires/<trainee_id>/dossier-scotia.pdf")
    @host.admin_login_required
    def admin_desp_scotia_download(session_id, trainee_id):
        training, trainee = candidate(session_id, trainee_id)
        groups, parts = inspect(host, training, trainee, include_content=True)
        missing = [group["label"] + " : " + group["error"] for group in groups if not group["available"]]
        if missing:
            return jsonify(ok=False, error="Dossier SCOTIA incomplet. " + " · ".join(missing)), 409
        try:
            with PdfWriter() as writer:
                for index, raw in enumerate(parts):
                    reader = PdfReader(BytesIO(raw))
                    # Isolate interactive field names between separate attachments.
                    reader.add_form_topname(f"piece{index + 1}")
                    writer.append(reader, import_outline=False)
                output = BytesIO()
                writer.write(output)
                output.seek(0)
        except Exception:
            app.logger.exception("Could not assemble DESP SCOTIA dossier")
            return jsonify(ok=False, error="Une pièce ne peut pas être intégrée. Remplacez-la par un PDF lisible."), 409
        filename = projects.base_name(host, trainee).replace("Projet de cadrage ", "Dossier SCOTIA ", 1)
        response = send_file(output, mimetype="application/pdf", as_attachment=True,
                             download_name=filename + ".pdf")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
