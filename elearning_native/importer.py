from __future__ import annotations

import contextlib
import hashlib
import html
import json
import os
import posixpath
import re
import shutil
import stat
import tempfile
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows development fallback
    fcntl = None


COURSE_FORMAT_VERSION = 1
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_ENTRIES = 5_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 1024 * 1024 * 1024
DEFAULT_MAX_JSON_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_HTML_BYTES = 4 * 1024 * 1024

_SAFE_IDENTIFIER_RE = re.compile(r"[^a-zA-Z0-9._-]+")
_SAFE_COURSE_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{1,96}$")
_DATA_TYPE_RE = re.compile(r'\bdata-type\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_EXTERNAL_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_FILL_SELECT_RE = re.compile(
    r'<select\b[^>]*\bdata-group-id=["\']([^"\']+)["\'][^>]*>.*?</select>',
    re.IGNORECASE | re.DOTALL,
)
_FILL_INPUT_RE = re.compile(
    r'<input\b[^>]*\bdata-group-id=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE | re.DOTALL,
)

_ALLOWED_ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp4",
    ".webm",
    ".mp3",
    ".m4a",
    ".ogg",
    ".wav",
    ".vtt",
    ".srt",
    ".pdf",
    ".json",
}

_QUESTION_TYPE_MAP = {
    "singleSelectText": "single_choice",
    "multipleSelect": "multiple_choice",
    "statement": "statement",
    "textMatching": "matching",
    "fillInTheBlank": "fill_blank",
}


class CourseImportError(ValueError):
    """Raised when an archive cannot safely become a native course."""


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(_json_dump(payload))
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(temporary_name)
        raise


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_identifier(value: Any, *, fallback: str) -> str:
    normalized = _SAFE_IDENTIFIER_RE.sub("-", str(value or "").strip()).strip("-._")
    return (normalized or fallback)[:96]


