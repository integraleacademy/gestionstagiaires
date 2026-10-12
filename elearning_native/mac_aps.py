"""MAC APS learning resources, independent of the APS initial curriculum.

The reference stage lasts 34 hours. These digital resources do not award stage
hours or an official MAC/SST certificate. Course completion and active time use
the existing native learner store; opening the catalogue never assigns a course.
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
VERSION = "20261012-macaps-v1"
NOTICE = (
    "Ce parcours numérique accompagne votre formation MAC APS. Les gestes et les "
    "mises en situation se travaillent avec un formateur. L’attestation réglementaire "
    "de stage est délivrée par votre organisme après vérification de toutes les conditions."
)
MODULES = {
    "01": {"title": "Gestes élémentaires de premiers secours", "regulatory_minutes": 420,
           "objective": "Actualiser les priorités de protection, d’examen et d’alerte, et préparer la pratique encadrée.", "icon": "secours"},
    "02": {"title": "Principes de la République", "regulatory_minutes": 180,
           "objective": "Appliquer les libertés, l’égalité, la laïcité et le respect de la dignité dans les missions de sécurité.", "icon": "republique"},
    "03": {"title": "Cadre juridique et déontologie", "regulatory_minutes": 240,
           "objective": "Actualiser les limites d’intervention et justifier une décision professionnelle à partir des faits.", "icon": "droit"},
    "04": {"title": "Gestion des conflits et filtrage", "regulatory_minutes": 420,
           "objective": "Prévenir l’escalade, adapter sa communication et organiser des contrôles d’accès proportionnés.", "icon": "conflits"},
    "05": {"title": "Prévention des risques terroristes", "regulatory_minutes": 780,
           "objective": "Détecter une situation préoccupante, se protéger, alerter et faciliter l’intervention des secours.", "icon": "prevention"},
}


def is_training(value):
    if isinstance(value, dict):
        value = value.get("training_type", "")
    normalized = re.sub(r"[\W_]+", " ", str(value or "").upper()).strip()
    return normalized.startswith("MAC APS") or normalized.startswith("APS MAC")


@lru_cache(maxsize=1)
def _lessons():
    return json.loads((ROOT / "lessons.json").read_text(encoding="utf-8"))["lessons"]


@lru_cache(maxsize=1)
def _exams():
    return json.loads((ROOT / "exams.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _media():
    path = ROOT / "media_manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"videos": {}}


@lru_cache(maxsize=1)
def regulatory_review():
    return json.loads((ROOT / "regulatory_review.json").read_text(encoding="utf-8"))


def curriculum_ids():
    return ["academy-macaps-" + number for number in MODULES]


def _video(number):
    video = _media().get("videos", {}).get(number)
    return copy.deepcopy(video) if video else None


def _question_activity(lesson, suffix, title, questions, kind, **payload):
    """Group related choices; answer keys stay in the server-side course only."""
    fields, groups, public_questions = [], [], []
    for number, question in enumerate(questions, 1):
        group_id = lesson["id"] + "-" + suffix + "-" + str(number)
        options = "".join(
            '<option value="%s">%s</option>' % (html.escape(option["id"], quote=True), html.escape(option["text"]))
            for option in question["options"]
        )
        fields.append(
            '<div class="mac-question-group"><p><strong>%s. %s</strong></p>'
            '<select class="native-elearning-blank" data-group-id="%s" aria-label="%s">'
            '<option value="">Choisissez une réponse…</option>%s</select></div>'
            % (number, html.escape(question["prompt"]), group_id,
               html.escape(question["prompt"], quote=True), options)
        )
        groups.append({"id": group_id, "mode": "choice", "answers": [
            {**option, "is_correct": option["id"] == question["answer"]} for option in question["options"]
        ]})
        public_questions.append({"id": group_id, "prompt": question["prompt"], "options": copy.deepcopy(question["options"])})
    return {
        "id": lesson["id"] + "-" + suffix, "title": title, "type": "question", "question_type": "fill_blank",
        "scored": True, "planned_minutes": 7 if kind == "application" else 5,
        "prompt": "Choisissez une réponse à chaque étape, puis validez pour lire les explications." if kind == "application" else "Répondez aux trois questions du chapitre, puis consultez la correction.",
        "prompt_html": "".join(fields), "answer_groups": groups,
        "explanation": "\n\n".join(
            "%s. %s — %s" % (index, next(o["text"] for o in q["options"] if o["id"] == q["answer"]), q["explanation"])
            for index, q in enumerate(questions, 1)
        ),
        "macaps": {"kind": kind, "ref": lesson["id"], "mode": lesson["mode"],
                   "objective": lesson["objective"], "question_count": len(questions), "questions": public_questions, **payload},
    }


def _section(lesson):
    common = {key: copy.deepcopy(lesson[key]) for key in ("id", "module", "title", "objective", "mode", "source_urls")}
    common["ref"] = lesson["id"]
    def content(suffix, label, kind, minutes, **payload):
        return {"id": lesson["id"] + "-" + suffix, "title": label + " · " + lesson["title"],
                "type": "content", "scored": False, "blocks": [], "planned_minutes": minutes,
                "macaps": {**common, "kind": kind, **copy.deepcopy(payload)}}
    lesson_content = {key: lesson[key] for key in ("sections", "table", "flow") if key in lesson}
    scenario = lesson["scenario"]
    return {"id": lesson["id"], "title": lesson["id"][-5:].replace("-", ".") + " · " + lesson["title"],
            "activities": [
                content("cours", "Comprendre", "lesson", 10, **lesson_content),
                _question_activity(lesson, "application", "Appliquer · " + scenario["title"], scenario["steps"], "application",
                                   example=lesson["example"], situation=scenario["intro"]),
                _question_activity(lesson, "quiz", "QCM · " + lesson["title"], lesson["quiz"], "quiz"),
                content("retenir", "À retenir", "recap", 3, takeaways=lesson["takeaways"]),
            ]}


@lru_cache(maxsize=5)
def _course(number):
    info = MODULES[number]
    lessons = [lesson for lesson in _lessons() if lesson["module"] == number]
    sections = [_section(lesson) for lesson in lessons]
    video = _video(number)
    assets = []
    if video:
        video.update(id="macaps-" + number + "-video", title="Synthèse · " + info["title"], required=True,
                     lesson_explainer=True, default_playback_rate=1, allowed_playback_rates=[0.85, 0.9, 1])
        assets = [video[key] for key in ("src", "poster", "captions")]
        sections.append({"id": "macaps-" + number + "-synthese", "title": "Le module en vidéo",
                         "activities": [{"id": "macaps-" + number + "-video", "title": "Synthèse vidéo · " + info["title"],
                                         "type": "content", "scored": False,
                                         "planned_minutes": math.ceil(video["duration_seconds"] / 60),
                                         "macaps": {"kind": "video", "mode": "revision_theorique", "module": number},
                                         "blocks": [{"id": video["id"], "type": "video", "html": "", "children": [], "video": video}]}]})
    activities = [activity for section in sections for activity in section["activities"]]
    planned = sum(activity["planned_minutes"] for activity in activities)
    return {"id": "academy-macaps-" + number, "version": VERSION, "format_version": 1,
            "title": "MAC APS · " + number + " · " + info["title"], "training_label": "MAC APS", "preview_only": False,
            "description": info["objective"], "planned_minutes": planned, "required_minutes": planned,
            "regulatory_minutes": info["regulatory_minutes"],
            "source": {"type": "academy-macaps", "sha256": hashlib.sha256((ROOT / "lessons.json").read_bytes()).hexdigest()},
            "regulation": {"scope": "pedagogical_support", "automatic_stage_credit": False, "automatic_certificate": False,
                           "reference": "Arrêté du 27 février 2017 · article 4", "notice": NOTICE},
            "mock_exam_id": "macaps-module-" + number,
            "assets": assets, "import_warnings": [], "introduction": [],
            "theme": {"main_color": "#164d78", "button_color": "#176dad", "text_color": "#152f45"},
            "settings": {"mastery_score": 80, "require_correct_answers": True, "force_navigation": True},
            "sections": sections, "activity_order": [activity["id"] for activity in activities],
            "counts": {"sections": len(sections), "activities": len(activities), "scored_activities": sum(a["scored"] for a in activities),
                       "assets": len(assets), "required_videos": int(bool(video))}}


def load_bundled_course(course_id, version=None):
    if course_id not in curriculum_ids() or version not in (None, VERSION):
        return None
    return copy.deepcopy(_course(course_id[-2:]))


def bundled_asset(course_id, version, name):
    course = load_bundled_course(course_id, version)
    if not course or name not in course["assets"]:
        return None
    root = (ROOT / "assets").resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def curriculum_manifest():
    modules = []
    for number, info in MODULES.items():
        course = _course(number)
        lessons = [lesson for lesson in _lessons() if lesson["module"] == number]
        video = _video(number)
        modules.append({**info, "number": number, "id": course["id"], "version": VERSION,
                        "planned_minutes": course["planned_minutes"], "lesson_count": len(lessons),
                        "question_count": len(_exams()["modules"][number]), "exam_id": course["mock_exam_id"],
                        "has_video": bool(video), "video_minutes": round(video["duration_seconds"] / 60, 1) if video else 0,
                        "lessons": [{"ref": lesson["id"], "title": lesson["title"], "activity": lesson["id"] + "-cours", "mode": lesson["mode"]} for lesson in lessons]})
    return {"version": VERSION, "training_label": "MAC APS", "preview_only": False, "notice": NOTICE,
            "modules": modules, "lesson_count": len(_lessons()), "case_count": len(_lessons()),
            "inline_question_count": sum(len(l["quiz"]) for l in _lessons()),
            "decision_count": sum(len(l["scenario"]["steps"]) for l in _lessons()),
            "exam_question_count": sum(len(rows) for rows in _exams()["modules"].values()) + len(_exams()["final"]),
            "activity_count": sum(_course(number)["counts"]["activities"] for number in MODULES),
            "planned_minutes": sum(module["planned_minutes"] for module in modules),
            "video_count": sum(module["has_video"] for module in modules),
            "video_minutes": round(sum((_video(n) or {}).get("duration_seconds", 0) for n in MODULES) / 60, 1),
            "final_exam_id": "macaps-final", "regulatory_review": copy.deepcopy(regulatory_review())}


def load_exam(exam_id, version):
    if version != VERSION:
        return None
    if exam_id == "macaps-final":
        questions = _exams()["final"]
        title = "MAC APS · Examen blanc transversal · 100 questions"
    elif re.fullmatch(r"macaps-module-0[1-5]", str(exam_id)):
        number = exam_id[-2:]
        questions = _exams()["modules"][number]
        title = "MAC APS · " + MODULES[number]["title"] + " · 30 questions"
    else:
        return None
    questions = copy.deepcopy(questions)
    for question in questions:
        number = str(question.get("module") or (exam_id[-2:] if exam_id != "macaps-final" else "05"))
        if number not in MODULES:
            match = re.search(r"0[1-5]", number)
            number = match[0] if match else "05"
        question["module"] = "Module " + number + " · " + MODULES[number]["title"]
        question.setdefault("sources", [question.get("source_url") or regulatory_review()["sources"][0]["url"]])
        question.setdefault("lesson_refs", [lesson["id"] for lesson in _lessons() if lesson["module"] == number])
    return {"id": exam_id, "version": VERSION, "title": title, "training_label": "MAC APS", "pass_percent": 80,
            "notice": "Examen blanc d’entraînement. Seuil pédagogique : 80 %. Ce résultat ne vaut ni attestation de stage MAC APS, ni certification SST.",
            "questions": questions}
