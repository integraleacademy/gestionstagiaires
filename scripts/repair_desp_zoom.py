"""One-off, source-only repair applied and tested on the dedicated branch."""
import ast
from pathlib import Path

path = Path('app.py')
source = path.read_text()
replacements = {}
replacements['admin_view_signed_desp_kickoff_attendance'] = '''def admin_view_signed_desp_kickoff_attendance(session_id: str):
    """Download the original Yousign PDF, including signatures already collected."""
    data = load_data()
    session_item = find_session(data, session_id)
    if not session_item or not _is_desp_initial_session(session_item):
        abort(404)
    state = _desp_kickoff_attendance_state(session_item)
    signed_path = _desp_kickoff_signed_pdf_path(state)
    request_id = str(state.get("signature_request_id") or "").strip()
    if not request_id and not (_is_yousign_signature_done(state) and signed_path):
        abort(404)
    try:
        if not (_is_yousign_signature_done(state) and signed_path):
            if not _yousign_is_configured():
                raise RuntimeError("La connexion Yousign est indisponible.")
            if _refresh_yousign_desp_kickoff_status_if_pending(session_item):
                save_data(data)
            state = _desp_kickoff_attendance_state(session_item)
            signed_path = _desp_kickoff_signed_pdf_path(state)
            if _is_yousign_signature_done(state) and not signed_path:
                _mark_yousign_desp_kickoff_signed(session_item, request_id)
                save_data(data)
                signed_path = _desp_kickoff_signed_pdf_path(state)
        if _is_yousign_signature_done(state) and signed_path:
            document = signed_path
            filename = os.path.basename(signed_path)
        else:
            # Never rebuild, annotate or merge a signed PDF: keep Yousign's bytes.
            response = _yousign_request(
                "GET",
                f"/signature_requests/{request_id}/documents/download",
                params={"version": "current", "archive": "false"},
                headers={"Accept": "application/pdf"},
            )
            content = _desp_kickoff_pdf_response_content(response)
            document = BytesIO(content)
            filename = f"feuille_presence_zoom_desp_{_safe_filename_part(session_id)}_en_cours.pdf"
        response = send_file(
            document,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
        response.headers["Cache-Control"] = "private, no-store"
        return response
    except Exception as exc:
        message = _sanitize_yousign_error(str(exc))
        app.logger.warning(
            "[DESP KICKOFF] document download failed session_id=%s error=%s",
            session_id, message,
        )
        flash(f"Impossible de télécharger la présence Zoom : {message}", "error")
        return redirect(url_for("admin_trainees", session_id=session_id))
'''
replacements['_desp_kickoff_attendance_view'] = '''def _desp_kickoff_signed_pdf_path(state: Dict[str, Any]) -> str:
    """Only trust a real PDF inside the dedicated signed-document directory."""
    raw = str(state.get("signed_pdf_path") or "").strip()
    if not raw:
        return ""
    path = os.path.realpath(raw)
    root = os.path.realpath(YOUSIGN_DESP_KICKOFF_SIGNED_DIR)
    if not path.startswith(root + os.sep):
        return ""
    try:
        if not os.path.isfile(path):
            return ""
        with open(path, "rb") as document:
            return path if b"%PDF-" in document.read(1024) else ""
    except OSError:
        return ""


def _desp_kickoff_pdf_response_content(response) -> bytes:
    content = response.content
    if not isinstance(content, bytes) or b"%PDF-" not in content[:1024]:
        raise RuntimeError("Yousign n’a pas renvoyé de document PDF valide. Réessayez dans quelques instants.")
    return content


def _desp_kickoff_attendance_view(session_obj: Dict[str, Any]) -> Dict[str, Any]:
    state = _desp_kickoff_attendance_state(session_obj)
    signers = state.get("signers") if isinstance(state.get("signers"), list) else []
    signed_count = sum(
        1 for signer in signers
        if isinstance(signer, dict)
        and _normalize_yousign_status(signer.get("status")) in YOUSIGN_FINAL_STATUSES
    )
    status = _normalize_yousign_status(state.get("status"))
    has_signed_pdf = bool(_desp_kickoff_signed_pdf_path(state))
    return {
        "status": status,
        "is_pending": status in YOUSIGN_PENDING_STATUSES,
        "is_done": status in YOUSIGN_FINAL_STATUSES,
        "signed_count": signed_count,
        "signer_count": len(signers),
        "last_error": str(state.get("last_error") or state.get("last_status_sync_error") or ""),
        "has_signed_pdf": has_signed_pdf,
        "can_download_pdf": bool(str(state.get("signature_request_id") or "").strip())
        or (status in YOUSIGN_FINAL_STATUSES and has_signed_pdf),
    }
'''
replacements['_download_yousign_desp_kickoff_signed_pdf'] = '''def _download_yousign_desp_kickoff_signed_pdf(signature_request_id: str, session_id: str) -> str:
    import tempfile

    response = _yousign_request(
        "GET",
        f"/signature_requests/{signature_request_id}/documents/download",
        params={"version": "completed", "archive": "false"},
        headers={"Accept": "application/pdf"},
    )
    content = _desp_kickoff_pdf_response_content(response)
    os.makedirs(YOUSIGN_DESP_KICKOFF_SIGNED_DIR, exist_ok=True)
    path = os.path.join(
        YOUSIGN_DESP_KICKOFF_SIGNED_DIR,
        f"feuille_presence_demarrage_desp_{_safe_filename_part(session_id)}_signee.pdf",
    )
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(dir=YOUSIGN_DESP_KICKOFF_SIGNED_DIR, suffix=".tmp", delete=False) as document:
            temporary_path = document.name
            document.write(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return path
'''
replacements['_refresh_yousign_desp_kickoff_status_if_pending'] = '''def _refresh_yousign_desp_kickoff_status_if_pending(session_obj: Dict[str, Any]) -> bool:
    state = _desp_kickoff_attendance_state(session_obj)
    request_id = str(state.get("signature_request_id") or "").strip()
    if not request_id or not _yousign_is_configured():
        return False
    if _is_yousign_signature_done(state) and _desp_kickoff_signed_pdf_path(state):
        return False
    try:
        signature_request = _yousign_json("GET", f"/signature_requests/{request_id}")
    except Exception as exc:
        state["last_status_sync_error"] = _sanitize_yousign_error(str(exc))
        app.logger.warning(
            "[DESP KICKOFF] Yousign status refresh failed request_id=%s error=%s",
            request_id, state["last_status_sync_error"],
        )
        return False
    status = _yousign_signature_request_status(signature_request)
    if not status:
        return False
    if status in YOUSIGN_FINAL_STATUSES:
        _mark_yousign_desp_kickoff_signed(session_obj, request_id)
        state.pop("last_status_sync_error", None)
        return True
    changed = bool(state.pop("last_status_sync_error", None))
    # Recover signer progress when a signer.done webhook was missed.
    remote_signers = signature_request.get("signers") if isinstance(signature_request, dict) else None
    local_signers = state.get("signers")
    if isinstance(remote_signers, list) and isinstance(local_signers, list):
        statuses = {
            str(signer.get("id") or ""): _normalize_yousign_status(signer.get("status"))
            for signer in remote_signers if isinstance(signer, dict)
        }
        for signer in local_signers:
            if not isinstance(signer, dict):
                continue
            remote_status = statuses.get(str(signer.get("signer_id") or ""))
            if remote_status and remote_status != _normalize_yousign_status(signer.get("status")):
                # Never downgrade a signature already confirmed by a webhook.
                if _normalize_yousign_status(signer.get("status")) not in YOUSIGN_FINAL_STATUSES:
                    signer["status"] = remote_status
                    changed = True
    if status != _normalize_yousign_status(state.get("status")):
        state["status"] = status
        state["last_error"] = ""
        changed = True
    if changed:
        state["updated_at"] = _now_iso()
    return changed
'''
parsed = ast.parse(source)
lines = source.splitlines(keepends=True)
found = set()
for node in sorted(parsed.body, key=lambda n: n.lineno, reverse=True):
    if isinstance(node, ast.FunctionDef) and node.name in replacements:
        lines[node.lineno-1:node.end_lineno] = [replacements[node.name].rstrip() + '\n']
        found.add(node.name)
