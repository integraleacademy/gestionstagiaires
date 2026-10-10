"""Public APS specimen: deterministic fictional data, no orders or tracking writes.

Only one explicitly selected lesson and its two illustrations are public. The
normal native learner access, course assets and answer banks remain protected.
"""
from __future__ import annotations

import datetime as dt
from flask import Response, abort, make_response, render_template, request, send_file

from elearning_native.academy import bundled_asset, curriculum_manifest, load_bundled_course


PUBLIC_ENDPOINTS = {"manuals_shop." + name for name in (
    "elearning_demo", "elearning_demo_lesson", "elearning_demo_asset", "elearning_demo_certificate",
)}
SAMPLE_COURSE = "academy-aps62-01"
SAMPLE_ASSETS = {"scene": "media/aps62/v2/module-01.webp", "schema": "media/aps62/repere-02.01.webp"}
PERSON = {"id": "specimen-person", "first_name": "Camille", "last_name": "Martin", "email": "camille.martin@example.test"}
PARTNER = {"name": "Centre de formation exemple"}
ORDER = {"id": "specimen-access", "course_code": "aps", "group_name": "Groupe APS · Démonstration"}


def duration(seconds):
    minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d} h {minutes:02d} min"


def demo_report():
    """Generate a coherent 50% specimen entirely from shipped curriculum metadata."""
    manifest = curriculum_manifest()
    total = sum(int(m["activities"]) for m in manifest["modules"])
    remaining_activities = total // 2
    required_seconds = sum(int(m["hours"] * 3600) for m in manifest["modules"])
    remaining_seconds = required_seconds // 2
    modules, connections, exams = [], [], []
    day = dt.date(2026, 9, 1)
    for item in manifest["modules"]:
        count, required = int(item["activities"]), int(item["hours"] * 3600)
        completed, active = min(remaining_activities, count), min(remaining_seconds, required)
        remaining_activities -= completed
        remaining_seconds -= active
        complete = completed == count and active == required
        module = {"id": item["id"], "number": item["number"], "version": item["version"],
                  "title": item["title"], "available": True, "hours": item["hours"],
                  "total_activities": count, "completed_activities": completed,
                  "progress_percent": round(completed / count * 100), "active_seconds": active,
                  "active_time_label": duration(active), "required_time_label": duration(required),
                  "module_complete": complete, "status": "complete" if complete else "progress" if completed or active else "pending",
                  "status_label": "Terminé" if complete else "En cours" if completed or active else "Non commencé"}
        modules.append(module)
        remaining_connection = active
        while remaining_connection:
            seconds = min(7200, remaining_connection)
            start = dt.datetime.combine(day, dt.time(8, 30))
            end = start + dt.timedelta(seconds=seconds)
            connections.append({"module": item["title"], "date": day.strftime("%d/%m/%Y"),
                                "started": start.strftime("%H:%M"), "ended": end.strftime("%H:%M"),
                                "credited_seconds": seconds, "active_time_label": duration(seconds)})
            remaining_connection -= seconds
            day += dt.timedelta(days=1)
        if complete:
            exams.append({"module": item["title"], "score": 90 if len(exams) % 2 == 0 else 87,
                          "questions": 30, "date": (day - dt.timedelta(days=1)).strftime("%d/%m/%Y"), "status": "Réussi"})
    return {"available": True, "complete": False, "modules": modules, "connections": list(reversed(connections)),
            "exams": list(reversed(exams)), "completed_modules": sum(m["module_complete"] for m in modules),
            "total_modules": len(modules), "completed_activities": total // 2, "total_activities": total,
            "progress_percent": round((total // 2) / total * 100),
            "active_seconds": required_seconds // 2, "active_time_label": duration(required_seconds // 2),
            "required_time_label": duration(required_seconds), "status_label": "En cours",
            "started_at_label": "01/09/2026 à 08:30", "updated_at_label": connections[-1]["date"] + " à " + connections[-1]["ended"],
            "generated_at_label": "Exemple pédagogique · septembre 2026"}


def module_details(module):
    """Only activity titles and fictional status, never lesson bodies or answers."""
    course = load_bundled_course(module["id"], module["version"])
    remaining = module["completed_activities"]
    sections = []
    current_assigned = False
    for section in course["sections"]:
        activities = []
        for activity in section["activities"]:
            completed = remaining > 0
            remaining = max(0, remaining - 1)
            current = not completed and not current_assigned and module["status"] == "progress"
            current_assigned = current_assigned or current
            activities.append({"title": activity["title"], "completed": completed, "current": current})
        sections.append({"title": section["title"], "activities": activities})
    return sections


def sample_lesson():
    course = load_bundled_course(SAMPLE_COURSE)
    academy = course["sections"][0]["activities"][0]["academy"]
    # Deliberate field allowlist: no full course, assessment keys, or hidden banks.
    return {"title": academy["title"], "case": academy["case"], "reason": academy["reason"],
            "decision": academy["decision"], "pitfall": academy["pitfall"],
            "paragraphs": academy["lessons"][0]["paragraphs"], "flow": academy["flow"],
            "visual_board": academy["visual_board"], "image_alt": academy.get("image_alt", "Situation professionnelle APS")}


def register_routes(host, bp):
    def response(body):
        result = make_response(body)
        result.headers.update({"Cache-Control": "no-store, private", "X-Robots-Tag": "noindex, nofollow, noarchive",
                               "X-Content-Type-Options": "nosniff", "Permissions-Policy": "display-capture=()",
                               "Referrer-Policy": "same-origin"})
        return result

    @bp.get("/e-learning/demo/aps")
    def elearning_demo():
        view = request.args.get("view", "stagiaire")
        if view not in {"stagiaire", "suivi"}:
            abort(404)
        report = demo_report()
        default = next((m for m in report["modules"] if m["status"] == "progress"), report["modules"][0])
        selected = next((m for m in report["modules"] if m["number"] == request.args.get("module", default["number"])), None)
        if selected is None:
            abort(404)
        return response(render_template("manuals/elearning_demo.html", view=view, report=report, person=PERSON,
                                        selected=selected, sections=module_details(selected) if view == "suivi" else []))

    @bp.get("/e-learning/demo/aps/cours")
    def elearning_demo_lesson():
        return response(render_template("manuals/elearning_demo_lesson.html", lesson=sample_lesson(), view="cours"))

    @bp.get("/e-learning/demo/aps/illustration/<name>")
    def elearning_demo_asset(name):
        if name not in SAMPLE_ASSETS:
            abort(404)
        course = load_bundled_course(SAMPLE_COURSE)
        path = bundled_asset(SAMPLE_COURSE, course["version"], SAMPLE_ASSETS[name])
        if path is None:
            abort(404)
        return response(send_file(path, mimetype="image/webp", conditional=True))

    @bp.get("/e-learning/demo/aps/attestation.pdf")
    def elearning_demo_certificate():
        from elearning_reporting import certificate_pdf
        return response(Response(certificate_pdf(demo_report(), PARTNER, ORDER, PERSON, specimen=True),
                                 mimetype="application/pdf", headers={"Content-Disposition": 'attachment; filename="specimen-attestation-APS.pdf"'}))
