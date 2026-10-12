"""Read-only public MAC APS specimen, isolated from orders and native tracking.

Only the selected first lesson, three selected practice questions and a separate
86-second video excerpt are projected publicly. This module never authenticates
a learner, opens a tracking database, persists progress or calls a provider.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from urllib.parse import urlsplit

from flask import Response, abort, make_response, render_template, request, send_file

from elearning_native import mac_aps

PUBLIC_ENDPOINTS = {"manuals_shop." + name for name in (
    "mac_aps_demo", "mac_aps_demo_lesson", "mac_aps_demo_media", "mac_aps_demo_certificate",
)}
SAMPLE_COURSE = "academy-macaps-02"
SAMPLE_LESSON = "macaps-02-01"
PERSON = {"id": "specimen-mac-aps-person", "first_name": "Camille", "last_name": "Martin", "email": "camille.martin@example.test"}
PARTNER = {"id": "specimen-mac-aps-centre", "name": "Centre de formation exemple"}
ORDER = {"id": "specimen-mac-aps-access", "course_code": "mac-aps", "group_name": "Groupe MAC APS · Démonstration"}
MEDIA_ROOT = Path(__file__).parent / "static" / "elearning-demo" / "mac-aps"
MEDIA = {
    "video": ("republique-extrait.mp4", "video/mp4"),
    "affiche": ("republique-poster.jpg", "image/jpeg"),
    "sous-titres": ("republique-extrait.vtt", "text/vtt"),
}


def duration(seconds):
    hours, minutes = divmod(max(0, int(seconds)) // 60, 60)
    return f"{hours:02d} h {minutes:02d} min"


def demo_report():
    """A sequential 50% specimen with completed modules and honest time budgets."""
    manifest = mac_aps.curriculum_manifest()
    source = [(item, mac_aps.load_bundled_course(item["id"], item["version"])) for item in manifest["modules"]]
    total = sum(course["counts"]["activities"] for _, course in source)
    remaining_activities = total // 2
    modules, connections, exams = [], [], []
    day = dt.date(2026, 10, 1)
    for item, course in source:
        activities = [activity for section in course["sections"] for activity in section["activities"]]
        count = len(activities)
        required = int(item["planned_minutes"]) * 60
        completed = min(remaining_activities, count)
        remaining_activities -= completed
        done = {activity["id"]: activity for activity in activities[:completed]}
        scored = [activity for activity in activities if activity.get("answer_groups")]
        assessed = sum(activity["id"] in done for activity in scored)
        timed_objectives = []
        for objective in course["timed_objectives"]:
            objective_ids = set(objective["activity_ids"])
            complete = objective_ids <= done.keys()
            seconds = int(objective["required_seconds"])
            active = seconds if complete else min(seconds, sum(int(done[aid]["planned_minutes"]) * 60 for aid in objective_ids & done.keys()))
            timed_objectives.append({"id": objective["id"], "title": objective["title"],
                                     "active_seconds": active, "required_seconds": seconds,
                                     "active_time_label": duration(active), "required_time_label": duration(seconds),
                                     "duration_met": active >= seconds, "complete": complete,
                                     "status_label": "Terminé" if complete else "En cours" if active else "À suivre"})
        active = sum(objective["active_seconds"] for objective in timed_objectives)
        complete = completed == count and active >= required
        status = "complete" if complete else "progress" if completed else "pending"
        modules.append({
            "id": item["id"], "version": item["version"], "number": item["number"],
            "display_number": f"{len(modules) + 1:02d}",
            "title": item["title"], "available": True, "hours": required / 3600,
            "total_activities": count, "completed_activities": completed,
            "progress_percent": round(completed / count * 100), "active_seconds": active,
            "active_time_label": duration(active), "required_time_label": duration(required),
            "module_complete": complete, "status": status, "status_label": "Terminé" if complete else "En cours" if completed else "À suivre",
            "sections_complete": completed == count, "exam": None,
            "score_percent": round(assessed / len(scored) * 100, 2) if scored else 100,
            "assessment_summary": {"first_attempt_score_percent": 100 if assessed else None,
                                   "assessed_items": assessed, "attempt_count": assessed,
                                   "first_attempt_correct": assessed, "incorrect_attempt_count": 0, "items_to_review": 0},
            "timed_objectives": timed_objectives,
        })
        remaining = active
        while remaining:
            seconds = min(7200, remaining)
            start = dt.datetime.combine(day, dt.time(9))
            end = start + dt.timedelta(seconds=seconds)
            connections.append({"module": item["title"], "course_id": item["id"], "course_version": item["version"],
                                "date": day.strftime("%d/%m/%Y"),
                                "started": start.strftime("%H:%M"), "ended": end.strftime("%H:%M"),
                                "started_at_label": start.strftime("%d/%m/%Y à %H:%M"),
                                "last_seen_label": end.strftime("%d/%m/%Y à %H:%M"),
                                "ended_at_label": end.strftime("%d/%m/%Y à %H:%M"), "status_label": "Clôturée",
                                "credited_seconds": seconds, "active_time_label": duration(seconds)})
            remaining -= seconds
            day += dt.timedelta(days=1)
        if complete:
            question_count = int(item["question_count"])
            correct = question_count - (3 if not exams else 4)
            exam = {"id": item["exam_id"], "title": item["title"], "module": item["title"],
                    "version": item["version"], "date_label": (day - dt.timedelta(days=1)).strftime("%d/%m/%Y"),
                    "score": correct, "total": question_count, "percent": round(correct / question_count * 100), "passed": True}
            exams.append(exam)
            modules[-1]["exam"] = exam
    completed = sum(m["completed_activities"] for m in modules)
    active = sum(m["active_seconds"] for m in modules)
    required = sum(int(m["hours"] * 3600) for m in modules)
    return {
        "available": True, "complete": False, "modules": modules,
        "versions": sorted({m["version"] for m in modules}),
        "connections": list(reversed(connections)), "exams": list(reversed(exams)), "final_exam": None,
        "completed_modules": sum(module["module_complete"] for module in modules), "total_modules": len(modules),
        "completed_activities": completed, "total_activities": total,
        "progress_percent": round(completed / total * 100),
        "active_seconds": active, "active_time_label": duration(active),
        "required_time_label": duration(required), "status_label": "En cours",
        "started_at_label": "01/10/2026 à 09:00",
        "updated_at_label": connections[-1]["date"] + " à " + connections[-1]["ended"],
        "generated_at_label": "Exemple pédagogique · octobre 2026",
    }


def module_details(module):
    """A public list of titles and fictional statuses, with no assessment bank."""
    course = mac_aps.load_bundled_course(module["id"], module["version"])
    remaining = module["completed_activities"]
    sections = []
    current_assigned = False
    for section in course["sections"]:
        activities = []
        for activity in section["activities"]:
            current = remaining == 0 and not current_assigned and module["status"] == "progress"
            current_assigned = current_assigned or current
            activities.append({"title": activity["title"], "completed": remaining > 0, "current": current})
            remaining = max(0, remaining - 1)
        sections.append({"title": section["title"], "activities": activities})
    return sections


def sample_lesson():
    course = mac_aps.load_bundled_course(SAMPLE_COURSE, mac_aps.VERSION)
    section = next(s for s in course["sections"] if s["id"] == SAMPLE_LESSON)
    reading = next(a["macaps"] for a in section["activities"] if a.get("macaps", {}).get("kind") == "lesson")
    quiz = next(a for a in section["activities"] if a.get("macaps", {}).get("kind") == "quiz")
    groups = {group["id"]: group for group in quiz["answer_groups"]}
    explanations = quiz["explanation"].split("\n\n")
    questions = []
    for index, question in enumerate(quiz["macaps"]["questions"][:3]):
        answers = groups[question["id"]]["answers"]
        questions.append({
            "id": "sample-" + str(index + 1), "prompt": question["prompt"],
            "options": [{"id": option["id"], "text": option["text"]} for option in question["options"]],
            "answer": next(answer["id"] for answer in answers if answer.get("is_correct")),
            "explanation": explanations[index].split(". ", 1)[-1],
        })
    # No full course or future exercise data is handed to the public template.
    source_names = {"www.legifrance.gouv.fr": "Légifrance", "www.elysee.fr": "Élysée", "www.defenseurdesdroits.fr": "Défenseur des droits"}
    return {"title": reading["title"], "objective": reading["objective"],
            "sections": [{"heading": item["heading"], "paragraphs": item["paragraphs"]} for item in reading["sections"][:3]],
            "table": reading.get("table"),
            "sources": [{"url": url, "label": source_names.get(urlsplit(url).hostname, urlsplit(url).hostname)}
                        for url in reading.get("source_urls", [])],
            "questions": questions}


def register_routes(host, bp):
    def response(body):
        result = make_response(body)
        result.headers.update({"Cache-Control": "no-store, private", "X-Robots-Tag": "noindex, nofollow, noarchive",
                               "X-Content-Type-Options": "nosniff", "Permissions-Policy": "display-capture=()",
                               "Referrer-Policy": "same-origin"})
        return result

    @bp.get("/e-learning/demo/mac-aps")
    def mac_aps_demo():
        view = request.args.get("view", "stagiaire")
        if view not in {"stagiaire", "suivi"}:
            abort(404)
        report = demo_report()
        selected = next((m for m in report["modules"] if m["number"] == request.args.get("module", "02")), None)
        if selected is None:
            abort(404)
        return response(render_template("manuals/mac_aps_demo.html", view=view, report=report, person=PERSON,
                                        selected=selected, sections=module_details(selected) if view == "suivi" else []))

    @bp.get("/e-learning/demo/mac-aps/cours")
    def mac_aps_demo_lesson():
        captions = (MEDIA_ROOT / MEDIA["sous-titres"][0]).read_text(encoding="utf-8")
        transcript = " ".join(" ".join(cue.splitlines()[1:]) for cue in captions.split("\n\n") if " --> " in cue)
        return response(render_template("manuals/mac_aps_demo_lesson.html", view="cours", lesson=sample_lesson(), transcript=transcript))

    @bp.get("/e-learning/demo/mac-aps/media/<name>")
    def mac_aps_demo_media(name):
        if name not in MEDIA:
            abort(404)
        filename, mimetype = MEDIA[name]
        path = MEDIA_ROOT / filename
        if not path.is_file():
            abort(404)
        return response(send_file(path, mimetype=mimetype, conditional=True))

    @bp.get("/e-learning/demo/mac-aps/releve.pdf")
    def mac_aps_demo_certificate():
        from elearning_reporting import certificate_pdf
        order = {**ORDER, "modules": [{"course_id": m["id"], "course_version": m["version"],
                                      "title": m["title"], "required_minutes": m["planned_minutes"]}
                                     for m in mac_aps.curriculum_manifest()["modules"]]}
        return response(Response(certificate_pdf(demo_report(), PARTNER, order, PERSON, specimen=True),
                                 mimetype="application/pdf", headers={"Content-Disposition": 'attachment; filename="specimen-suivi-MAC-APS.pdf"'}))
