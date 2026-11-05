"""Complete, tenant-scoped DESP initial examination dossiers, assembled on demand."""
from io import BytesIO
from pathlib import Path

from flask import abort, jsonify, send_file, url_for
from pypdf import PdfReader, PdfWriter
from werkzeug.exceptions import HTTPException

import desp_jury_projects as projects
from document_conversion import convert_upload, _validate_pdf

GROUPS = (
    ("candidate_info_sheet", "Fiche de renseignement candidat"),
    ("desp_exam_sworn_statement", "Attestation sur l’honneur de prise en compte de l’examen DESP"),
    ("project", "Projet de cadrage"),
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


def inspect(host, training, trainee, *, include_content=False):
    groups, parts, total = [], [], 0
    for key, label in GROUPS:
        error, content = "", []
        try:
            if key == "project":
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
        training = training_or_404(session_id)
        trainee = next((t for t in host._registered_trainees(training) if str(t.get("id")) == trainee_id), None)
        if not trainee:
            abort(404)
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