def _safe_css_color(value: Any, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", candidate):
        return candidate.lower()
    return fallback


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _localized(value: Any, locale: str, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, Mapping):
        return default
    direct = value.get(locale)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for candidate in value.values():
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return default


def _archive_member_name(raw_name: str) -> str:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise CourseImportError("Chemin de fichier ZIP invalide.")
    candidate = PurePosixPath(raw_name)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise CourseImportError(f"Chemin de fichier ZIP dangereux : {raw_name!r}")
    normalized = posixpath.normpath(raw_name)
    if normalized.startswith("../") or normalized == "..":
        raise CourseImportError(f"Chemin de fichier ZIP dangereux : {raw_name!r}")
    return normalized


def _validated_members(
    archive: zipfile.ZipFile,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_member_bytes: int,
) -> Dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos:
        raise CourseImportError("Le ZIP est vide.")
    if len(infos) > max_entries:
        raise CourseImportError(f"Le ZIP contient trop de fichiers ({len(infos)} > {max_entries}).")

    members: Dict[str, zipfile.ZipInfo] = {}
    casefolded: set[str] = set()
    total_size = 0
    for info in infos:
        name = _archive_member_name(info.filename)
        if info.is_dir():
            continue
        unix_mode = info.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise CourseImportError(f"Les liens symboliques sont interdits dans le ZIP : {name}")
        if info.flag_bits & 0x1:
            raise CourseImportError(f"Les fichiers ZIP chiffrés ne sont pas acceptés : {name}")
        if info.file_size > max_member_bytes:
            raise CourseImportError(f"Fichier trop volumineux dans le ZIP : {name}")
        total_size += info.file_size
        if total_size > max_uncompressed_bytes:
            raise CourseImportError("Le contenu décompressé du ZIP dépasse la limite autorisée.")
        folded = name.casefold()
        if folded in casefolded:
            raise CourseImportError(f"Nom de fichier dupliqué dans le ZIP : {name}")
        casefolded.add(folded)
        members[name] = info

    return members


def _read_member(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    name: str,
    *,
    max_bytes: int,
    required: bool = True,
) -> Optional[bytes]:
    info = members.get(name)
    if info is None:
        if required:
            raise CourseImportError(f"Fichier obligatoire absent du ZIP : {name}")
        return None
    if info.file_size > max_bytes:
        raise CourseImportError(f"Fichier trop volumineux : {name}")
    with archive.open(info, "r") as source:
        payload = source.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise CourseImportError(f"Fichier trop volumineux : {name}")
    return payload


def _read_json_member(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    name: str,
    *,
    required: bool = True,
) -> Dict[str, Any]:
    raw = _read_member(
        archive,
        members,
        name,
        max_bytes=DEFAULT_MAX_JSON_BYTES,
        required=required,
    )
    if raw is None:
        return {}
    try:
        text = raw.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise CourseImportError(f"Encodage invalide pour {name}.") from exc

    # Current manual Easygenerator packages contain plain JSON despite the .js
    # extension. The conservative fallback also supports older `var x = {...}`
    # wrappers without evaluating JavaScript.
    if not text.startswith("{"):
        first = text.find("{")
        last = text.rfind("}")
        if first < 0 or last <= first:
            raise CourseImportError(f"JSON introuvable dans {name}.")
        text = text[first : last + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CourseImportError(f"JSON invalide dans {name} : {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CourseImportError(f"Objet JSON attendu dans {name}.")
    return payload


class _HTMLSanitizer(HTMLParser):
    _allowed_tags = {
        "a",
        "b",
        "br",
        "div",
        "em",
        "i",
        "img",
        "input",
        "li",
        "ol",
        "option",
        "p",
        "select",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
    _void_tags = {"br", "img", "input"}
    _drop_content_tags = {"script", "style", "object", "embed", "template"}
    _generic_attributes = {"class", "title", "role"}
    _tag_attributes = {
        "a": {"href", "target"},
        "img": {"src", "data-src", "alt", "width", "height"},
        "td": {"colspan", "rowspan"},
        "th": {"colspan", "rowspan", "scope"},
        "option": {"value"},
        "select": {"data-group-id"},
        "input": {"type", "autocomplete", "spellcheck", "data-group-id"},
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._drop_depth = 0

    @staticmethod
    def _safe_url(value: str, *, image: bool = False) -> Optional[str]:
        raw = str(value or "").strip()
        if not raw:
            return None
        parsed = urlparse(raw)
        if image:
            normalized = posixpath.normpath(raw.lstrip("./"))
            if parsed.scheme or parsed.netloc or normalized.startswith("../"):
                return None
            if not normalized.startswith("media/"):
                return None
            if Path(normalized).suffix.lower() not in _ALLOWED_ASSET_EXTENSIONS:
                return None
            return normalized
        if parsed.scheme and parsed.scheme.lower() not in {"http", "https", "mailto"}:
            return None
        if not parsed.scheme and (raw.startswith("//") or raw.lower().startswith("javascript:")):
            return None
        return raw

    @staticmethod
    def _clean_class(value: str) -> str:
        tokens = re.findall(r"[a-zA-Z0-9_-]+", str(value or ""))
        return " ".join(tokens[:20])

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self._drop_content_tags:
            self._drop_depth += 1
            return
        if self._drop_depth or tag not in self._allowed_tags:
            return

        if tag == "input":
            source_classes = " ".join(
                str(value or "") for name, value in attrs if str(name or "").lower() == "class"
            )
            if "native-elearning-blank" not in self._clean_class(source_classes).split():
                return

        cleaned: List[Tuple[str, str]] = []
        allowed = self._generic_attributes | self._tag_attributes.get(tag, set())
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            value = str(raw_value or "")
            if name.startswith("on"):
                continue
            if name.startswith("aria-") or name.startswith("data-"):
                pass
            elif name not in allowed:
                continue
            if name == "class":
                value = self._clean_class(value)
                if not value:
                    continue
            elif name in {"src", "data-src"}:
                safe = self._safe_url(value, image=True)
                if safe is None:
                    continue
                value = safe
            elif name == "href":
                safe = self._safe_url(value)
                if safe is None:
                    continue
                value = safe
            elif name in {"width", "height", "colspan", "rowspan"}:
                if not re.fullmatch(r"\d{1,4}", value):
                    continue
            elif tag == "input" and name == "type":
                value = value.lower()
                if value != "text":
                    continue
            elif tag == "input" and name == "autocomplete":
                value = "off"
            elif tag == "input" and name == "spellcheck":
                value = "false"
            cleaned.append((name, value))

        rendered_attrs = "".join(
            f' {name}="{html.escape(value, quote=True)}"' for name, value in cleaned
        )
        if tag == "a":
            rendered_attrs += ' rel="noopener noreferrer"'
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._drop_content_tags:
            if self._drop_depth:
                self._drop_depth -= 1
            return
        if self._drop_depth or tag not in self._allowed_tags or tag in self._void_tags:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.parts.append(html.escape(data, quote=False))

    def get_html(self) -> str:
        return "".join(self.parts).strip()


def sanitize_course_html(value: str) -> str:
    sanitizer = _HTMLSanitizer()
    sanitizer.feed(str(value or ""))
    sanitizer.close()
    return sanitizer.get_html()


def _safe_asset_reference(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    while raw.startswith("../"):
        raw = raw[3:]
    raw = raw.lstrip("./")
    normalized = posixpath.normpath(raw)
    if normalized.startswith("../") or not normalized.startswith("media/"):
        return ""
    if Path(normalized).suffix.lower() not in _ALLOWED_ASSET_EXTENSIONS:
        return ""
    return normalized


class _EasygeneratorConverter:
    def __init__(
        self,
        archive: zipfile.ZipFile,
        members: Mapping[str, zipfile.ZipInfo],
        course_data: Mapping[str, Any],
        settings: Mapping[str, Any],
        locale: str,
    ) -> None:
        self.archive = archive
        self.members = members
        self.course_data = course_data
        self.settings = settings
        self.locale = locale
        self.warnings: List[str] = []
        self.block_types: Counter[str] = Counter()
        self.content_block_count = 0
        self._seen_content_ids: set[str] = set()

    def _html_member(self, content_id: str, *, suffix: str = "") -> str:
        candidate = f"content/{self.locale}/{content_id}{suffix}.html"
        raw = _read_member(
            self.archive,
            self.members,
            candidate,
            max_bytes=DEFAULT_MAX_HTML_BYTES,
            required=False,
        )
        if raw is None:
            self.warnings.append(f"Contenu absent : {candidate}")
            return ""
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            self.warnings.append(f"Contenu non UTF-8 ignoré : {candidate}")
            return ""

    def _video_from_html(self, raw_html: str, content_id: str) -> Dict[str, Any]:
        source_match = re.search(r"[?&]source=([a-zA-Z0-9._-]+)", raw_html)
        if not source_match:
            self.warnings.append(f"Source vidéo introuvable pour le bloc {content_id}.")
            return {"src": "", "poster": "", "duration_seconds": None}
        source_id = source_match.group(1)
        metadata_name = f"media/{source_id}.json"
        metadata = _read_json_member(
            self.archive,
            self.members,
            metadata_name,
            required=False,
        )
        src = _safe_asset_reference(metadata.get("sourceUrl"))
        poster = _safe_asset_reference(metadata.get("thumbnail"))
        if not src:
            fallback = f"media/{source_id}.mp4"
            if fallback in self.members:
                src = fallback
        if not src or src not in self.members:
            self.warnings.append(f"Fichier vidéo absent pour le bloc {content_id}.")
            src = ""
        if poster and poster not in self.members:
            poster = ""
        return {"src": src, "poster": poster, "duration_seconds": None}

    def content_node(self, node: Mapping[str, Any]) -> Dict[str, Any]:
        content_id = str(node.get("id") or "").strip()
        if not content_id:
            self.warnings.append("Bloc sans identifiant ignoré.")
            return {"id": "", "type": "unknown", "html": "", "children": []}
        raw_html = self._html_member(content_id)
        match = _DATA_TYPE_RE.search(raw_html)
        block_type = match.group(1) if match else "html"
        self.block_types[block_type] += 1
        if content_id not in self._seen_content_ids:
            self.content_block_count += 1
            self._seen_content_ids.add(content_id)

        converted: Dict[str, Any] = {
            "id": content_id,
            "type": block_type,
            "html": "",
            "children": [
                self.content_node(child)
                for child in (node.get("children") or [])
                if isinstance(child, Mapping)
            ],
        }
        if block_type == "singleVideo":
            converted["video"] = self._video_from_html(raw_html, content_id)
        else:
            converted["html"] = sanitize_course_html(raw_html)
        if _EXTERNAL_URL_RE.search(raw_html):
            converted["contains_external_link"] = True
        return converted

    def _fill_blank_prompt(self, activity: Mapping[str, Any]) -> Tuple[str, Dict[str, str]]:
        activity_id = str(activity.get("id") or "")
        raw = self._html_member(activity_id, suffix="_content")
        groups = {
            str(group.get("id") or ""): group
            for group in (activity.get("answerGroups") or [])
            if isinstance(group, Mapping)
        }
        control_modes: Dict[str, str] = {}

        def register_control(group_id: str, mode: str) -> None:
            existing = control_modes.get(group_id)
            control_modes[group_id] = mode if existing in {None, mode} else "mixed"

        def select_replacement(match: re.Match[str]) -> str:
            group_id = match.group(1)
            register_control(group_id, "choice")
            group = groups.get(group_id, {})
            options = ['<option value="">Choisir une réponse…</option>']
            for answer in group.get("answers") or []:
                if not isinstance(answer, Mapping):
                    continue
                answer_id = html.escape(str(answer.get("id") or ""), quote=True)
                label = html.escape(_localized(answer.get("text"), self.locale))
                options.append(f'<option value="{answer_id}">{label}</option>')
            safe_group = html.escape(group_id, quote=True)
            return f'<select class="native-elearning-blank" data-group-id="{safe_group}">' + "".join(options) + "</select>"

        def input_replacement(match: re.Match[str]) -> str:
            group_id = match.group(1)
            register_control(group_id, "text")
            safe_group = html.escape(group_id, quote=True)
            return (
                '<input type="text" class="native-elearning-blank native-elearning-blank--text" '
                f'data-group-id="{safe_group}" autocomplete="off" spellcheck="false" '
                'aria-label="Réponse à compléter">'
            )

        rebuilt = _FILL_SELECT_RE.sub(select_replacement, raw)
        rebuilt = _FILL_INPUT_RE.sub(input_replacement, rebuilt)
        return sanitize_course_html(rebuilt), control_modes

    def activity(self, raw_activity: Mapping[str, Any], sequence: int) -> Dict[str, Any]:
        source_type = str(raw_activity.get("type") or "unknown")
        activity_id = str(raw_activity.get("id") or f"activity-{sequence}")
        base: Dict[str, Any] = {
            "id": activity_id,
            "sequence": sequence,
            "title": _localized(raw_activity.get("title"), self.locale, f"Activité {sequence + 1}"),
            "source_type": source_type,
            "type": "content" if source_type == "informationContent" else "question",
            "scored": source_type != "informationContent",
        }
        if source_type == "informationContent":
            base["blocks"] = [
                self.content_node(node)
                for node in (raw_activity.get("learningContents") or [])
                if isinstance(node, Mapping)
            ]
            return base

        question_type = _QUESTION_TYPE_MAP.get(source_type, "unsupported")
        base["question_type"] = question_type
        if question_type == "unsupported":
            raise CourseImportError(f"Type de question Easygenerator non pris en charge : {source_type}")

        if question_type in {"single_choice", "multiple_choice", "statement"}:
            base["options"] = [
                {
                    "id": str(answer.get("id") or ""),
                    "text": _localized(answer.get("text"), self.locale),
                    "is_correct": bool(answer.get("isCorrect")),
                }
                for answer in (raw_activity.get("answers") or [])
                if isinstance(answer, Mapping)
            ]
            option_ids = [str(option.get("id") or "") for option in base["options"]]
            correct_count = sum(1 for option in base["options"] if option.get("is_correct"))
            if not option_ids or any(not value for value in option_ids) or len(set(option_ids)) != len(option_ids):
                raise CourseImportError(f"Réponses invalides pour la question {activity_id}.")
            if question_type == "single_choice" and correct_count != 1:
                raise CourseImportError(f"La question {activity_id} doit avoir une seule bonne réponse.")
            if question_type != "single_choice" and correct_count < 1:
                raise CourseImportError(f"La question {activity_id} ne contient aucune bonne réponse.")
        elif question_type == "matching":
            base["pairs"] = [
                {
                    "id": str(answer.get("id") or ""),
                    "left": _localized(answer.get("key"), self.locale),
                    "right": _localized(answer.get("value"), self.locale),
                }
                for answer in (raw_activity.get("answers") or [])
                if isinstance(answer, Mapping)
            ]
            pair_ids = [str(pair.get("id") or "") for pair in base["pairs"]]
            if not pair_ids or any(not value for value in pair_ids) or len(set(pair_ids)) != len(pair_ids):
                raise CourseImportError(f"Associations invalides pour la question {activity_id}.")
        elif question_type == "fill_blank":
            base["prompt_html"], control_modes = self._fill_blank_prompt(raw_activity)
            base["answer_groups"] = [
                {
                    "id": str(group.get("id") or ""),
                    "mode": control_modes.get(str(group.get("id") or ""), ""),
                    "answers": [
                        {
                            "id": str(answer.get("id") or ""),
                            "text": _localized(answer.get("text"), self.locale),
                            "is_correct": bool(answer.get("isCorrect")),
                            "match_case": bool(answer.get("matchCase")),
                        }
                        for answer in (group.get("answers") or [])
                        if isinstance(answer, Mapping)
                    ],
                }
                for group in (raw_activity.get("answerGroups") or [])
                if isinstance(group, Mapping)
            ]
            group_ids = [str(group.get("id") or "") for group in base["answer_groups"]]
            if not group_ids or any(not value for value in group_ids) or len(set(group_ids)) != len(group_ids):
                raise CourseImportError(f"Groupes de réponses invalides pour la question {activity_id}.")
            prompt_group_ids = set(re.findall(r'data-group-id="([^"]+)"', base["prompt_html"]))
            if prompt_group_ids != set(group_ids) or set(control_modes) != set(group_ids):
                raise CourseImportError(f"Texte à trous incomplet pour la question {activity_id}.")
            for group in base["answer_groups"]:
                answers = group.get("answers") or []
                answer_ids = [str(answer.get("id") or "") for answer in answers]
                correct_count = sum(1 for answer in answers if answer.get("is_correct"))
                if (
                    not answer_ids
                    or any(not value for value in answer_ids)
                    or len(set(answer_ids)) != len(answer_ids)
                ):
                    raise CourseImportError(f"Réponses de texte à trous invalides pour la question {activity_id}.")
                if group.get("mode") == "choice" and correct_count != 1:
                    raise CourseImportError(f"Réponses de texte à trous invalides pour la question {activity_id}.")
                if group.get("mode") == "text" and not any(
                    answer.get("is_correct") and str(answer.get("text") or "").strip()
                    for answer in answers
                ):
                    raise CourseImportError(f"Réponses de texte à trous invalides pour la question {activity_id}.")
                if group.get("mode") not in {"choice", "text"}:
                    raise CourseImportError(f"Format de texte à trous invalide pour la question {activity_id}.")
        return base

    def course(self, *, source_sha256: str) -> Dict[str, Any]:
        source_id = _safe_identifier(self.course_data.get("id"), fallback=source_sha256[:16])
        course_id = _safe_identifier(f"eg-{source_id}", fallback=f"eg-{source_sha256[:16]}")
        source_version = _safe_identifier(
            self.course_data.get("version"),
            fallback=source_sha256[:12],
        )
        sections: List[Dict[str, Any]] = []
        activity_order: List[str] = []
        question_types: Counter[str] = Counter()
        sequence = 0
        for section_index, raw_section in enumerate(self.course_data.get("sections") or []):
            if not isinstance(raw_section, Mapping):
                continue
            activities: List[Dict[str, Any]] = []
            for raw_activity in raw_section.get("questions") or []:
                if not isinstance(raw_activity, Mapping):
                    continue
                converted = self.activity(raw_activity, sequence)
                activities.append(converted)
                activity_order.append(converted["id"])
                if converted.get("question_type"):
                    question_types[str(converted["question_type"])] += 1
                sequence += 1
            sections.append(
                {
                    "id": str(raw_section.get("id") or f"section-{section_index + 1}"),
                    "title": _localized(raw_section.get("title"), self.locale, f"Séquence {section_index + 1}"),
                    "learning_objective": _localized(raw_section.get("learningObjective"), self.locale),
                    "image": _safe_asset_reference(_localized(raw_section.get("imageUrl"), self.locale)),
                    "activities": activities,
                }
            )

        if not activity_order:
            raise CourseImportError("Le cours ne contient aucune activité convertible.")
        if len(set(activity_order)) != len(activity_order):
            raise CourseImportError("Le cours contient des identifiants d’activité dupliqués.")

        introductions = [
            self.content_node(node)
            for node in (self.course_data.get("introductions") or [])
            if isinstance(node, Mapping)
        ]

        branding = self.settings.get("branding") if isinstance(self.settings.get("branding"), Mapping) else {}
        colors = branding.get("colors") if isinstance(branding, Mapping) else []
        palette = {
            str(item.get("key")): str(item.get("value"))
            for item in (colors or [])
            if isinstance(item, Mapping) and item.get("key") and item.get("value")
        }
        mastery = self.settings.get("masteryScore") if isinstance(self.settings.get("masteryScore"), Mapping) else {}
        attempts = self.settings.get("numberOfAttempts") if isinstance(self.settings.get("numberOfAttempts"), Mapping) else {}
        timer = self.settings.get("timer") if isinstance(self.settings.get("timer"), Mapping) else {}
        force_navigation = self.settings.get("forceNavigation") if isinstance(self.settings.get("forceNavigation"), Mapping) else {}

        scored_count = sum(
            1 for section in sections for activity in section["activities"] if activity.get("scored")
        )
        asset_paths = sorted(
            name
            for name in self.members
            if name.startswith("media/")
            and Path(name).suffix.lower() in _ALLOWED_ASSET_EXTENSIONS
        )
        return {
            "format_version": COURSE_FORMAT_VERSION,
            "id": course_id,
            "version": source_version,
            "title": _localized(self.course_data.get("title"), self.locale, "Cours importé"),
            "locale": self.locale,
            "author_name": str(self.course_data.get("authorFullName") or "").strip(),
            "source": {
                "type": "easygenerator-manual-scorm",
                "source_id": source_id,
                "source_version": str(self.course_data.get("version") or ""),
                "sha256": source_sha256,
            },
            "settings": {
                "mastery_score": _bounded_int(
                    mastery.get("score"), default=80, minimum=0, maximum=100
                ),
                "mastery_is_overall": bool(mastery.get("isOverall")),
                "force_navigation": bool(force_navigation.get("enabled")),
                "attempts_limited": bool(attempts.get("isLimited")),
                "attempts_limit": _bounded_int(
                    attempts.get("attemptsLimit"), default=0, minimum=0, maximum=10_000
                ),
                "source_timer_enabled": bool(timer.get("enabled")),
            },
            "theme": {
                "main_color": _safe_css_color(palette.get("main-color"), fallback="#4f46e5"),
                "button_color": _safe_css_color(
                    palette.get("cta-button-color"),
                    fallback=_safe_css_color(palette.get("main-color"), fallback="#4f46e5"),
                ),
                "text_color": _safe_css_color(palette.get("text-color"), fallback="#172033"),
            },
            "introduction": introductions,
            "sections": sections,
            "activity_order": activity_order,
            "counts": {
                "sections": len(sections),
                "activities": len(activity_order),
                "scored_activities": scored_count,
                "content_blocks": self.content_block_count,
                "assets": len(asset_paths),
                "question_types": dict(sorted(question_types.items())),
                "block_types": dict(sorted(self.block_types.items())),
            },
            "assets": asset_paths,
            "import_warnings": sorted(set(self.warnings)),
        }


def _detect_locale(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    course_data: Mapping[str, Any],
) -> str:
    language_raw = _read_member(
        archive,
        members,
        "languageSettings.json",
        max_bytes=1024 * 1024,
        required=False,
    )
    if language_raw:
        try:
            language_settings = json.loads(language_raw.decode("utf-8-sig"))
            if isinstance(language_settings, list):
                default = next(
                    (item for item in language_settings if isinstance(item, Mapping) and item.get("isDefault")),
                    None,
                )
                if default:
                    language = str(default.get("language") or "").strip()
                    if language:
                        return language
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    title = course_data.get("title")
    if isinstance(title, Mapping):
        for key in title:
            if re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z]{2,4})?", str(key)):
                return str(key)
    return "fr"


def _copy_assets(
    archive: zipfile.ZipFile,
    members: Mapping[str, zipfile.ZipInfo],
    asset_names: Iterable[str],
    destination: Path,
) -> None:
    for name in asset_names:
        info = members.get(name)
        if info is None:
            raise CourseImportError(f"Média référencé mais absent : {name}")
        relative = PurePosixPath(name)
        target = destination.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)


@contextlib.contextmanager
def _catalog_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".import.lock"
    with lock_path.open("a+b") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def import_easygenerator_course(
    archive_path: os.PathLike[str] | str,
    catalog_root: os.PathLike[str] | str,
    *,
    archive_source: bool = True,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
) -> Dict[str, Any]:
    source_path = Path(archive_path).resolve()
    if not source_path.is_file():
        raise CourseImportError("Archive Easygenerator introuvable.")
    archive_size = source_path.stat().st_size
    if archive_size <= 0 or archive_size > max_archive_bytes:
        raise CourseImportError(
            f"Taille du ZIP non autorisée ({archive_size} octets, limite {max_archive_bytes})."
        )

    source_sha256 = _sha256_file(source_path)
    try:
        archive = zipfile.ZipFile(source_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise CourseImportError("Le fichier fourni n’est pas un ZIP valide.") from exc

    with archive:
        members = _validated_members(
            archive,
            max_entries=max_entries,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_member_bytes=max_member_bytes,
        )
        bad_member = archive.testzip()
        if bad_member:
            raise CourseImportError(f"Le fichier {bad_member} est corrompu dans le ZIP.")
        course_data = _read_json_member(archive, members, "content/data.js")
        settings = _read_json_member(archive, members, "settings.js", required=False)
        locale = _detect_locale(archive, members, course_data)
        converter = _EasygeneratorConverter(archive, members, course_data, settings, locale)
        course = converter.course(source_sha256=source_sha256)

        root = Path(catalog_root).resolve()
        courses_root = root / "courses"
        course_root = courses_root / course["id"]
        if not _SAFE_COURSE_ID_RE.fullmatch(course["id"]):
            raise CourseImportError("Identifiant de cours invalide après conversion.")

        with _catalog_lock(root):
            course_root.mkdir(parents=True, exist_ok=True)
            version_name = _safe_identifier(course["version"], fallback=source_sha256[:12])
            target = course_root / version_name
            if target.exists():
                current_course_path = target / "course.json"
                if current_course_path.is_file():
                    try:
                        existing = json.loads(current_course_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        existing = {}
                    if existing.get("source", {}).get("sha256") == source_sha256:
                        _atomic_write_json(course_root / "current.json", {"version": version_name})
                        return existing
                version_name = f"{version_name}-{source_sha256[:8]}"
                target = course_root / version_name
                if target.exists():
                    raise CourseImportError("Cette version de cours existe déjà mais est incohérente.")

            course["version"] = version_name
            staging = Path(tempfile.mkdtemp(prefix=".import-", dir=str(course_root)))
            try:
                assets_root = staging / "assets"
                _copy_assets(archive, members, course["assets"], assets_root)
                _atomic_write_json(staging / "course.json", course)
                if archive_source:
                    shutil.copyfile(source_path, staging / "source.zip")
                os.replace(staging, target)
                _atomic_write_json(course_root / "current.json", {"version": version_name})
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
    return course


class CourseCatalog:
    def __init__(self, root: os.PathLike[str] | str) -> None:
        self.root = Path(root).resolve()

    def import_zip(self, archive_path: os.PathLike[str] | str, *, archive_source: bool = True) -> Dict[str, Any]:
        return import_easygenerator_course(
            archive_path,
            self.root,
            archive_source=archive_source,
        )

    def _course_root(self, course_id: str) -> Path:
        if not _SAFE_COURSE_ID_RE.fullmatch(str(course_id or "")):
            raise CourseImportError("Identifiant de cours invalide.")
        return self.root / "courses" / course_id

    def load_course(self, course_id: str, version: Optional[str] = None) -> Dict[str, Any]:
        course_root = self._course_root(course_id)
        if version is None:
            try:
                pointer = json.loads((course_root / "current.json").read_text(encoding="utf-8"))
                version = str(pointer["version"])
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise CourseImportError("Cours introuvable.") from exc
        safe_version = _safe_identifier(version, fallback="")
        if not safe_version or safe_version != version:
            raise CourseImportError("Version de cours invalide.")
        path = course_root / safe_version / "course.json"
        try:
            course = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CourseImportError("Cours introuvable ou corrompu.") from exc
        if course.get("id") != course_id or course.get("version") != safe_version:
            raise CourseImportError("Métadonnées de cours incohérentes.")
        return course

    def list_courses(self) -> List[Dict[str, Any]]:
        courses_root = self.root / "courses"
        if not courses_root.is_dir():
            return []
        courses: List[Dict[str, Any]] = []
        for course_dir in sorted(courses_root.iterdir(), key=lambda item: item.name):
            if not course_dir.is_dir() or not _SAFE_COURSE_ID_RE.fullmatch(course_dir.name):
                continue
            try:
                course = self.load_course(course_dir.name)
            except CourseImportError:
                continue
            courses.append(course)
        return sorted(courses, key=lambda item: str(item.get("title") or "").casefold())

    def asset_path(self, course_id: str, version: str, asset_name: str) -> Path:
        course_root = self._course_root(course_id)
        safe_version = _safe_identifier(version, fallback="")
        normalized = _archive_member_name(str(asset_name or ""))
        if not safe_version or safe_version != version or not normalized.startswith("media/"):
            raise CourseImportError("Chemin de média invalide.")
        path = (course_root / safe_version / "assets").joinpath(*PurePosixPath(normalized).parts)
        expected_root = (course_root / safe_version / "assets").resolve()
        resolved = path.resolve()
        if expected_root not in resolved.parents or not resolved.is_file():
            raise CourseImportError("Média introuvable.")
        return resolved