assert found == set(replacements), (found, set(replacements))
source = ''.join(lines)
old = '''    if _is_yousign_signature_done(state) and state.get("signed_pdf_path"):
        return
    signed_path = _download_yousign_desp_kickoff_signed_pdf('''
new = '''    already_done = _is_yousign_signature_done(state)
    if already_done and _desp_kickoff_signed_pdf_path(state):
        return
    signed_path = _download_yousign_desp_kickoff_signed_pdf('''
assert source.count(old) == 1
source = source.replace(old, new, 1)
# Re-downloading a missing archive must not duplicate trainee history entries.
start = source.index('def _mark_yousign_desp_kickoff_signed(')
end = source.index('\ndef _refresh_yousign_desp_kickoff_status_if_pending(', start)
block = source[start:end]
needle = '    signers = state.get("signers") if isinstance(state.get("signers"), list) else []'
assert block.count(needle) == 1
block = block.replace(needle, '    if already_done:\n        return\n' + needle, 1)
source = source[:start] + block + source[end:]
ast.parse(source)
path.write_text(source)

template_path = Path('templates/admin_trainees.html')
template = template_path.read_text()
start = template.index('    {% if is_desp_initial %}\n')
end = template.index('    {% if is_ssiap_session', start)
template = template[:start] + '''    {% if is_desp_initial %}
    <a class="btn btn-outline" id="btnPreviewDespKickoffAttendance"
       href="{{ url_for('admin_desp_kickoff_attendance_preview', session_id=session.id) }}"
       target="_blank" rel="noopener"
       title="Modèle de la feuille de présence, sans les signatures des stagiaires">👁️ Aperçu vierge présence Zoom</a>
      {% if desp_kickoff_attendance.can_download_pdf %}
      <a class="btn btn-primary" id="btnSignedDespKickoffAttendance"
         href="{{ url_for('admin_view_signed_desp_kickoff_attendance', session_id=session.id) }}"
         title="Télécharger le PDF original Yousign avec les signatures déjà apposées, sans attendre les autres signataires">
        {% if desp_kickoff_attendance.is_done %}📥 Télécharger présence Zoom signée{% else %}📥 Télécharger avec les signatures reçues{% endif %}
      </a>
      {% endif %}
      {% if not desp_kickoff_attendance.is_done and not is_read_only %}
      <form method="post"
            action="{{ url_for('admin_send_desp_kickoff_attendance_yousign', session_id=session.id) }}"
            style="display:inline;"
            onsubmit="return confirm('Confirmer l’envoi de la feuille de présence DESP à tous les stagiaires via Yousign ?');">
        <button class="btn btn-primary" id="btnSendDespKickoffAttendance" type="submit">
          {% if desp_kickoff_attendance.is_pending %}📨 Renvoyer les liens Yousign{% else %}✍️ Envoyer la présence via Yousign{% endif %}
        </button>
      </form>
      {% endif %}
      {% if desp_kickoff_attendance.is_pending %}
      <span class="pill" title="Version en cours : le téléchargement contient uniquement les signatures déjà apposées.">Yousign : {{ desp_kickoff_attendance.signed_count }}/{{ desp_kickoff_attendance.signer_count }} signature(s)</span>
      {% endif %}
      {% if desp_kickoff_attendance.last_error %}
      <span class="pill" title="{{ desp_kickoff_attendance.last_error }}">Yousign : erreur de synchronisation</span>
      {% endif %}
    {% endif %}
''' + template[end:]
template_path.write_text(template)
print('Updated DESP download, partial-signature access, archive recovery and template.')
