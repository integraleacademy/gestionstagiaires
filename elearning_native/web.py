from __future__ import annotations

import base64
import csv
import datetime as dt
import hashlib
import hmac
import html
import json
import io
import os
import re
import secrets
import tempfile
import time
import threading
import unicodedata
from collections import OrderedDict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from markupsafe import Markup
from werkzeug.exceptions import Conflict

from .importer import (
    DEFAULT_MAX_ARCHIVE_BYTES,
    CourseCatalog,
    CourseImportError,
    sanitize_course_html,
)
from .store import NativeElearningStore, TrackingError
from .paths import (
    assigned_modules, course_outline, path_revision, project_course,
    project_progress, validate_modules,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development fallback
    fcntl = None


ACCESS_TOKEN_TTL_SECONDS = 12 * 60 * 60
CLIENT_IDLE_SECONDS = 120
CLIENT_HEARTBEAT_SECONDS = 15
UPLOAD_CHUNK_BYTES = 5 * 1024 * 1024
UPLOAD_TTL_SECONDS = 6 * 60 * 60
_ASSET_ATTRIBUTE_RE = re.compile(r'\b(src|data-src)="(media/[a-zA-Z0-9._/-]+)"')
_UPLOAD_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signing_key() -> bytes:
    if not current_app.secret_key:
        raise RuntimeError("SECRET_KEY doit être configurée pour le e-learning natif.")
    return str(current_app.secret_key).encode("utf-8")


def _sign_access(payload: Mapping[str, Any]) -> str:
    encoded = _b64encode(json.dumps(dict(payload), separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64encode(hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _verify_signed(raw_token: Any) -> Dict[str, Any]:
    token = str(raw_token or "").strip()
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _b64encode(
            hmac.new(_signing_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        abort(401, "Accès e-learning invalide.")
    if not isinstance(payload, dict) or int(payload.get("expires_at") or 0) < int(time.time()):
        abort(401, "L’accès e-learning a expiré. Rechargez la page.")
    return payload


def _verify_access(raw_token: Any) -> Dict[str, Any]:
    payload = _verify_signed(raw_token)
    nonce = str(payload.get("nonce") or "")
    if not nonce or not hmac.compare_digest(nonce, str(session.get("native_elearning_nonce") or "")):
        abort(401, "Session e-learning expirée.")
    public_token = str(payload.get("public_token") or "")
    if not session.get("admin_logged_in") and not session.get(f"public_auth_{public_token}"):
        abort(401, "Session stagiaire expirée.")
    for field in ("session_id", "trainee_id", "course_id", "course_version"):
        if not str(payload.get(field) or "").strip():
            abort(401, "Contexte e-learning incomplet.")
    return payload


def _asset_access_payload(access: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "course_asset",
        "course_id": str(access.get("course_id") or ""),
        "course_version": str(access.get("course_version") or ""),
        "nonce": str(access.get("nonce") or ""),
        "expires_at": int(access.get("expires_at") or 0),
    }


def _verify_asset_access(raw_token: Any) -> Dict[str, Any]:
    payload = _verify_signed(raw_token)
    nonce = str(payload.get("nonce") or "")
    if payload.get("kind") != "course_asset" or not nonce:
        abort(401, "Accès au média invalide.")
    if not hmac.compare_digest(nonce, str(session.get("native_elearning_nonce") or "")):
        abort(401, "Session e-learning expirée.")
    for field in ("course_id", "course_version"):
        if not str(payload.get(field) or "").strip():
            abort(401, "Contexte du média incomplet.")
    return payload


def _csrf_token() -> str:
    token = str(session.get("native_elearning_csrf") or "")
    if not token:
        token = secrets.token_urlsafe(32)
        session["native_elearning_csrf"] = token
    return token


def _require_csrf() -> None:
    supplied = str(request.headers.get("X-Elearning-CSRF") or "")
    expected = str(session.get("native_elearning_csrf") or "")
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        abort(403, "Jeton de sécurité invalide.")


def _require_form_csrf() -> None:
    supplied = str(request.form.get("native_elearning_csrf") or "")
    expected = str(session.get("native_elearning_csrf") or "")
    if not supplied or not expected or not hmac.compare_digest(supplied, expected):
        abort(403, "Jeton de sécurité invalide.")


def _activity_pairs(course: Mapping[str, Any]) -> List[Tuple[Mapping[str, Any], Mapping[str, Any]]]:
    pairs: List[Tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for section in course.get("sections") or []:
        if not isinstance(section, Mapping):
            continue
        for activity in section.get("activities") or []:
            if isinstance(activity, Mapping):
                pairs.append((section, activity))
    return pairs


def _scored_activity_ids(course: Mapping[str, Any]) -> List[str]:
    return [
        str(activity.get("id"))
        for _, activity in _activity_pairs(course)
        if activity.get("scored")
    ]


def _course_access_payload(
    session_obj: Mapping[str, Any],
    trainee: Mapping[str, Any],
    course: Mapping[str, Any],
    *,
    public_token: str,
) -> Dict[str, Any]:
    nonce = str(session.get("native_elearning_nonce") or "")
    if not nonce:
        nonce = secrets.token_urlsafe(24)
        session["native_elearning_nonce"] = nonce
    now = int(time.time())
    return {
        "session_id": str(session_obj.get("id") or ""),
        "trainee_id": str(trainee.get("id") or trainee.get("trainee_id") or ""),
        "course_id": str(course.get("id") or ""),
        "course_version": str(course.get("version") or ""),
        "public_token": public_token,
        "nonce": nonce,
        "issued_at": now,
        "expires_at": now + ACCESS_TOKEN_TTL_SECONDS,
        "path_revision": path_revision(session_obj),
        "section_ids": [str(section["id"]) for section in course.get("sections") or []],
        "module_title": str(course.get("title") or ""),
    }


def _next_incomplete(activity_order: Sequence[str], completed: Sequence[str]) -> str:
    completed_set = set(completed)
    return next((activity_id for activity_id in activity_order if activity_id not in completed_set), "")


def _format_seconds(value: Any) -> str:
    seconds = max(0, int(float(value or 0)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _normalize_fill_blank_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", normalized).strip()


def _safe_theme(course: Mapping[str, Any]) -> Dict[str, str]:
    raw = course.get("theme") if isinstance(course.get("theme"), Mapping) else {}

    def color(name: str, fallback: str) -> str:
        candidate = str(raw.get(name) or "").strip()
        return candidate.lower() if re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", candidate) else fallback

    return {
        "main_color": color("main_color", "#4f46e5"),
        "button_color": color("button_color", "#f97316"),
        "text_color": color("text_color", "#172033"),
    }


def _evaluate_answer(activity: Mapping[str, Any], payload: Mapping[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    question_type = str(activity.get("question_type") or "")
    if question_type in {"single_choice", "multiple_choice", "statement"}:
        raw_selected = payload.get("selected")
        selected = raw_selected if isinstance(raw_selected, list) else [raw_selected]
        selected_ids = sorted({str(value) for value in selected if str(value or "")})
        valid_ids = {str(option.get("id")) for option in activity.get("options") or []}
        if not selected_ids or any(value not in valid_ids for value in selected_ids):
            raise TrackingError("Réponse invalide.")
        if question_type == "single_choice" and len(selected_ids) != 1:
            raise TrackingError("Une seule réponse est attendue.")
        expected = sorted(
            str(option.get("id"))
            for option in activity.get("options") or []
            if option.get("is_correct")
        )
        return selected_ids == expected, {"selected": selected_ids}

    if question_type == "matching":
        selected = payload.get("selected")
        if not isinstance(selected, list):
            raise TrackingError("Associations invalides.")
        pairs = [pair for pair in activity.get("pairs") or [] if isinstance(pair, Mapping)]
        valid_ids = {str(pair.get("id")) for pair in pairs}
        selected_ids = [str(value or "") for value in selected]
        if len(selected_ids) != len(pairs) or any(value not in valid_ids for value in selected_ids):
            raise TrackingError("Toutes les associations sont obligatoires.")
        expected = [str(pair.get("id")) for pair in pairs]
        return selected_ids == expected, {"selected": selected_ids}

    if question_type == "fill_blank":
        groups = payload.get("groups")
        if not isinstance(groups, Mapping):
            raise TrackingError("Réponse à compléter invalide.")
        normalized = {
            str(key): _normalize_fill_blank_text(value)
            for key, value in groups.items()
        }
        answer_groups = [
            group
            for group in (activity.get("answer_groups") or [])
            if isinstance(group, Mapping)
        ]
        expected_group_ids = {str(group.get("id") or "") for group in answer_groups}
        if (
            set(normalized) != expected_group_ids
            or not expected_group_ids
            or any(not value for value in normalized.values())
        ):
            raise TrackingError("Toutes les réponses à compléter sont obligatoires.")

        is_correct = True
        for group in answer_groups:
            group_id = str(group.get("id") or "")
            answers = [answer for answer in group.get("answers") or [] if isinstance(answer, Mapping)]
            mode = str(group.get("mode") or "choice")
            submitted = normalized[group_id]
            if mode == "text":
                correct_answers = [answer for answer in answers if answer.get("is_correct")]
                group_is_correct = any(
                    (
                        submitted == _normalize_fill_blank_text(answer.get("text"))
                        if answer.get("match_case")
                        else submitted.casefold()
                        == _normalize_fill_blank_text(answer.get("text")).casefold()
                    )
                    for answer in correct_answers
                )
            elif mode == "choice":
                valid_ids = {str(answer.get("id") or "") for answer in answers}
                if submitted not in valid_ids:
                    raise TrackingError("Toutes les réponses à compléter sont obligatoires.")
                expected = next(
                    (str(answer.get("id") or "") for answer in answers if answer.get("is_correct")),
                    "",
                )
                group_is_correct = submitted == expected
            else:
                raise TrackingError("Format de réponse à compléter invalide.")
            is_correct = is_correct and group_is_correct
        return is_correct, {"groups": normalized}

    raise TrackingError("Ce type de question n’est pas encore pris en charge.")


def create_native_elearning_blueprint(
    *,
    get_persist_dir: Callable[[], str],
    load_data: Callable[[], Dict[str, Any]],
    save_data: Callable[[Dict[str, Any]], None],
    mutate_data: Callable[[Callable[[Dict[str, Any]], Dict[str, Any]]], Dict[str, Any]],
    find_session: Callable[[Dict[str, Any], str], Optional[Dict[str, Any]]],
    find_session_and_trainee_by_token: Callable[[Dict[str, Any], str], Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]],
    session_trainees: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
    public_is_authed: Callable[[str], bool],
    is_aps_elearning_session: Callable[[Dict[str, Any]], bool],
    session_start_date: Callable[[Dict[str, Any]], Optional[dt.date]],
) -> Blueprint:
    blueprint = Blueprint("native_elearning", __name__)
    # Cache only successful authorization timestamps, never administrative data
    # or course bodies. Heartbeats must not parse the large data.json every 15s.
    access_checks: OrderedDict[tuple, float] = OrderedDict()
    access_checks_lock = threading.Lock()

    def root() -> Path:
        return Path(get_persist_dir()).resolve() / "native_elearning"

    def catalog() -> CourseCatalog:
        return CourseCatalog(root())

    def store() -> NativeElearningStore:
        return NativeElearningStore(root() / "tracking.sqlite3")

    def max_archive_bytes() -> int:
        try:
            configured = int(
                os.environ.get(
                    "NATIVE_ELEARNING_MAX_ARCHIVE_BYTES",
                    str(DEFAULT_MAX_ARCHIVE_BYTES),
                )
            )
        except (TypeError, ValueError):
            configured = DEFAULT_MAX_ARCHIVE_BYTES
        return max(1024 * 1024, min(configured, DEFAULT_MAX_ARCHIVE_BYTES))

    def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not session.get("admin_logged_in"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Session administrateur expirée."}), 401
                return redirect(url_for("admin_login", next=request.full_path.rstrip("?")))
            return view(*args, **kwargs)

        return wrapped

    def admin_write_required(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if session.get("admin_role") == "viewer":
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    def learner_session(token: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        data = load_data()
        session_obj, trainee = find_session_and_trainee_by_token(data, token)
        if not session_obj or not trainee:
            abort(404)
        if not public_is_authed(token):
            abort(401)
        if not is_aps_elearning_session(session_obj):
            abort(403)
        if not session.get("admin_logged_in"):
            start_date = session_start_date(session_obj)
            if start_date is None:
                abort(403)
            if dt.date.today() < start_date:
                abort(403)
        return session_obj, trainee

    def learner_context(token: str, course_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        session_obj, trainee = learner_session(token)
        module = next((item for item in assigned_modules(session_obj) if item.get("course_id") == course_id), None)
        if module is None:
            abort(403)
        try:
            course = project_course(catalog().load_course(course_id, module.get("course_version") or None), module)
        except CourseImportError:
            abort(404)
        return session_obj, trainee, course

    def course_for_access(access: Mapping[str, Any]) -> Dict[str, Any]:
        cache_key = (str(root()), *(str(access.get(field) or "") for field in (
            "session_id", "trainee_id", "course_id", "course_version", "path_revision", "nonce", "issued_at",
        )), bool(session.get("admin_logged_in")))
        with access_checks_lock:
            recently_checked = time.monotonic() - access_checks.get(cache_key, float("-inf")) < 60
        if request.endpoint == "native_elearning.tracking_heartbeat" and recently_checked and access.get("section_ids"):
            try:
                return project_course(catalog().load_course(str(access["course_id"]), str(access["course_version"])),
                                      {"section_ids": access["section_ids"], "title": access.get("module_title")})
            except CourseImportError:
                abort(404)
        session_obj, trainee, course = learner_context(str(access.get("public_token") or ""), str(access.get("course_id") or ""))
        if (str(session_obj.get("id")) != str(access.get("session_id"))
                or str(trainee.get("id") or trainee.get("trainee_id")) != str(access.get("trainee_id"))
                or course["version"] != access.get("course_version")):
            abort(403)
        if access.get("path_revision") and access["path_revision"] != path_revision(session_obj):
            abort(409, "Le parcours a été modifié. Rechargez la page.")
        with access_checks_lock:
            access_checks[cache_key] = time.monotonic()
            access_checks.move_to_end(cache_key)
            while len(access_checks) > 512:
                access_checks.popitem(last=False)
        return course

    def current_progress(access: Mapping[str, Any], course: Mapping[str, Any]) -> Dict[str, Any]:
        raw = store().get_progress(access, activity_order=course.get("activity_order") or [],
                                   scored_activity_ids=_scored_activity_ids(course))
        return project_progress(raw, course)

    def load_path(session_obj: Mapping[str, Any], cache: Optional[Dict[Any, Any]] = None) -> List[Dict[str, Any]]:
        cache = cache if cache is not None else {}
        modules = []
        for item in assigned_modules(session_obj):
            key = (str(item.get("course_id") or ""), str(item.get("course_version") or ""))
            try:
                if key not in cache:
                    cache[key] = catalog().load_course(key[0], key[1] or None)
                source = cache[key]
                course = project_course(source, item)
                modules.append({"assignment": item, "course": course, "outline": course_outline(source), "error": ""})
            except CourseImportError as exc:
                modules.append({"assignment": item, "error": str(exc), "course": None, "outline": None})
        return modules

    def asset_url(asset_token: str, course_id: str, asset_name: str) -> str:
        return url_for(
            "native_elearning.course_asset",
            course_id=course_id,
            asset_name=asset_name,
            access=asset_token,
        )

    def prepare_html(value: str, asset_token: str, course_id: str) -> Markup:
        def replace(match: re.Match[str]) -> str:
            attribute, name = match.groups()
            safe_url = html.escape(asset_url(asset_token, course_id, name), quote=True)
            return f'{attribute}="{safe_url}"'

        # Imported HTML is sanitized when persisted and again here so a damaged
        # or manually altered course.json can never bypass the boundary.
        sanitized = sanitize_course_html(str(value or ""))
        return Markup(_ASSET_ATTRIBUTE_RE.sub(replace, sanitized))  # noqa: S704

    def prepare_block(block: Mapping[str, Any], asset_token: str, course_id: str) -> Dict[str, Any]:
        public_block = {
            "id": str(block.get("id") or ""),
            "type": str(block.get("type") or "html"),
            "html": prepare_html(str(block.get("html") or ""), asset_token, course_id),
            "children": [
                prepare_block(child, asset_token, course_id)
                for child in (block.get("children") or [])
                if isinstance(child, Mapping)
            ],
        }
        video = block.get("video")
        if isinstance(video, Mapping):
            src = str(video.get("src") or "")
            poster = str(video.get("poster") or "")
            public_block["video"] = {
                "src": asset_url(asset_token, course_id, src) if src else "",
                "poster": asset_url(asset_token, course_id, poster) if poster else "",
            }
        return public_block

    def prepare_activity(
        activity: Mapping[str, Any],
        asset_token: str,
        course_id: str,
    ) -> Dict[str, Any]:
        public: Dict[str, Any] = {
            "id": str(activity.get("id") or ""),
            "title": str(activity.get("title") or ""),
            "type": str(activity.get("type") or "content"),
            "question_type": str(activity.get("question_type") or ""),
            "scored": bool(activity.get("scored")),
        }
        if public["type"] == "content":
            public["blocks"] = [
                prepare_block(block, asset_token, course_id)
                for block in (activity.get("blocks") or [])
                if isinstance(block, Mapping)
            ]
            return public

        question_type = public["question_type"]
        if question_type in {"single_choice", "multiple_choice", "statement"}:
            public["options"] = [
                {"id": str(option.get("id") or ""), "text": str(option.get("text") or "")}
                for option in (activity.get("options") or [])
                if isinstance(option, Mapping)
            ]
        elif question_type == "matching":
            pairs = [pair for pair in activity.get("pairs") or [] if isinstance(pair, Mapping)]
            public["matching_lefts"] = [str(pair.get("left") or "") for pair in pairs]
            choices = [
                {"id": str(pair.get("id") or ""), "text": str(pair.get("right") or "")}
                for pair in pairs
            ]
            secrets.SystemRandom().shuffle(choices)
            public["matching_choices"] = choices
        elif question_type == "fill_blank":
            public["prompt_html"] = prepare_html(
                str(activity.get("prompt_html") or ""), asset_token, course_id
            )
        return public

    def navigation_for(
        course: Mapping[str, Any],
        progress: Mapping[str, Any],
        *,
        token: str,
        current_activity_id: str,
    ) -> List[Dict[str, Any]]:
        completed = set(progress.get("completed_activity_ids") or [])
        order = [str(value) for value in course.get("activity_order") or []]
        first_incomplete = _next_incomplete(order, list(completed))
        first_incomplete_index = order.index(first_incomplete) if first_incomplete in order else len(order)
        force_navigation = bool(course.get("settings", {}).get("force_navigation"))
        result: List[Dict[str, Any]] = []
        sequence = 0
        for section in course.get("sections") or []:
            if not isinstance(section, Mapping):
                continue
            items: List[Dict[str, Any]] = []
            for activity in section.get("activities") or []:
                if not isinstance(activity, Mapping):
                    continue
                activity_id = str(activity.get("id") or "")
                locked = force_navigation and sequence > first_incomplete_index and activity_id not in completed
                items.append(
                    {
                        "id": activity_id,
                        "title": str(activity.get("title") or ""),
                        "completed": activity_id in completed,
                        "current": activity_id == current_activity_id,
                        "locked": locked,
                        "url": url_for(
                            "native_elearning.course_player",
                            token=token,
                            course_id=course.get("id"),
                            activity=activity_id,
                        ),
                    }
                )
                sequence += 1
            result.append({"title": str(section.get("title") or ""), "activities": items})
        return result

    def _is_aps_training(session_obj: Mapping[str, Any]) -> bool:
        return str(session_obj.get("training_type") or "").strip().upper().startswith("APS")

    def _admin_upload_nonce() -> str:
        nonce = str(session.get("native_elearning_admin_upload_nonce") or "")
        if not nonce:
            nonce = secrets.token_urlsafe(24)
            session["native_elearning_admin_upload_nonce"] = nonce
        return nonce

    def _upload_paths(upload_id: str) -> Tuple[Path, Path]:
        if not _UPLOAD_ID_RE.fullmatch(str(upload_id or "")):
            abort(404)
        imports_root = root() / "imports"
        imports_root.mkdir(parents=True, exist_ok=True)
        return imports_root / f"{upload_id}.part", imports_root / f"{upload_id}.json"

    def _write_upload_metadata(path: Path, metadata: Mapping[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(dict(metadata), target, ensure_ascii=False, separators=(",", ":"))
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

    def _read_upload_metadata(upload_id: str) -> Tuple[Path, Path, Dict[str, Any]]:
        part_path, metadata_path = _upload_paths(upload_id)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            abort(404)
        if not isinstance(metadata, dict):
            abort(404)
        expected_nonce = str(metadata.get("owner_nonce") or "")
        if not expected_nonce or not hmac.compare_digest(expected_nonce, _admin_upload_nonce()):
            abort(403)
        if int(metadata.get("expires_at") or 0) < int(time.time()):
            for path in (part_path, metadata_path):
                try:
                    path.unlink()
                except OSError:
                    pass
            abort(410, "Import expiré. Recommencez l’envoi.")
        return part_path, metadata_path, metadata

    def _cleanup_expired_uploads() -> None:
        imports_root = root() / "imports"
        if not imports_root.is_dir():
            return
        now = int(time.time())
        for metadata_path in imports_root.glob("*.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                expired = int(metadata.get("expires_at") or 0) < now
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                expired = True
            if expired:
                part_path = metadata_path.with_suffix(".part")
                for path in (part_path, metadata_path):
                    try:
                        path.unlink()
                    except OSError:
                        pass
        for part_path in imports_root.glob("*.part"):
            if part_path.with_suffix(".json").exists():
                continue
            try:
                is_stale = time.time() - part_path.stat().st_mtime > UPLOAD_TTL_SECONDS
            except OSError:
                continue
            if is_stale:
                try:
                    part_path.unlink()
                except OSError:
                    pass

    @blueprint.get("/admin/elearning")
    @admin_required
    def admin_catalog() -> Any:
        _cleanup_expired_uploads()
        data = load_data()
        aps_sessions_by_id: Dict[str, Dict[str, Any]] = {}
        for session_obj in data.get("sessions", []) or []:
            if not isinstance(session_obj, dict) or not _is_aps_training(session_obj):
                continue
            session_id = str(session_obj.get("id") or "").strip()
            if session_id:
                aps_sessions_by_id.setdefault(session_id, session_obj)
        aps_sessions = list(aps_sessions_by_id.values())
        courses = catalog().list_courses()
        cache = {(course["id"], course["version"]): course for course in courses}
        path_summaries = {}
        for session_obj in aps_sessions:
            modules = load_path(session_obj, cache)
            path_summaries[session_obj["id"]] = {
                "modules": len(modules),
                "sections": sum(item["course"]["counts"]["sections"] for item in modules if item["course"]),
                "activities": sum(item["course"]["counts"]["activities"] for item in modules if item["course"]),
                "unavailable": any(item["error"] for item in modules),
            }
        return render_template(
            "admin_native_elearning.html",
            courses=courses,
            aps_sessions=aps_sessions,
            path_summaries=path_summaries,
            upload_limit_mb=max_archive_bytes() // (1024 * 1024),
            upload_limit_bytes=max_archive_bytes(),
            upload_chunk_mb=UPLOAD_CHUNK_BYTES // (1024 * 1024),
            csrf_token=_csrf_token(),
        )

    @blueprint.get("/admin/sessions/<session_id>/elearning")
    @admin_required
    def admin_path(session_id: str) -> Any:
        session_obj = find_session(load_data(), session_id)
        if not session_obj or not _is_aps_training(session_obj):
            abort(404)
        modules = load_path(session_obj)
        outlines = {(course["id"], course["version"]): course_outline(course) for course in catalog().list_courses()}
        for item in modules:
            if item["outline"]:
                outline = item["outline"]
                outlines[(outline["course_id"], outline["course_version"])] = outline
        return render_template(
            "admin_native_elearning_path.html", training_session=session_obj,
            path_config={
                "catalog": list(outlines.values()), "modules": assigned_modules(session_obj),
                "revision": path_revision(session_obj), "csrfToken": _csrf_token(),
                "saveUrl": url_for("native_elearning.admin_save_path", session_id=session_id),
                "readOnly": session.get("admin_role") == "viewer",
            },
        )

    @blueprint.post("/api/admin/sessions/<session_id>/elearning/path")
    @admin_required
    @admin_write_required
    def admin_save_path(session_id: str) -> Any:
        _require_csrf()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "Parcours invalide."}), 400
        data = load_data()
        session_obj = find_session(data, session_id)
        if not session_obj or not _is_aps_training(session_obj):
            abort(404)
        if payload.get("revision") != path_revision(session_obj):
            return jsonify({"ok": False, "error": "Ce parcours a été modifié dans une autre fenêtre. Rechargez la page avant de l’enregistrer."}), 409
        title = payload.get("title", "")
        if not isinstance(title, str) or len(title) > 180:
            return jsonify({"ok": False, "error": "Le titre du parcours est limité à 180 caractères."}), 400
        try:
            modules = validate_modules(payload.get("modules"), catalog())
        except CourseImportError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        def persist_path(canonical: Dict[str, Any]) -> Dict[str, Any]:
            target = find_session(canonical, session_id)
            if not target or not _is_aps_training(target):
                abort(404)
            # Recheck under the application's canonical storage lock, not just
            # against the earlier request snapshot. Only this session changes.
            if payload.get("revision") != path_revision(target):
                raise Conflict("Ce parcours a été modifié. Rechargez la page avant de l’enregistrer.")
            target["aps_native_modules"] = modules
            target["aps_native_path_title"] = title.strip()
            if modules:
                target["aps_native_course_id"] = modules[0]["course_id"]
                target["aps_native_course_version"] = modules[0]["course_version"]
            else:
                target.pop("aps_native_course_id", None)
                target.pop("aps_native_course_version", None)
            return {"ok": True, "revision": path_revision(target), "modules": modules}

        try:
            result = mutate_data(persist_path)
        except Conflict as exc:
            return jsonify({"ok": False, "error": exc.description}), 409
        with access_checks_lock:
            access_checks.clear()
        return jsonify(result)

    @blueprint.post("/api/admin/elearning/imports")
    @admin_required
    @admin_write_required
    def admin_create_chunked_import() -> Any:
        _require_csrf()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, Mapping):
            return jsonify({"ok": False, "error": "Demande d’import invalide."}), 400
        raw_filename = str(payload.get("filename") or "").replace("\x00", "").replace("\\", "/")
        filename = Path(raw_filename).name
        try:
            expected_size = int(payload.get("size") or 0)
        except (TypeError, ValueError):
            expected_size = 0
        if not filename.lower().endswith(".zip"):
            return jsonify({"ok": False, "error": "Sélectionnez un fichier ZIP."}), 400
        if expected_size <= 0 or expected_size > max_archive_bytes():
            return jsonify({"ok": False, "error": "La taille du ZIP n’est pas autorisée."}), 400

        upload_id = secrets.token_hex(16)
        part_path, metadata_path = _upload_paths(upload_id)
        try:
            with part_path.open("xb"):
                pass
            _write_upload_metadata(
                metadata_path,
                {
                    "upload_id": upload_id,
                    "filename": filename[:255],
                    "expected_size": expected_size,
                    "owner_nonce": _admin_upload_nonce(),
                    "created_at": int(time.time()),
                    "expires_at": int(time.time()) + UPLOAD_TTL_SECONDS,
                },
            )
        except OSError:
            return jsonify({"ok": False, "error": "Impossible de préparer l’import."}), 500
        return jsonify(
            {
                "ok": True,
                "upload_id": upload_id,
                "chunk_size": UPLOAD_CHUNK_BYTES,
                "chunk_url": url_for("native_elearning.admin_upload_chunk", upload_id=upload_id),
                "complete_url": url_for("native_elearning.admin_complete_chunked_import", upload_id=upload_id),
            }
        ), 201

    @blueprint.post("/api/admin/elearning/imports/<upload_id>/chunks")
    @admin_required
    @admin_write_required
    def admin_upload_chunk(upload_id: str) -> Any:
        _require_csrf()
        part_path, _metadata_path, metadata = _read_upload_metadata(upload_id)
        try:
            offset = int(request.headers.get("X-Upload-Offset") or -1)
        except (TypeError, ValueError):
            offset = -1
        payload = request.stream.read(UPLOAD_CHUNK_BYTES + 1)
        if offset < 0 or not payload or len(payload) > UPLOAD_CHUNK_BYTES:
            return jsonify({"ok": False, "error": "Fragment d’import invalide."}), 400
        expected_size = int(metadata.get("expected_size") or 0)

        with part_path.open("r+b") as target:
            if fcntl is not None:
                fcntl.flock(target.fileno(), fcntl.LOCK_EX)
            target.seek(0, os.SEEK_END)
            received = target.tell()
            if received != offset:
                return jsonify(
                    {"ok": False, "error": "Décalage d’import invalide.", "received": received}
                ), 409
            if received + len(payload) > expected_size:
                return jsonify({"ok": False, "error": "Le ZIP dépasse la taille annoncée."}), 400
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
            received += len(payload)

        return jsonify({"ok": True, "received": received, "total": expected_size})

    @blueprint.post("/api/admin/elearning/imports/<upload_id>/complete")
    @admin_required
    @admin_write_required
    def admin_complete_chunked_import(upload_id: str) -> Any:
        _require_csrf()
        part_path, metadata_path, metadata = _read_upload_metadata(upload_id)
        expected_size = int(metadata.get("expected_size") or 0)
        try:
            received_size = part_path.stat().st_size
        except OSError:
            received_size = -1
        if received_size != expected_size:
            return jsonify(
                {
                    "ok": False,
                    "error": "Le fichier n’est pas encore entièrement reçu.",
                    "received": max(0, received_size),
                    "total": expected_size,
                }
            ), 409
        try:
            imported = catalog().import_zip(part_path, archive_source=True)
        except CourseImportError as exc:
            return jsonify({"ok": False, "error": f"Import impossible : {exc}"}), 400
        finally:
            for path in (part_path, metadata_path):
                try:
                    path.unlink()
                except OSError:
                    pass
        return jsonify(
            {
                "ok": True,
                "course": {
                    "id": imported.get("id"),
                    "version": imported.get("version"),
                    "title": imported.get("title"),
                    "counts": imported.get("counts", {}),
                    "warnings": imported.get("import_warnings", []),
                },
            }
        )

    @blueprint.post("/admin/elearning/import")
    @admin_required
    @admin_write_required
    def admin_import_course() -> Any:
        _require_form_csrf()
        uploaded = request.files.get("course_zip")
        if uploaded is None or not str(uploaded.filename or "").lower().endswith(".zip"):
            flash("Sélectionnez un export Easygenerator manuel au format ZIP.", "error")
            return redirect(url_for("native_elearning.admin_catalog"))
        max_bytes = max_archive_bytes()
        imports_root = root() / "imports"
        imports_root.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix="easygenerator-", suffix=".zip", dir=str(imports_root))
        total = 0
        try:
            with os.fdopen(fd, "wb") as target:
                while True:
                    chunk = uploaded.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise CourseImportError("Le ZIP dépasse la taille maximale autorisée.")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            imported = catalog().import_zip(temporary_name, archive_source=True)
        except CourseImportError as exc:
            flash(f"Import impossible : {exc}", "error")
        else:
            counts = imported.get("counts", {})
            flash(
                f"Cours importé : {imported.get('title')} · {counts.get('sections', 0)} séquences · "
                f"{counts.get('activities', 0)} activités.",
                "success",
            )
        finally:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        return redirect(url_for("native_elearning.admin_catalog"))

    @blueprint.post("/admin/sessions/<session_id>/elearning/assign")
    @admin_required
    @admin_write_required
    def admin_assign_course(session_id: str) -> Any:
        _require_form_csrf()
        data = load_data()
        session_obj = find_session(data, session_id)
        if not session_obj or not _is_aps_training(session_obj):
            abort(404)
        if "aps_native_modules" in session_obj:
            abort(409, "Utilisez le compositeur de parcours pour modifier cette session.")
        course_id = str(request.form.get("course_id") or "").strip()
        if not course_id:
            session_obj.pop("aps_native_course_id", None)
            session_obj.pop("aps_native_course_version", None)
            flash("Cours natif retiré de la session.", "success")
        else:
            try:
                course = catalog().load_course(course_id)
            except CourseImportError:
                abort(404)
            session_obj["aps_native_course_id"] = course["id"]
            session_obj["aps_native_course_version"] = course["version"]
            flash(f"Cours « {course.get('title')} » affecté à la session.", "success")
        save_data(data)
        return redirect(url_for("native_elearning.admin_catalog"))

    def live_payload(course_id: str) -> Dict[str, Any]:
        try:
            course = catalog().load_course(course_id)
        except CourseImportError:
            abort(404)
        rows = store().live_progress(course_id)
        identities: Dict[Tuple[str, str], Dict[str, str]] = {}
        session_paths: Dict[str, Dict[str, Any]] = {}
        data = load_data()
        for session_obj in data.get("sessions", []) or []:
            if not isinstance(session_obj, dict):
                continue
            module = next((item for item in assigned_modules(session_obj) if item.get("course_id") == course_id), None)
            if module:
                session_paths[str(session_obj.get("id"))] = module
            for trainee in session_trainees(session_obj):
                trainee_id = str(trainee.get("id") or trainee.get("trainee_id") or "")
                identities[(str(session_obj.get("id") or ""), trainee_id)] = {
                    "trainee_name": f"{trainee.get('first_name', '')} {trainee.get('last_name', '')}".strip(),
                    "session_name": str(session_obj.get("name") or session_obj.get("id") or ""),
                }
        versions: Dict[str, Dict[str, Any]] = {str(course.get("version") or ""): course}
        for row in rows:
            row_version = str(row.get("course_version") or "")
            if row_version not in versions:
                try:
                    versions[row_version] = catalog().load_course(course_id, row_version)
                except CourseImportError:
                    versions[row_version] = course
            row_course = versions[row_version]
            module = session_paths.get(row["session_id"])
            if module and (not module.get("course_version") or module["course_version"] == row_version):
                try:
                    row_course = project_course(row_course, module)
                except CourseImportError:
                    pass
            row.update(project_progress(row, row_course))
            activity_titles = {
                str(activity.get("id")): str(activity.get("title") or "")
                for _, activity in _activity_pairs(row_course)
            }
            total = len(row_course.get("activity_order") or [])
            row.update(identities.get((row["session_id"], row["trainee_id"]), {}))
            row["trainee_name"] = row.get("trainee_name") or row["trainee_id"]
            row["session_name"] = row.get("session_name") or row["session_id"]
            row["activity_title"] = activity_titles.get(row.get("current_activity_id"), "")
            completed_count = len(set(row.get("completed_activity_ids") or []) & set(row_course.get("activity_order") or []))
            row["progress_percent"] = round((completed_count / total) * 100, 1) if total else 0
            row["active_time_label"] = _format_seconds(row.get("active_seconds"))
            row.pop("answers", None)
        return {
            "ok": True,
            "course": {"id": course["id"], "version": course["version"], "title": course["title"]},
            "summary": {"learners": len(rows), "live": sum(1 for row in rows if row.get("live"))},
            "learners": rows,
            "server_time": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    @blueprint.get("/admin/elearning/courses/<course_id>/live")
    @admin_required
    def admin_live(course_id: str) -> Any:
        payload = live_payload(course_id)
        return render_template(
            "admin_native_elearning_live.html",
            initial=payload,
            live_url=url_for("native_elearning.admin_live_api", course_id=course_id),
        )

    @blueprint.get("/api/admin/elearning/courses/<course_id>/live")
    @admin_required
    def admin_live_api(course_id: str) -> Any:
        return jsonify(live_payload(course_id))

    @blueprint.get("/admin/elearning/courses/<course_id>/export.csv")
    @admin_required
    def admin_course_export(course_id: str) -> Any:
        payload = live_payload(course_id)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(
            [
                "Stagiaire",
                "Session",
                "Version du cours",
                "Statut",
                "Progression (%)",
                "Score (%)",
                "Temps actif (secondes)",
                "Temps actif",
                "Activité actuelle",
                "Début du parcours",
                "Dernière activité",
                "Fin du parcours",
            ]
        )
        for row in payload["learners"]:
            writer.writerow(
                [
                    row.get("trainee_name") or "",
                    row.get("session_name") or "",
                    row.get("course_version") or "",
                    row.get("status") or "",
                    row.get("progress_percent") or 0,
                    row.get("score_percent") or 0,
                    round(float(row.get("active_seconds") or 0), 2),
                    row.get("active_time_label") or "00:00:00",
                    row.get("activity_title") or "",
                    row.get("started_at") or "",
                    row.get("updated_at") or "",
                    row.get("completed_at") or "",
                ]
            )
        response = Response("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = f'attachment; filename="suivi-{course_id}.csv"'
        return response

    @blueprint.get("/espace/<token>/elearning")
    def learner_path(token: str) -> Any:
        if not public_is_authed(token):
            return redirect(url_for("public_trainee_login", token=token))
        session_obj, trainee = learner_session(token)
        raw_progress = store().learner_progress(str(session_obj["id"]), str(trainee.get("id") or trainee.get("trainee_id")))
        progress_by_key = {(item["course_id"], item["course_version"]): item for item in raw_progress}
        modules = load_path(session_obj)
        total = completed = seconds = finished = 0
        resume_url = ""
        for item in modules:
            course = item["course"]
            if not course:
                continue
            progress = project_progress(progress_by_key.get((course["id"], course["version"]), {}), course)
            item["progress"] = progress
            item["url"] = url_for("native_elearning.course_player", token=token, course_id=course["id"])
            item["time_label"] = _format_seconds(progress["active_seconds"])
            item["complete"] = progress["status"] in {"passed", "failed"}
            total += len(course["activity_order"])
            completed += len(progress["completed_activity_ids"])
            seconds += progress["active_seconds"]
            finished += int(item["complete"])
            if not resume_url and not item["complete"]:
                resume_url = item["url"]
        return render_template(
            "native_elearning_path.html", modules=modules,
            path_title=session_obj.get("aps_native_path_title") or "Mon parcours APS",
            session_name=session_obj.get("name") or "Formation APS",
            learner_name=f"{trainee.get('first_name', '')} {trainee.get('last_name', '')}".strip(),
            total_activities=total, completed_activities=completed, completed_modules=finished,
            progress_percent=round(completed / total * 100) if total else 0,
            active_time_label=_format_seconds(seconds), resume_url=resume_url,
            portal_url=url_for("public_trainee_space", token=token),
        )

    @blueprint.get("/espace/<token>/elearning/<course_id>")
    def course_player(token: str, course_id: str) -> Any:
        if not public_is_authed(token):
            return redirect(url_for("public_trainee_login", token=token))
        session_obj, trainee, course = learner_context(token, course_id)
        access = _course_access_payload(session_obj, trainee, course, public_token=token)
        access_token = _sign_access(access)
        asset_token = _sign_access(_asset_access_payload(access))
        csrf = _csrf_token()
        order = [str(value) for value in course.get("activity_order") or []]
        scored_ids = _scored_activity_ids(course)
        progress = current_progress(access, course)
        if not order:
            abort(404)
        requested_id = str(request.args.get("activity") or progress.get("current_activity_id") or "")
        if requested_id not in order:
            requested_id = _next_incomplete(order, progress.get("completed_activity_ids") or []) or order[0]
        completed = set(progress.get("completed_activity_ids") or [])
        first_incomplete = _next_incomplete(order, list(completed))
        if course.get("settings", {}).get("force_navigation") and first_incomplete in order:
            if order.index(requested_id) > order.index(first_incomplete) and requested_id not in completed:
                requested_id = first_incomplete

        pairs = _activity_pairs(course)
        index = order.index(requested_id)
        raw_activity = next(activity for _, activity in pairs if str(activity.get("id")) == requested_id)
        section = next(section for section, activity in pairs if str(activity.get("id")) == requested_id)
        activity = prepare_activity(raw_activity, asset_token, course_id)
        introduction = [
            prepare_block(block, asset_token, course_id)
            for block in (course.get("introduction") or [])
            if isinstance(block, Mapping)
        ] if index == 0 else []
        previous_url = (
            url_for("native_elearning.course_player", token=token, course_id=course_id, activity=order[index - 1])
            if index > 0
            else ""
        )
        next_url = (
            url_for("native_elearning.course_player", token=token, course_id=course_id, activity=order[index + 1])
            if index + 1 < len(order)
            else url_for("native_elearning.course_player", token=token, course_id=course_id, activity=requested_id)
        )
        modules = assigned_modules(session_obj)
        module_index = next(index for index, item in enumerate(modules) if item.get("course_id") == course_id)
        path_url = url_for("native_elearning.learner_path", token=token)
        next_module = modules[module_index + 1] if module_index + 1 < len(modules) else None
        end_url = url_for("native_elearning.course_player", token=token, course_id=next_module["course_id"]) if next_module else path_url
        return render_template(
            "native_elearning_player.html",
            course={"id": course["id"], "title": course["title"], "theme": _safe_theme(course)},
            learner_name=f"{trainee.get('first_name', '')} {trainee.get('last_name', '')}".strip(),
            section_title=str(section.get("title") or ""),
            activity=activity,
            introduction=introduction,
            progress=progress,
            navigation=navigation_for(course, progress, token=token, current_activity_id=requested_id),
            activity_position=index + 1,
            activity_count=len(order),
            activity_completed=requested_id in completed,
            previous_url=previous_url,
            next_url=next_url,
            portal_url=url_for("public_trainee_space", token=token),
            path_url=path_url, end_url=end_url,
            end_label="Module suivant" if next_module else "Retour au parcours",
            module_position=module_index + 1, module_count=len(modules),
            csrf_token=csrf,
            access_token=access_token,
            heartbeat_seconds=CLIENT_HEARTBEAT_SECONDS,
            idle_seconds=CLIENT_IDLE_SECONDS,
            is_last_activity=index + 1 == len(order),
        )

    @blueprint.get("/elearning/assets/<course_id>/<path:asset_name>")
    def course_asset(course_id: str, asset_name: str) -> Any:
        access = _verify_asset_access(request.args.get("access"))
        if not hmac.compare_digest(str(access.get("course_id")), str(course_id)):
            abort(403)
        try:
            path = catalog().asset_path(course_id, str(access.get("course_version")), asset_name)
        except CourseImportError:
            abort(404)
        response = send_file(path, conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response

    def api_context() -> Tuple[Dict[str, Any], Dict[str, Any], List[str], List[str]]:
        _require_csrf()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            abort(400)
        access = _verify_access(payload.get("access_token"))
        course = course_for_access(access)
        order = [str(value) for value in course.get("activity_order") or []]
        return access, course, order, _scored_activity_ids(course)

    @blueprint.post("/api/elearning/v1/tracking/start")
    def tracking_start() -> Any:
        access, _course, order, scored_ids = api_context()
        payload = request.get_json(silent=True) or {}
        activity_id = str(payload.get("activity_id") or "")
        if activity_id not in order:
            return jsonify({"ok": False, "error": "Activité inconnue."}), 400
        try:
            started = store().start_tracking(
                access,
                tab_id=str(payload.get("tab_id") or ""),
                activity_id=activity_id,
            )
            progress = current_progress(access, _course)
        except TrackingError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, **started, "progress": progress})

    @blueprint.post("/api/elearning/v1/tracking/heartbeat")
    def tracking_heartbeat() -> Any:
        access, _course, order, scored_ids = api_context()
        payload = request.get_json(silent=True) or {}
        activity_id = str(payload.get("activity_id") or "")
        if activity_id not in order:
            return jsonify({"ok": False, "error": "Activité inconnue."}), 400
        try:
            result = store().heartbeat(
                access,
                str(payload.get("tracking_session_id") or ""),
                activity_id=activity_id,
                visible=payload.get("visible") is True,
                focused=payload.get("focused") is True,
                recent_activity=payload.get("recent_activity") is True,
                media_playing=payload.get("media_playing") is True,
            )
            result["progress"] = current_progress(access, _course)
        except TrackingError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, **result})

    @blueprint.post("/api/elearning/v1/tracking/finish")
    def tracking_finish() -> Any:
        access, _course, order, scored_ids = api_context()
        payload = request.get_json(silent=True) or {}
        try:
            result = store().finish_tracking(
                access,
                str(payload.get("tracking_session_id") or ""),
                activity_id=str(payload.get("activity_id") or ""),
            )
            result["progress"] = current_progress(access, _course)
        except TrackingError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, **result})

    def can_complete(course: Mapping[str, Any], progress: Mapping[str, Any], activity_id: str) -> bool:
        order = [str(value) for value in course.get("activity_order") or []]
        if activity_id not in order:
            return False
        if not course.get("settings", {}).get("force_navigation"):
            return True
        completed = set(progress.get("completed_activity_ids") or [])
        return all(previous in completed for previous in order[: order.index(activity_id)])

    @blueprint.post("/api/elearning/v1/activities/<activity_id>/complete")
    def activity_complete(activity_id: str) -> Any:
        access, course, order, scored_ids = api_context()
        activity = next((item for _, item in _activity_pairs(course) if item.get("id") == activity_id), None)
        if activity is None or activity.get("scored"):
            return jsonify({"ok": False, "error": "Activité invalide."}), 400
        current = current_progress(access, course)
        if not can_complete(course, current, activity_id):
            return jsonify({"ok": False, "error": "Terminez d’abord l’activité précédente."}), 409
        result = store().complete_activity(
            access,
            activity_id,
            activity_order=order,
            scored_activity_ids=scored_ids,
            mastery_score=float(course.get("settings", {}).get("mastery_score") or 80),
        )
        return jsonify({"ok": True, "progress": project_progress(result, course), "next_activity_id": result.get("current_activity_id")})

    @blueprint.post("/api/elearning/v1/activities/<activity_id>/answer")
    def activity_answer(activity_id: str) -> Any:
        access, course, order, scored_ids = api_context()
        activity = next((item for _, item in _activity_pairs(course) if item.get("id") == activity_id), None)
        if activity is None or not activity.get("scored"):
            return jsonify({"ok": False, "error": "Question invalide."}), 400
        current = current_progress(access, course)
        if not can_complete(course, current, activity_id):
            return jsonify({"ok": False, "error": "Terminez d’abord l’activité précédente."}), 409
        existing = current.get("answers", {}).get(activity_id)
        if isinstance(existing, Mapping):
            return jsonify({"ok": True, "already_answered": True, "correct": bool(existing.get("correct")), "progress": current})
        payload = request.get_json(silent=True) or {}
        answer_payload = payload.get("answer")
        if not isinstance(answer_payload, Mapping):
            return jsonify({"ok": False, "error": "Réponse invalide."}), 400
        try:
            correct, response_payload = _evaluate_answer(activity, answer_payload)
        except TrackingError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        answer = {
            **response_payload,
            "correct": correct,
            "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        result = store().complete_activity(
            access,
            activity_id,
            activity_order=order,
            scored_activity_ids=scored_ids,
            mastery_score=float(course.get("settings", {}).get("mastery_score") or 80),
            answer=answer,
        )
        return jsonify(
            {
                "ok": True,
                "already_answered": False,
                "correct": correct,
                "progress": project_progress(result, course),
                "next_activity_id": result.get("current_activity_id"),
            }
        )

    return blueprint
