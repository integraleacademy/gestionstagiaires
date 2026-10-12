"""Versioned MAC APS resources: immutable v1 and a scoped 14-hour v2.

The 2025 order is a historical curriculum reference, not a claim that its
exception has been extended. Digital study never awards regulatory stage hours.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent / "mac_aps"
LEGACY_VERSION = "20261012-macaps-v1"
VERSION = "20261012-macaps-v2"
SUPPORTED_VERSIONS = (LEGACY_VERSION, VERSION)
MEDIA_REVISION = "20261012-mac-aps-v2"
_MEDIA_FIELDS = ("src", "poster", "captions", "render_revision", "burned_captions",
                 "video_sha256", "caption_cues")
PRINCIPAL_MODULE_NUMBERS = ("02", "03", "05")
PRINCIPAL_MINUTES = {"02": 180, "03": 240, "05": 420}
TOTAL_MINUTES = 840
NOTICE = (
    "Support numérique de préparation et de révision de 14 heures, structuré selon "
    "les objectifs de l’arrêté du 27 janvier 2025. Son ouverture temporaire au "
    "distanciel se terminait le 31 décembre 2025. Le parcours ne vaut ni autorisation "
    "de FOAD en 2026, ni attestation de stage MAC APS, ni validation de gestes pratiques."
)
MODULES = {
    "02": {"title": "Principes de la République", "regulatory_minutes": 180,
           "objective": "Appliquer les libertés, l’égalité, la laïcité et le respect de la dignité dans les missions de sécurité.", "icon": "republique"},
    "03": {"title": "Cadre juridique et déontologie", "regulatory_minutes": 240,
           "objective": "Actualiser les limites d’intervention et justifier une décision professionnelle à partir des faits.", "icon": "droit"},
    "05": {"title": "Prévention des risques terroristes · objectifs théoriques", "regulatory_minutes": 420,
           "objective": "Reconnaître les menaces, maintenir une vigilance factuelle, identifier les blessures et alerter les secours.", "icon": "prevention"},
}


def is_training(value):
    if isinstance(value, dict):
        value = value.get("training_type", "")
    normalized = re.sub(r"[\W_]+", " ", str(value or "").upper()).strip()
    return normalized.startswith("MAC APS") or normalized.startswith("APS MAC")


@lru_cache(maxsize=1)
def _legacy():
    return json.loads((ROOT / "versions" / LEGACY_VERSION / "snapshot.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _plan():
    return json.loads((ROOT / "v2" / "curriculum.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _lessons(version=None):
    path = ROOT / "lessons.json" if version == LEGACY_VERSION else ROOT / "v2" / "lessons.json"
    return json.loads(path.read_text(encoding="utf-8"))["lessons"]


@lru_cache(maxsize=2)
def _exams(version=None):
    path = ROOT / "exams.json" if version == LEGACY_VERSION else ROOT / "v2" / "exams.json"
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _media():
    return json.loads((ROOT / "media_manifest.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=5)
def _original_media(number):
    return json.loads((ROOT / "assets" / "media" / "mac-aps" / "v1" /
                       ("module-" + number + ".json")).read_text(encoding="utf-8"))


def _original_video(number):
    """Keep teaching text, identifiers and the recorded timeline in the snapshot."""
    course = _legacy()["courses"].get("academy-macaps-" + number, {})
    for section in course.get("sections", []):
        for activity in section.get("activities", []):
            for block in activity.get("blocks", []):
                video = block.get("video")
                if video and video.get("id") == "macaps-" + number + "-video":
                    return video
    raise ValueError("Original MAC APS video is missing: " + number)


def _reviewed_media(number):
    manifest = _media()
    if manifest.get("revision") != MEDIA_REVISION:
        return None
    entry = manifest.get("videos", {}).get(number)
    prefix = "media/mac-aps/v2/module-" + number
    if (not isinstance(entry, dict) or entry.get("render_revision") != MEDIA_REVISION
            or any(entry.get(key) != prefix + extension
                   for key, extension in (("src", ".mp4"), ("poster", ".jpg"), ("captions", ".vtt")))):
        raise ValueError("Reviewed MAC APS media is invalid: " + number)
    return entry


def _video(number, version=None):
    if entry := _reviewed_media(number):
        video = copy.deepcopy(_original_media(number))
        video.update({key: copy.deepcopy(entry[key]) for key in _MEDIA_FIELDS if key in entry})
        return video
    video = _media().get("videos", {}).get(number)
    return copy.deepcopy(video) if video else None


def _with_reviewed_media(course):
    """Overlay only visual media on detached courses; old signed URLs still work."""
    if not course or _media().get("revision") != MEDIA_REVISION:
        return course
    assets = course.setdefault("assets", [])
    for section in course.get("sections", []):
        for activity in section.get("activities", []):
            pending = list(activity.get("blocks", []))
            while pending:
                block = pending.pop()
                pending.extend(block.get("children") or [])
                video = block.get("video")
                if not isinstance(video, dict):
                    continue
                match = re.fullmatch(r"macaps-(0[1-5])-video", str(video.get("id") or ""))
                if not match:
                    continue
                number = match.group(1)
                entry = _reviewed_media(number)
                video.update({key: copy.deepcopy(entry[key]) for key in _MEDIA_FIELDS if key in entry})
                original = _original_video(number)
                for row in (original, entry):
                    for key in ("src", "poster", "captions"):
                        if row[key] not in assets:
                            assets.append(row[key])
    course.setdefault("counts", {})["assets"] = len(assets)
    return course


def curriculum_ids(version=None):
    """Only mandatory modules for the requested edition; never complements."""
    if version == LEGACY_VERSION:
        return list(_legacy()["courses"])
    if version not in (None, VERSION):
        return []
    return ["academy-macaps-" + number for number in PRINCIPAL_MODULE_NUMBERS]


def bundled_course_ids():
    """Recognition set for CourseCatalog, including historical and extra IDs."""
    return list(dict.fromkeys([*curriculum_ids(LEGACY_VERSION), *curriculum_ids(),
                               *(item["id"] for item in _plan()["complements"])]))


def legal_objectives(version=None):
    if version not in (None, VERSION):
        return []
    return copy.deepcopy([{**row, "required_minutes": row["minimum_minutes"],
                           "required_seconds": row["minimum_minutes"] * 60,
                           "source_url": _plan()["source_url"],
                           "reference_period_end": _plan()["reference_period_end"],
                           "current_distance_authorization_claimed": False}
                          for row in _plan()["objectives"]])


def minimum_minutes(course_id, version=None):
    if version == LEGACY_VERSION:
        return int(_legacy()["courses"].get(course_id, {}).get("required_minutes", 0))
    if version not in (None, VERSION) or course_id not in curriculum_ids():
        return 0
    return PRINCIPAL_MINUTES[course_id[-2:]]


def required_section_ids(course_id, version=None):
    course = load_bundled_course(course_id, version)
    if not course or course.get("pedagogical_scope") == "complement":
        return []
    return [section["id"] for section in course["sections"]]


def regulatory_review(version=None):
    if version == LEGACY_VERSION:
        return copy.deepcopy(_legacy()["manifest"]["regulatory_review"])
    review = copy.deepcopy(_legacy()["manifest"]["regulatory_review"])
    review.update(version=VERSION, reviewed_on=_plan()["reviewed_on"],
                  digital_support_minutes=TOTAL_MINUTES, principal_module_minutes=copy.deepcopy(PRINCIPAL_MINUTES),
                  current_distance_authorization_claimed=False, reference_period_end="2025-12-31",
                  historical_distance_objectives=legal_objectives(),
                  eligible_objectives=legal_objectives(), duration_method=_plan()["duration_method"])
    review["notes"][0] = (
        "L’édition v2 fixe le parcours principal à 840 minutes : République 180, droit 240, "
        "huit objectifs théoriques de prévention terroriste 420. Les compléments ne sont pas "
        "inclus dans ces minutes. Le stage complet demeure distinct (34 heures ou 27 heures "
        "avec dispense de secourisme demandée et justifiée)."
    )
    return review


def _question_activity(lesson, suffix, title, questions, kind, minutes, **payload):
    fields, groups, public_questions = [], [], []
    for number, question in enumerate(questions, 1):
        group_id = lesson["id"] + "-" + suffix + "-" + str(number)
        options = "".join('<option value="%s">%s</option>' %
                          (html.escape(option["id"], quote=True), html.escape(option["text"]))
                          for option in question["options"])
        fields.append(
            '<div class="mac-question-group"><p><strong>%s. %s</strong></p>'
            '<select class="native-elearning-blank" data-group-id="%s" aria-label="%s">'
            '<option value="">Choisissez une réponse…</option>%s</select></div>'
            % (number, html.escape(question["prompt"]), group_id,
               html.escape(question["prompt"], quote=True), options))
        groups.append({"id": group_id, "mode": "choice", "answers": [
            {**option, "is_correct": option["id"] == question["answer"]}
            for option in question["options"]]})
        public_questions.append({"id": group_id, "prompt": question["prompt"],
                                 "options": copy.deepcopy(question["options"])})
    return {
        "id": lesson["id"] + "-" + suffix, "title": title, "type": "question",
        "question_type": "fill_blank", "scored": True, "planned_minutes": minutes,
        "required_minutes": minutes, "required_seconds": minutes * 60,
        "objective_id": lesson.get("objective_id"),
        "prompt": "Choisissez une réponse à chaque question, puis validez pour étudier les explications.",
        "prompt_html": "".join(fields), "answer_groups": groups,
        "explanation": "\n\n".join("%s. %s — %s" %
            (index, next(o["text"] for o in q["options"] if o["id"] == q["answer"]), q["explanation"])
            for index, q in enumerate(questions, 1)),
        "macaps": {"kind": kind, "ref": lesson["id"], "mode": lesson["mode"],
                   "module": lesson["module"], "objective": lesson["objective"],
                   "objective_id": lesson.get("objective_id"), "question_count": len(questions),
                   "questions": public_questions, **copy.deepcopy(payload)},
    }


def _section(lesson, minutes=25, scope="principal"):
    common = {key: copy.deepcopy(lesson[key]) for key in
              ("id", "module", "title", "objective", "mode", "source_urls")}
    common.update(ref=lesson["id"], objective_id=lesson.get("objective_id"), pedagogical_scope=scope)
    allocation = {20: (8, 5, 4, 3), 25: (10, 7, 5, 3), 26: (11, 7, 5, 3), 27: (12, 7, 5, 3)}[minutes]
    def content(suffix, label, kind, duration, **payload):
        return {"id": lesson["id"] + "-" + suffix, "title": label + " · " + lesson["title"],
                "type": "content", "scored": False, "blocks": [], "planned_minutes": duration,
                "required_minutes": duration if scope == "principal" else 0,
                "required_seconds": duration * 60 if scope == "principal" else 0,
                "objective_id": lesson.get("objective_id"),
                "macaps": {**common, "kind": kind, **copy.deepcopy(payload)}}
    scenario = lesson["scenario"]
    activities = [
        content("cours", "Comprendre", "lesson", allocation[0],
                **{key: lesson[key] for key in ("sections", "table", "flow") if key in lesson}),
        _question_activity(lesson, "application", "Appliquer · " + scenario["title"], scenario["steps"],
                           "application", allocation[1], example=lesson["example"], situation=scenario["intro"]),
        _question_activity(lesson, "quiz", "QCM · " + lesson["title"], lesson["quiz"], "quiz", allocation[2]),
        content("retenir", "À retenir", "recap", allocation[3], takeaways=lesson["takeaways"]),
    ]
    for activity in activities:
        activity["pedagogical_scope"] = scope
        activity["macaps"]["pedagogical_scope"] = scope
        if scope == "complement":
            activity["required_minutes"] = 0
            activity["required_seconds"] = 0
    return {"id": lesson["id"], "title": lesson["title"], "objective_id": lesson.get("objective_id"),
            "pedagogical_scope": scope, "delivery": "revision_theorique" if scope == "principal" else "presentiel_preparation",
            "planned_minutes": minutes, "required_minutes": minutes if scope == "principal" else 0,
            "required_seconds": minutes * 60 if scope == "principal" else 0, "activities": activities}


def _video_section(number, objective_id=None, scope="principal", minutes=7):
    video = _video(number)
    if not video:
        raise ValueError("Published MAC APS video is missing: " + number)
    ident = "macaps-" + number + "-video"
    video.update(id=ident, required=scope == "principal", lesson_explainer=True,
                 default_playback_rate=1, allowed_playback_rates=[0.85, 0.9, 1])
    duration = minutes if scope == "principal" else math.ceil(video["duration_seconds"] / 60)
    return {"id": "macaps-" + number + "-synthese", "title": video["title"],
            "objective_id": objective_id, "pedagogical_scope": scope, "planned_minutes": duration,
            "required_minutes": duration if scope == "principal" else 0,
            "required_seconds": duration * 60 if scope == "principal" else 0,
            "activities": [{"id": ident, "title": video["title"], "type": "content", "scored": False,
                "objective_id": objective_id, "pedagogical_scope": scope, "planned_minutes": duration,
                "required_minutes": duration if scope == "principal" else 0,
                "required_seconds": duration * 60 if scope == "principal" else 0,
                "macaps": {"kind": "video", "mode": "revision_theorique" if scope == "principal" else "presentiel_preparation",
                           "module": number, "objective_id": objective_id, "pedagogical_scope": scope},
                "blocks": [{"id": ident, "type": "video", "html": "", "children": [], "video": video}]}]}


def _assessment_section(objective):
    questions = _exams()["objectives"][objective["id"]]
    ident = objective["id"] + "-evaluation"
    lesson = {"id": ident, "module": objective["module"], "objective_id": objective["id"],
              "objective": objective["title"], "mode": "revision_theorique"}
    activity = _question_activity(lesson, "quiz", "Bilan d’objectif · " + objective["title"], questions,
                                  "quiz", objective["assessment_minutes"],
                                  is_objective_assessment=True, pedagogical_scope="principal")
    activity.update(is_objective_assessment=True, pedagogical_scope="principal")
    return {"id": ident, "title": "Bilan d’objectif · " + objective["title"],
            "objective_id": objective["id"], "pedagogical_scope": "principal",
            "planned_minutes": objective["assessment_minutes"], "required_minutes": objective["assessment_minutes"],
            "required_seconds": objective["assessment_minutes"] * 60, "activities": [activity]}


def _base_course(course_id, title, description, sections, scope, minutes, assets, mock_exam_id=None):
    activities = [activity for section in sections for activity in section["activities"]]
    course = {"id": course_id, "version": VERSION, "format_version": 1, "title": title,
              "training_label": "MAC APS", "preview_only": False, "description": description,
              "pedagogical_scope": scope, "planned_minutes": minutes, "required_minutes": minutes if scope == "principal" else 0,
              "principal_minutes": minutes if scope == "principal" else 0,
              "source": {"type": "academy-macaps", "sha256": hashlib.sha256((ROOT / "v2" / "lessons.json").read_bytes()).hexdigest()},
              "regulation": {"scope": "pedagogical_support", "pedagogical_scope": scope,
                  "automatic_stage_credit": False, "automatic_certificate": False,
                  "current_distance_authorization_claimed": False, "reference_period_end": "2025-12-31",
                  "reference": "Arrêté du 27 janvier 2025 · article 1 (référence historique des objectifs)",
                  "source_url": _plan()["source_url"], "notice": NOTICE},
              "assets": assets, "import_warnings": [], "introduction": [],
              "theme": {"main_color": "#164d78", "button_color": "#176dad", "text_color": "#152f45"},
              "settings": {"mastery_score": 80, "require_correct_answers": True, "force_navigation": scope == "principal"},
              "sections": sections, "activity_order": [activity["id"] for activity in activities],
              "counts": {"sections": len(sections), "activities": len(activities),
                         "scored_activities": sum(a["scored"] for a in activities), "assets": len(assets),
                         "required_videos": sum(bool(block.get("video", {}).get("required")) for a in activities for block in a.get("blocks", []))}}
    if mock_exam_id:
        course["mock_exam_id"] = mock_exam_id
    return course


@lru_cache(maxsize=3)
def _course(number):
    objectives = [row for row in legal_objectives() if row["module"] == number]
    lessons = {lesson["id"]: lesson for lesson in _lessons()}
    sections, assets, timed_objectives = [], [], []
    for objective in objectives:
        grouped = [_section(lessons[ref], objective["lesson_minutes"]) for ref in objective["lesson_refs"]]
        if objective.get("video_module"):
            grouped.append(_video_section(objective["video_module"], objective["id"], minutes=objective["video_minutes"]))
            video = _video(objective["video_module"])
            assets.extend(video[key] for key in ("src", "poster", "captions"))
        grouped.append(_assessment_section(objective))
        activity_ids = [a["id"] for section in grouped for a in section["activities"]]
        actual = sum(a["planned_minutes"] for section in grouped for a in section["activities"])
        if actual != objective["minimum_minutes"]:
            raise ValueError("MAC APS objective budget mismatch: " + objective["id"])
        timed_objectives.append({"id": objective["id"], "title": objective["title"],
                                 "required_seconds": objective["required_seconds"],
                                 "required_minutes": objective["minimum_minutes"], "activity_ids": activity_ids,
                                 "assessment_activity_id": activity_ids[-1], "source_url": objective["source_url"]})
        sections.extend(grouped)
    info = MODULES[number]
    course = _base_course("academy-macaps-" + number, "MAC APS · " + info["title"],
                          info["objective"], sections, "principal", PRINCIPAL_MINUTES[number], assets,
                          "macaps-module-" + number)
    course.update(timed_objectives=timed_objectives, regulatory_minutes=PRINCIPAL_MINUTES[number],
                  stage_module_minutes={"02": 180, "03": 240, "05": 780}[number])
    course["regulation"]["objectives"] = objectives
    return course


@lru_cache(maxsize=3)
def _complement(course_id):
    info = next(item for item in _plan()["complements"] if item["id"] == course_id)
    lessons = {lesson["id"]: lesson for lesson in _lessons(LEGACY_VERSION)}
    sections = [_section(lessons[ref], scope="complement") for ref in info["lesson_refs"]]
    sections.append(_video_section(info["video_module"], scope="complement"))
    video = _video(info["video_module"])
    course = _base_course(course_id, "MAC APS · Complément · " + info["title"],
                          "Préparer les ateliers et les échanges avec le formateur ; cette consultation ne valide aucune pratique.",
                          sections, "complement", sum(s["planned_minutes"] for s in sections),
                          [video[key] for key in ("src", "poster", "captions")])
    course.update(reference_stage_minutes=info["reference_stage_minutes"], timed_objectives=[])
    return course


def load_bundled_course(course_id, version=None):
    if version == LEGACY_VERSION:
        return _with_reviewed_media(copy.deepcopy(_legacy()["courses"].get(course_id)))
    if version not in (None, VERSION):
        return None
    if course_id in curriculum_ids():
        return _with_reviewed_media(copy.deepcopy(_course(course_id[-2:])))
    if course_id in {row["id"] for row in _plan()["complements"]}:
        return _with_reviewed_media(copy.deepcopy(_complement(course_id)))
    # Calls without a version to old-only IDs retain their original meaning.
    if version is None and course_id in curriculum_ids(LEGACY_VERSION):
        return _with_reviewed_media(copy.deepcopy(_legacy()["courses"][course_id]))
    return None


def bundled_asset(course_id, version, name):
    course = load_bundled_course(course_id, version)
    if not course or name not in course["assets"]:
        return None
    root = (ROOT / "assets").resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def complement_manifest():
    modules = []
    for row in _plan()["complements"]:
        course = _complement(row["id"])
        lessons = [section for section in course["sections"] if section["activities"][0].get("macaps", {}).get("kind") == "lesson"]
        video = _video(row["video_module"])
        modules.append({**copy.deepcopy(row), "version": VERSION, "pedagogical_scope": "complement",
                        "planned_minutes": course["planned_minutes"], "required_minutes": 0,
                        "lesson_count": len(lessons), "has_video": True, "video_minutes": round(video["duration_seconds"] / 60, 1),
                        "lessons": [{"ref": s["id"], "title": s["title"], "activity": s["activities"][0]["id"],
                                     "mode": "presentiel_preparation", "pedagogical_scope": "complement"} for s in lessons]})
    return {"version": VERSION, "pedagogical_scope": "complement", "principal_minutes": 0,
            "required_minutes": 0, "modules": modules, "lesson_count": sum(m["lesson_count"] for m in modules),
            "video_count": len(modules), "notice": "Compléments pour préparer le présentiel, hors des 14 heures du parcours principal. Les gestes et mises en situation sont encadrés et évalués par le formateur."}


def curriculum_manifest(version=None):
    if version == LEGACY_VERSION:
        return copy.deepcopy(_legacy()["manifest"])
    if version not in (None, VERSION):
        return None
    modules = []
    for number, info in MODULES.items():
        course = _course(number)
        lessons = [lesson for lesson in _lessons() if lesson["module"] == number]
        video = _video(number) if number in ("02", "03") else None
        objectives = [row for row in legal_objectives() if row["module"] == number]
        modules.append({**copy.deepcopy(info), "number": number, "id": course["id"], "version": VERSION,
                        "pedagogical_scope": "principal", "planned_minutes": course["planned_minutes"],
                        "required_minutes": course["required_minutes"], "lesson_count": len(lessons),
                        "question_count": len(_exams()["modules"][number]), "exam_id": course["mock_exam_id"],
                        "objective_count": len(objectives), "objectives": objectives,
                        "objective_question_count": sum(len(_exams()["objectives"][row["id"]]) for row in objectives),
                        "has_video": bool(video), "video_minutes": round(video["duration_seconds"] / 60, 1) if video else 0,
                        "required_section_ids": [s["id"] for s in course["sections"]],
                        "lessons": [{"ref": lesson["id"], "title": lesson["title"], "activity": lesson["id"] + "-cours",
                                     "mode": lesson["mode"], "objective_id": lesson["objective_id"]} for lesson in lessons]})
    return {"version": VERSION, "training_label": "MAC APS", "preview_only": False, "notice": NOTICE,
            "pedagogical_scope": "principal", "modules": modules, "lesson_count": len(_lessons()),
            "case_count": len(_lessons()), "inline_question_count": sum(len(l["quiz"]) for l in _lessons()),
            "decision_count": sum(len(l["scenario"]["steps"]) for l in _lessons()),
            "objective_count": len(legal_objectives()),
            "objective_question_count": sum(len(rows) for rows in _exams()["objectives"].values()),
            "exam_question_count": sum(len(rows) for rows in _exams()["modules"].values()) + len(_exams()["final"]),
            "activity_count": sum(_course(number)["counts"]["activities"] for number in MODULES),
            "planned_minutes": TOTAL_MINUTES, "required_minutes": TOTAL_MINUTES,
            "video_count": 2, "video_minutes": round(sum(_video(n)["duration_seconds"] for n in ("02", "03")) / 60, 1),
            "final_exam_id": "macaps-final", "complements": complement_manifest(),
            "regulatory_review": regulatory_review()}


def load_exam(exam_id, version):
    if version == LEGACY_VERSION:
        return copy.deepcopy(_legacy()["exams"].get(exam_id))
    if version != VERSION:
        return None
    if exam_id == "macaps-final":
        questions = _exams()["final"]
        title = "MAC APS · Bilan du parcours de révision de 14 heures · 100 questions"
    elif exam_id in {"macaps-module-" + n for n in PRINCIPAL_MODULE_NUMBERS}:
        number = exam_id[-2:]
        questions = _exams()["modules"][number]
        title = "MAC APS · " + MODULES[number]["title"] + " · 30 questions"
    else:
        return None
    questions = copy.deepcopy(questions)
    for question in questions:
        number = question["module"]
        question["module"] = "Module " + number + " · " + MODULES[number]["title"]
        question.setdefault("sources", [question.get("source_url") or _plan()["source_url"]])
    return {"id": exam_id, "version": VERSION, "title": title, "training_label": "MAC APS", "pass_percent": 80,
            "pedagogical_scope": "principal", "required_course_ids": curriculum_ids(),
            "notice": "Évaluation pédagogique du support de révision de 14 heures. Seuil : 80 %. Ce résultat ne vaut ni attestation réglementaire de stage MAC APS, ni certification SST.",
            "questions": questions}
