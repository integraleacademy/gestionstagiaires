"""Read-only, tenant-scoped reporting for purchased native learning spaces.

The purchase's module versions and virtual session are the source of truth. A
report never opens the learner's session, creates activity, or changes progress.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from flask import Response, abort, url_for
from werkzeug.utils import secure_filename

import elearning_orders as learning
from elearning_programmes import PROGRAMMES, programme_download
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.paths import project_course, project_progress, required_activity_order
from elearning_native.store import NativeElearningStore
from elearning_native.aps_final_time import final_time
from elearning_native.exams import module_exam_activity_id
from elearning_exam_reporting import activity_exam_seconds, recorded_seconds
from elearning_native.vtc_105_migration import read_transition_session, lineage_versions
from elearning_native.vtc_cma import learner_attempt_summaries
from elearning_native.module_signatures import MAC_APS_NOTICE


CUSTOMER_ENDPOINTS = {"manuals_shop." + name for name in (
    "elearning_progress", "elearning_progress_certificate", "elearning_progress_connections",
    "elearning_progress_programme", "elearning_progress_exam_copy",
)}
STATUS_LABELS = {"not_started": "Non commencé", "in_progress": "En cours",
                 "awaiting_time": "Temps de suivi à compléter", "passed": "Terminé",
                 "failed": "Terminé · résultats à revoir", "unavailable": "Suivi indisponible"}


def time_label(seconds):
    value = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d} h {minutes:02d} min {seconds:02d} s"


def date_label(value):
    if not value:
        return "—"
    try:
        date = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=dt.timezone.utc)
        return date.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M")
    except (ValueError, TypeError):
        return "—"


class ProgressReader:
    def __init__(self, host):
        root = Path(host.PERSIST_DIR).resolve() / "native_elearning"
        self.catalog = CourseCatalog(root)
        self.database_path = root / "tracking.sqlite3"
        self.courses = {}
        self.ai_path = root / "production_ai.sqlite3"

    def course(self, module):
        # Missing version must not silently report against today's curriculum.
        key = (str(module.get("course_id") or ""), str(module.get("course_version") or ""))
        if not all(key):
            raise CourseImportError("La version du module n’est pas disponible.")
        if key not in self.courses:
            self.courses[key] = self.catalog.load_course(*key)
        return project_course(self.courses[key], module)

    def rows(self, table, session_id, learner_id):
        """Use existing history only: no schema creation, no learner mutation."""
        if not self.database_path.is_file():
            return []
        queries = {
            "progress": """SELECT * FROM learner_course_progress
                WHERE session_id = ? AND trainee_id = ?""",
            "connections": """SELECT course_id, course_version, created_at, last_seen_at,
                ended_at, credited_seconds, status FROM tracking_sessions
                WHERE session_id = ? AND trainee_id = ? ORDER BY created_at DESC, id DESC""",
            "exams": """SELECT exam_id, version, attempt_id, submitted_at, result_json FROM aps_exam_attempts
                WHERE session_id = ? AND trainee_id = ? ORDER BY submitted_at DESC, attempt_id DESC""",
        }
        table_name = {"progress": "learner_course_progress", "connections": "tracking_sessions", "exams": "aps_exam_attempts"}[table]
        with sqlite3.connect(self.database_path.as_uri() + "?mode=ro", uri=True, timeout=15) as db:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
            records = [dict(row) for row in db.execute(queries[table], (session_id, learner_id))] if exists else []
        if table == "progress":
            for row in records:
                # Optional tracking ledgers were introduced progressively.
                # Reading historical reports must not migrate learner data.
                for column in ("video_progress_json", "assessment_diagnostics_json",
                               "activity_seconds_json", "lesson_seconds_json", "aps_workload_json"):
                    row.setdefault(column, "{}")
            return [NativeElearningStore._serialize_progress(row) for row in records]
        return records

    def report(self, order, person, *, detailed=True):
        is_mac_aps = order["course_code"] == "mac-aps"
        course_label = "MAC APS" if is_mac_aps else order["course_code"].upper()
        session_id, learner_id = "el-" + order["id"], str(person["id"])
        session_view = read_transition_session({
            'id': session_id, 'training_type': order['course_code'].upper(),
            'aps_native_path_title': 'Mon parcours ' + order['course_code'].upper(),
            'aps_native_modules': order.get('modules', []),
        }, person, self.database_path)
        raw_rows = self.rows("progress", session_id, learner_id)
        by_key = {(r["course_id"], r["course_version"]): r for r in raw_rows}
        modules, complement_modules, exam_keys, course_titles, course_scopes, exam_scopes, exam_titles = [], [], set(), {}, {}, {}, {}
        exam_catalogue = {}
        total = completed = active = required = finished = optional_total = 0
        starts, updates = [], []
        for assignment in session_view.get('aps_native_modules', []):
            assigned_key = (str(assignment.get("course_id") or ""), str(assignment.get("course_version") or ""))
            complementary = is_mac_aps and assigned_key[0].startswith("academy-macaps-complement-")
            scope = "complement" if complementary else "principal"
            target_modules = complement_modules if complementary else modules
            if all(assigned_key):
                # Historical connections remain evidence even if the purchased
                # course files are temporarily unavailable. Do not broaden the
                # allowlist to other editions of the same module.
                course_titles[assigned_key] = assignment.get("title") or assigned_key[0]
                course_scopes[assigned_key] = scope
            module = {"title": assignment.get("title") or assignment.get("course_id") or "Module",
                      "course_id": assigned_key[0], "pedagogical_scope": scope,
                      "version": assignment.get("course_version") or "", "available": False,
                      "status_label": "Suivi indisponible", "sections": [], "module_complete": False,
                      "required_seconds": int(assignment.get("required_minutes") or 0) * 60,
                      "required_time_label": time_label(int(assignment.get("required_minutes") or 0) * 60)}
            try:
                course = self.course(assignment)
            except (CourseImportError, OSError):
                recorded = by_key.get(assigned_key, {})
                recorded_active_seconds = max(0, float(recorded.get("active_seconds") or 0))
                if not complementary:
                    active += recorded_active_seconds
                module.update(active_seconds=recorded_active_seconds, active_time_label=time_label(recorded_active_seconds))
                if recorded.get("started_at") and not complementary:
                    starts.append(recorded["started_at"])
                if recorded.get("updated_at") and not complementary:
                    updates.append(recorded["updated_at"])
                if not complementary:
                    required += module["required_seconds"]
                target_modules.append(module)
                continue
            key = (course["id"], course["version"])
            course_titles[key] = course["title"]
            course_scopes[key] = scope
            for historical_version in lineage_versions(session_view, course['id']):
                course_titles[(course['id'], historical_version)] = course['title']
                course_scopes[(course['id'], historical_version)] = scope
            progress = project_progress(by_key.get(key, {}), course)
            access = {"session_id": session_id, "trainee_id": learner_id,
                      "course_id": key[0], "course_version": key[1]}
            ids = set(progress["completed_activity_ids"])
            required_ids = set(required_activity_order(course))
            required_completed = progress["completed_required_activities"]
            required_total = progress["required_activity_count"]
            activities = [a for section in course["sections"] for a in section.get("activities", [])]
            questions = [a for a in activities if a.get("scored") and a["id"] in required_ids]
            answered = sum(a["id"] in progress.get("answers", {}) for a in questions)
            if not complementary:
                total += required_total
                completed += required_completed
                optional_total += progress["optional_activity_count"]
                active += progress["active_seconds"]
                required += progress["required_seconds"]
                finished += int(progress["module_complete"])
            if progress.get("started_at") and not complementary:
                starts.append(progress["started_at"])
            if progress.get("updated_at") and not complementary:
                updates.append(progress["updated_at"])
            module.update(title=course["title"], version=course["version"], available=True,
                          progress_percent=progress["progress_percent"], active_seconds=progress["active_seconds"],
                          active_time_label=time_label(progress["active_seconds"]),
                          required_seconds=progress["required_seconds"],
                          required_time_label=time_label(progress["required_seconds"]),
                          remaining_time_label=time_label(progress["remaining_seconds"]),
                          module_complete=progress["module_complete"], status=progress["status"],
                          status_label=STATUS_LABELS.get(progress["status"], "En cours"),
                          completed_activities=required_completed, total_activities=required_total,
                          optional_activity_count=progress["optional_activity_count"],
                          score_percent=progress["score_percent"] if answered else None,
                          assessment_summary=progress.get("assessment_summary") or {},
                          assessment_diagnostics=progress.get("assessment_diagnostics") or {},
                          timed_objectives=[{**objective, "active_time_label": time_label(objective.get("active_seconds")),
                                             "required_time_label": time_label(objective.get("required_seconds")),
                                             "remaining_time_label": time_label(objective.get("remaining_seconds"))}
                                            for objective in progress.get("timed_objectives") or []],
                          objectives_duration_met=progress.get("objectives_duration_met"),
                          assessment_attempts=self.assessment_attempts(access, course) if detailed else [],
                          answered_questions=answered, total_questions=len(questions),
                          completed_videos=progress["completed_video_count"], total_videos=progress["required_video_count"],
                          started_at_label=date_label(progress.get("started_at")), updated_at_label=date_label(progress.get("updated_at")))
            if course.get("mock_exam_id"):
                for historical_version in lineage_versions(session_view, course['id']):
                    exam_key = (course["mock_exam_id"], historical_version)
                    exam_keys.add(exam_key)
                    exam_scopes[exam_key] = scope
                    exam_titles[exam_key] = ("Examen blanc MAC APS - " if is_mac_aps else "Examen blanc - ") + course["title"]
                    if not complementary:
                        exam_catalogue[exam_key] = {"id": exam_key[0], "version": exam_key[1],
                            "title": course["title"],
                            "active_seconds": activity_exam_seconds(by_key.get((course['id'], historical_version), {}), module_exam_activity_id(course))}
            if detailed:
                for section in course["sections"]:
                    rows = []
                    for activity in section.get("activities", []):
                        answer = progress.get("answers", {}).get(activity["id"], {})
                        rows.append({"title": activity.get("title") or "Activité", "completed": activity["id"] in ids,
                                     "optional": activity["id"] not in required_ids,
                                     "current": activity["id"] == progress.get("current_activity_id"),
                                     "answer_label": ("Réponse correcte" if answer.get("correct") else "À revoir") if activity.get("scored") and answer else ""})
                        if activity.get("production") and isinstance(answer.get("production_answers"), dict):
                            production = activity["production"]
                            rows[-1]["production"] = {
                                "draft": bool(answer.get("production_draft")),
                                "ai_feedback": answer.get("production_ai_feedback"),
                                "first_responses": [{"label": field["label"], "text": answer.get("production_first_answers", {}).get(field["id"], "")} for field in production["response_fields"]],
                                "responses": [{"label": field["label"], "text": answer["production_answers"].get(field["id"], "")}
                                              for field in production["response_fields"]],
                                "review": [{"label": criterion["label"], "needs_help": answer.get("production_self_review", {}).get(criterion["id"]) == "needs_help"}
                                           for criterion in production["rubric"] if answer.get("production_self_review", {}).get(criterion["id"]) in ("checked", "needs_help")],
                            }
                            # VTC corrections use the tracked production attempt
                            # projection above; APS analyses retain their own
                            # history and grading schema in production_ai.sqlite3.
                            if activity.get("vtc", {}).get("kind") != "production" and self.ai_path.is_file():
                                from elearning_native.production_ai import read_analyses
                                rows[-1]["production"]["ai"] = read_analyses(self.ai_path, access, activity["id"])
                    required_rows = [row for row in rows if not row["optional"]]
                    module["sections"].append({"title": section.get("title") or "Séquence", "activities": rows,
                                               "objective_id": section.get("objective_id"),
                                               "required_seconds": section.get("required_seconds"),
                                               "completed": sum(a["completed"] for a in required_rows),
                                               "total": len(required_rows),
                                               "optional_activity_count": len(rows) - len(required_rows)})
            target_modules.append(module)
        module_active = active
        aps_final = final_time(session_view.get('aps_native_modules', []), raw_rows) if order['course_code'] == 'aps' else None
        if aps_final:
            active += aps_final['active_seconds']
            aps_final['active_time_label'] = time_label(aps_final['active_seconds'])
            final_tracking_key = (aps_final['course_id'], aps_final['version'])
            course_titles[final_tracking_key] = aps_final['title']
            course_scopes[final_tracking_key] = 'principal'
            if aps_final.get('started_at'):
                starts.append(aps_final['started_at'])
            if aps_final.get('updated_at'):
                updates.append(aps_final['updated_at'])
        versions = {m["version"] for m in modules if m["version"]}
        if len(versions) == 1:
            final_id = "macaps-final" if is_mac_aps else "vtc-final" if order["course_code"] == "vtc" else "final"
            # Keep final attempts from a proven VTC predecessor edition, just
            # like module attempts; never include unrelated curriculum versions.
            final_versions = set.intersection(*(set(lineage_versions(session_view, m["course_id"])) for m in modules))
            for final_version in sorted(final_versions - {""}):
                final_key = (final_id, final_version)
                exam_keys.add(final_key)
                exam_scopes[final_key] = "principal"
                exam_titles[final_key] = "Examen blanc final " + course_label
                exam_catalogue[final_key] = {"id": final_id, "version": final_key[1],
                    "title": exam_titles[final_key], "is_final": True,
                    "active_seconds": recorded_seconds(by_key.get((aps_final['course_id'], final_version), {}).get('active_seconds')) if aps_final else None}
        complete = bool(modules) and finished == len(modules)
        available = bool(modules) and all(m["available"] for m in modules)
        report = {"available": available, "modules": modules, "completed_modules": finished, "total_modules": len(modules),
                  "course_label": course_label, "course_code": order["course_code"],
                  "versions": sorted({m["version"] for m in modules if m["version"]}),
                  "pedagogical_scope": "pedagogical_support" if is_mac_aps else "learning_record",
                  "regulatory_notice": MAC_APS_NOTICE if is_mac_aps else "",
                  "complement_modules": complement_modules,
                  "complement_active_time_label": time_label(sum(m.get("active_seconds", 0) for m in complement_modules)),
                  "complement_required_time_label": time_label(sum(m.get("required_seconds", 0) for m in complement_modules)),
                  "completed_activities": completed, "total_activities": total,
                  "optional_activity_count": optional_total,
                  "progress_percent": round(completed / total * 100, 1) if total and available else None,
                  "active_seconds": round(active, 2), "active_time_label": time_label(active),
                  "module_active_seconds": round(module_active, 2), "module_active_time_label": time_label(module_active),
                  "final_exam_time": aps_final,
                  "required_seconds": required, "required_time_label": time_label(required), "complete": complete,
                  "status_label": "Parcours terminé" if complete else "Suivi partiellement indisponible" if not available else "En cours" if starts else "Non commencé",
                  "started_at_label": date_label(min(starts)) if starts else "Pas encore commencé",
                  "updated_at_label": date_label(max(updates)) if updates else "Aucune activité enregistrée",
                  "generated_at_label": date_label(dt.datetime.now(dt.timezone.utc).isoformat()),
                  "connections": [], "complement_connections": [], "exams": [], "complement_exams": [], "cma_attempts": [],
                  "exam_catalogue": list(exam_catalogue.values()),
                  "final_exams": [dict(entry, submitted=False) for entry in exam_catalogue.values()
                                  if entry.get("is_final") and entry["version"] in versions]}
        if detailed:
            if order['course_code'] == 'vtc':
                report['cma_attempts'] = learner_attempt_summaries(self.database_path, session_id, learner_id)
            for connection in self.rows("connections", session_id, learner_id):
                key = (connection["course_id"], connection["course_version"])
                if key not in course_titles:
                    continue
                destination = "complement_connections" if course_scopes.get(key) == "complement" else "connections"
                report[destination].append({"module": course_titles[key], "course_id": key[0], "version": key[1],
                    "pedagogical_scope": course_scopes.get(key, "principal"),
                    "started_at_label": date_label(connection["created_at"]),
                    "last_seen_label": date_label(connection["last_seen_at"]),
                    "ended_at_label": date_label(connection["ended_at"]),
                    "active_time_label": time_label(connection["credited_seconds"]),
                    "credited_seconds": round(float(connection["credited_seconds"] or 0), 2),
                    "status_label": "Clôturée" if connection["ended_at"] else "Dernière activité enregistrée"})
            for attempt in self.rows("exams", session_id, learner_id):
                if (attempt["exam_id"], attempt["version"]) not in exam_keys:
                    continue
                try:
                    result = json.loads(attempt["result_json"])
                    row = {k: result[k] for k in ("score", "total", "percent", "passed")}
                except (ValueError, KeyError, TypeError):
                    continue
                exam_key = (attempt["exam_id"], attempt["version"])
                title = exam_titles.get(exam_key) or ("Examen blanc final" if attempt["exam_id"] in {"final", "vtc-final"} else "Examen blanc " + attempt["exam_id"].replace("vtc-", "").replace("module-", "module "))
                destination = "complement_exams" if exam_scopes.get(exam_key) == "complement" else "exams"
                report[destination].append({**row, "id": attempt["exam_id"], "version": attempt["version"],
                    "title": title, "attempt_id": attempt["attempt_id"], "submitted_at": attempt["submitted_at"],
                    "is_final": bool(exam_catalogue.get(exam_key, {}).get("is_final")),
                    "pass_percent": result.get("pass_percent"), "date_label": date_label(attempt["submitted_at"])})
                for final in report["final_exams"]:
                    if (final["id"], final["version"]) == exam_key:
                        final["submitted"] = True
        return report

    def exam_attempt(self, order, person, exam_id, version, attempt_id):
        """Authorize the purchased exam edition before reading a saved copy."""
        from elearning_exam_pdf import read_stored_attempt

        report = self.report(order, person, detailed=False)
        exam = next((item for item in report["exam_catalogue"]
                     if (item["id"], item["version"]) == (exam_id, version)), None)
        if exam is None:
            return None
        attempt = read_stored_attempt(self.database_path, "el-" + order["id"], person["id"],
                                      exam_id, version, attempt_id)
        return {**attempt, "title": exam["title"]} if attempt else None

    def assessment_attempts(self, access, course):
        """Return the purchased module's recorded checks without creating a DB."""
        if not self.database_path.is_file():
            return []
        from elearning_native.assessment import describe_history, history_for
        selected = set(course["activity_order"])
        with sqlite3.connect(self.database_path.as_uri() + "?mode=ro", uri=True, timeout=15) as db:
            db.row_factory = sqlite3.Row
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learner_assessment_attempts'").fetchone():
                return []
            return describe_history(course, [row for row in history_for(db, access) if row["activity_id"] in selected])


def group_progress(host, group):
    """Compact mapping consumed by the group/individual roster template."""
    reader, result = None, {}
    orders = {o["id"]: o for o in group.get("orders", [])}
    for row in group.get("learners", []):
        order = orders.get(row.get("order_id"))
        if not order or not learning.entitled(order):
            continue
        person = next((p for p in order.get("learners", []) if p.get("id") == row.get("id") and p.get("activated_at")), None)
        if not person:
            continue
        reader = reader or ProgressReader(host)
        report = reader.report(order, person, detailed=False)
        result[row["id"]] = {k: report[k] for k in (
            "available", "progress_percent", "active_time_label", "completed_modules", "total_modules", "status_label")}
    return result


def certificate_pdf(report, partner, order, person, *, logo_path=None, specimen=False):
    """Issue the centre's follow-up record from real tracking evidence.

    ``logo_path`` is an optional trusted local Path resolved by the tenant's
    profile helper, never a request parameter or a remote URL. ``specimen`` is
    used only by the fictional public demonstration, not by the customer route.
    """
    from reportlab.lib import colors
    from decimal import Decimal, InvalidOperation
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, LongTable, HRFlowable, CondPageBreak
    from elearning_pdf_components import CompletionBadge, TimeProgress, module_duration, report_duration
    from elearning_pdf_components import compact_duration
    from elearning_exam_reporting import exam_groups, number_label

    output = io.BytesIO()
    centre_name = str(partner.get("name") or partner.get("centre") or "Organisme de formation").strip()
    is_mac_aps = order["course_code"] == "mac-aps"
    course_label = "MAC APS" if is_mac_aps else order["course_code"].upper()
    document_title = "Relevé de suivi numérique MAC APS" if is_mac_aps else "Attestation de suivi e-learning"
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title=("SPECIMEN - " if specimen else "") + document_title,
                            author=centre_name)
    styles = {name: ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
              textColor=colors.HexColor(color), spaceAfter=after, alignment=TA_LEFT) for name, font, size, leading, color, after in (
        ("brand", "Helvetica-Bold", 10, 13, "#19324b", 3),
        ("title", "Helvetica-Bold", 22, 26, "#19324b", 5),
        ("heading", "Helvetica-Bold", 11, 14, "#19324b", 5),
        ("body", "Helvetica", 8.5, 12, "#263d55", 4),
        ("small", "Helvetica", 7.2, 10, "#62768b", 2),
        ("cell", "Helvetica", 7.5, 10, "#263d55", 0),
        ("th", "Helvetica-Bold", 7, 10, "#ffffff", 0))}
    # Embed the same readable typeface for every training path and PDF viewer.
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_root = Path("/usr/share/fonts/truetype/dejavu")
    if (font_root / "DejaVuSans.ttf").is_file() and (font_root / "DejaVuSans-Bold.ttf").is_file():
        if "LearningReport" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("LearningReport", str(font_root / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("LearningReportBold", str(font_root / "DejaVuSans-Bold.ttf")))
        for style in styles.values():
            style.fontName = "LearningReportBold" if style.fontName == "Helvetica-Bold" else "LearningReport"
    regular_font, bold_font = styles["body"].fontName, styles["heading"].fontName
    styles["title"].keepWithNext = True
    def p(value, style="body"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])
    issuer = [p(centre_name, "brand")]
    address = ", ".join(str(partner.get(key) or "").strip() for key in ("address", "address_extra") if str(partner.get(key) or "").strip())
    city = " ".join(str(partner.get(key) or "").strip() for key in ("postal_code", "city") if str(partner.get(key) or "").strip())
    contact = " · ".join(str(partner.get(key) or "").strip() for key in ("email", "phone") if str(partner.get(key) or "").strip())
    for line in (address, city, contact, "SIRET : " + str(partner["siret"]) if partner.get("siret") else ""):
        if line:
            issuer.append(p(line, "small"))
    logo = None
    if isinstance(logo_path, Path):
        # Decode local image bytes ourselves. ReportLab never receives a URL or
        # a filesystem string that could trigger its remote image loader.
        from PIL import Image as PillowImage, UnidentifiedImageError
        try:
            if logo_path.is_file() and logo_path.stat().st_size <= 5 * 1024 * 1024:
                with logo_path.open("rb") as source:
                    image_data = source.read(5 * 1024 * 1024 + 1)
                with PillowImage.open(io.BytesIO(image_data)) as source_image:
                    width, height = source_image.size
                    if source_image.format in {"PNG", "JPEG", "WEBP"} and 0 < width * height <= 16_000_000:
                        normalized = source_image.convert("RGBA")
                        normalized.thumbnail((1200, 600))
                        image_buffer = io.BytesIO()
                        normalized.save(image_buffer, format="PNG")
                        image_buffer.seek(0)
                        scale = min(36 * mm / width, 15 * mm / height)
                        logo = Image(image_buffer, width=width * scale, height=height * scale)
                        logo.hAlign = "RIGHT"
        except (OSError, ValueError, UnidentifiedImageError, PillowImage.DecompressionBombError):
            logo = None
    if logo is not None:
        heading = Table([[issuer, logo]], colWidths=[136 * mm, 38 * mm], hAlign="LEFT")
        heading.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        story = [heading]
    else:
        story = issuer
    story.extend([Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=.6, color=colors.HexColor("#dbe6ef")), Spacer(1, 4 * mm)])
    if specimen:
        story.extend([p("SPECIMEN - DONNÉES FICTIVES", "heading"),
                      p("Exemple de document. Ce spécimen ne prouve aucun suivi de formation et ne constitue pas une attestation délivrée à un stagiaire.", "small")])
    name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
    status = (CompletionBadge("Parcours numérique terminé" if is_mac_aps else "Parcours e-learning terminé", font=bold_font, size=9, width=320)
              if report["complete"] else p("Relevé de suivi partiel - parcours non terminé", "body"))
    identity_table = Table([[
        [p("STAGIAIRE", "small"), p(name, "heading"), p(person.get("email", ""), "small")],
        [p("FORMATION · " + course_label, "small"), p(learning.COURSES[order['course_code']]['title']),
         p("Groupe / accès : " + (order.get("group_name") or "Accès individuel"), "small")]
    ]], colWidths=[80 * mm, 94 * mm], hAlign="LEFT")
    identity_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story.extend([p("Relevé de suivi numérique" if is_mac_aps else "Attestation de suivi", "title"),
                  status, Spacer(1, 3 * mm), identity_table, Spacer(1, 3 * mm)])
    if is_mac_aps:
        versions = report.get("versions") or sorted({m.get("version", "") for m in report["modules"] if m.get("version")})
        story.extend([p("Édition(s) suivie(s) : " + (", ".join(versions) or "Non renseignée"), "small"),
                      p(MAC_APS_NOTICE, "small"), Spacer(1, 3 * mm)])
    duration = report_duration(report)
    exams = exam_groups(report)
    metrics = [[
        [p("TEMPS SUIVI / DURÉE PRÉVUE", "small"),
         TimeProgress(duration, width=96 * mm, font=regular_font, bold=bold_font, large=True)],
        [p("MODULES TERMINÉS", "small"), p(f"{report['completed_modules']} / {report['total_modules']}", "heading"),
         p("ACTIVITÉS TERMINÉES", "small"), p(f"{report['completed_activities']} / {report['total_activities']}" if report["available"] else "Données partielles", "heading")]
    ]]
    box = Table(metrics, colWidths=[109 * mm, 65 * mm], hAlign="LEFT")
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4fb")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([box, Spacer(1, 3 * mm),
                  p("Temps actif enregistré : " + report["active_time_label"] + " · Durée prévue : " + report["required_time_label"], "small"),
                  p(f"Première activité : {report['started_at_label']} · Dernière activité : {report['updated_at_label']}", "small"),
                  Spacer(1, 3 * mm)])
    if not exams and not report.get("cma_attempts"):
        story.append(p("Examens blancs : aucune tentative ni durée enregistrée.", "small"))
    headers = ("MODULE / ÉDITION" if is_mac_aps else "MODULE", "TEMPS SUIVI / " + ("CIBLE" if is_mac_aps else "REQUIS"), "ACTIVITÉS", "ÉTAT")
    table_rows = [[p(value, "th") for value in headers]]
    for module in report["modules"]:
        activity_label = (f"{module['completed_activities']} / {module['total_activities']}"
                          if "completed_activities" in module and "total_activities" in module
                          else f"{module.get('progress_percent', 0):g} %")
        completed_module = bool(module.get("available") and module.get("module_complete") and module.get("status") in {"passed", "complete"})
        state = (CompletionBadge(font=bold_font, width=26 * mm) if completed_module else
                 p("Activités à terminer" if module.get("status") == "in_progress" and module_duration(module)["fraction"] == 1 else
                   "Temps à compléter" if module.get("status") == "awaiting_time" else module["status_label"], "cell"))
        row = [p(module["title"] + ("\n" + (module.get("version") or "Édition inconnue") if is_mac_aps else ""), "cell"),
               TimeProgress(module_duration(module), width=51 * mm, font=regular_font, bold=bold_font),
               p(activity_label if module["available"] else "Indisponible", "cell"), state]
        table_rows.append(row)
    table = LongTable(table_rows, colWidths=[w * mm for w in [64, 55, 24, 31]], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173858")),
                              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
                              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                              ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor("#e2eaf1"))]))
    story.extend([CondPageBreak(55), p("Détail du parcours", "heading"), table])
    # References and legal notes are printed with the integral connection annex
    # below, so a duplicate block cannot create a nearly empty summary page.

    def detail_table(rows, widths, padding=7):
        value = LongTable(rows, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
        value.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173858")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), padding), ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]))
        return value

    if is_mac_aps:
        identity = f"Organisme : {centre_name}\nStagiaire : {name} · {person.get('email', '')}"
        story.extend([PageBreak(), p("Objectifs et temps enregistrés", "title"), p(identity, "small"),
                      p("Chaque objectif conserve son propre temps actif. Les excédents d'un objectif et les compléments ne remplacent pas le temps prévu pour un autre objectif.", "small")])
        for module in report["modules"]:
            story.extend([Spacer(1, 3 * mm), p(module["title"], "heading"),
                          p("Édition : " + (module.get("version") or "Non renseignée"), "small")])
            objectives = module.get("timed_objectives") or []
            if objectives:
                rows = [[p(value, "th") for value in ("OBJECTIF", "TEMPS ACTIF", "DURÉE CIBLE", "ÉTAT")]]
                for objective in objectives:
                    rows.append([p(objective["title"], "cell"), p(time_label(objective.get("active_seconds")), "cell"),
                                 p(time_label(objective.get("required_seconds")), "cell"),
                                 p("Terminé" if objective.get("complete") else "Activités à compléter" if objective.get("duration_met") else "Temps à compléter", "cell")])
                story.append(detail_table(rows, [76, 34, 34, 30]))
            else:
                story.append(p("Aucun relevé de temps par objectif n'est disponible pour cette édition. Aucun temps antérieur n'est reconstitué.", "small"))
        story.extend([PageBreak(), p("Résultats pédagogiques MAC APS", "title"), p(identity, "small"),
                      p("Les examens blancs sont des entraînements distincts du suivi des activités. Leurs résultats ne constituent pas une validation réglementaire du stage.", "small")])
        quiz_rows = [[p(value, "th") for value in ("MODULE", "PREMIER ESSAI", "SCORE GLOBAL APRÈS REPRISES", "ESSAIS ENREGISTRÉS")]]
        for module in report["modules"]:
            summary = module.get("assessment_summary") or {}
            first = summary.get("first_attempt_score_percent")
            score = module.get("score_percent")
            quiz_rows.append([p(module["title"], "cell"), p(f"{first:g} %" if isinstance(first, (int, float)) else "Non disponible", "cell"),
                              p(f"{score:g} %" if isinstance(score, (int, float)) else "Non disponible", "cell"),
                              p(str(summary.get("attempt_count", 0)), "cell")])
        story.extend([p("Questionnaires du parcours", "heading"),
                      p("Premier essai : activités réussies dès la première réponse parmi les activités déjà essayées. "
                        "Score global après reprises : activités actuellement réussies parmi toutes les activités évaluables du module, "
                        "y compris celles restant à réaliser. Les deux pourcentages ont donc des bases différentes lorsque le module est en cours.", "small"),
                      detail_table(quiz_rows, [71, 32, 35, 36])])

    if exams or report.get("cma_attempts"):
        exam_identity = f"Organisme : {centre_name}\nStagiaire : {name} · {person.get('email', '')}"
        story.extend([PageBreak(), p("Relevé des examens blancs", "title"), p(exam_identity, "small"), Spacer(1, 3 * mm)])
        if exams:
            story.append(p("Temps actif cumulé par examen, questions et corrigé compris.", "small"))
            rows = [[p(value, "th") for value in ("EXAMEN / DERNIÈRE TENTATIVE", "TEMPS ACTIF CUMULÉ", "ESSAIS", "DERNIÈRE NOTE", "RÉSULTAT")]]
            for exam in exams:
                latest = exam["latest"]
                title = exam["title"] + ("\nÉdition : " + exam["version"] if is_mac_aps and exam["version"] else "")
                rows.append([p(title + "\n" + latest["date_label"], "cell"),
                    p(compact_duration(exam["active_seconds"]) if exam["active_seconds"] is not None else "Non enregistré", "cell"),
                    p(len(exam["attempts"]), "cell"), p(latest["score_label"], "cell"), p(latest["result_label"], "cell")])
            story.append(detail_table(rows, [62, 30, 16, 32, 34], padding=5))
            repeated = [exam for exam in exams if len(exam["attempts"]) > 1]
            if repeated:
                story.extend([Spacer(1, 5 * mm), CondPageBreak(65), p("Historique des examens repassés", "heading")])
                rows = [[p(value, "th") for value in ("EXAMEN", "ESSAI", "DATE", "NOTE", "SEUIL", "RÉSULTAT")]]
                for exam in repeated:
                    for attempt in exam["attempts"]:
                        rows.append([p(exam["title"], "cell"), p(attempt["number"], "cell"), p(attempt["date_label"], "cell"),
                                     p(attempt["score_label"], "cell"), p(attempt["pass_label"], "cell"), p(attempt["result_label"], "cell")])
                story.append(detail_table(rows, [47, 13, 34, 28, 20, 32], padding=5))
        if report.get("cma_attempts"):
            story.extend([Spacer(1, 4 * mm), CondPageBreak(65), p("Examens blancs CMA VTC", "heading")])
            rows = [[p(value, "th") for value in ("DATE DE DÉBUT", "TEMPS D’EXAMEN", "ÉPREUVES REMISES", "MOYENNE", "RÉSULTAT")]]
            for attempt in reversed(report["cma_attempts"]):
                result = ("Réussi" if attempt.get("passed") is True else "À retravailler" if attempt.get("passed") is False else
                          "Données indisponibles" if attempt.get("status") == "unavailable" else "En cours / correction en attente")
                average = attempt.get("weighted_average")
                rows.append([p(date_label(attempt.get("created_at")), "cell"),
                    p(compact_duration(attempt.get("exam_seconds")) if attempt.get("status") != "unavailable" else "Non enregistré", "cell"),
                    p(f"{attempt.get('submitted_subjects', 0)} / {len(attempt.get('subjects') or [])}" if attempt.get("status") != "unavailable" else "Indisponible", "cell"),
                    p(number_label(average) + " / 20" if average is not None else "En attente", "cell"), p(result, "cell")])
            story.append(detail_table(rows, [35, 30, 30, 30, 49]))

    # Keep the integral connection evidence in the same PDF as the attestation.
    # Table headers identify the centre and learner again on every annex page.
    # A last heartbeat is deliberately never relabelled as a disconnection.
    connections = report.get("connections") or []
    story.extend([PageBreak(), p("Relevé détaillé des connexions", "title"),
                  p(f"{len(connections)} connexion{'s' if len(connections) != 1 else ''} enregistrée{'s' if len(connections) != 1 else ''}", "heading"),
                  p("Tous les horaires sont exprimés dans le fuseau Europe/Paris. Le temps actif correspond au travail comptabilisé par la plateforme, et non à la durée écoulée entre le début et la fin d’une connexion.", "small"),
                  p("La dernière activité est le dernier signal enregistré. Une fin non enregistrée ne signifie pas que le stagiaire est toujours connecté.", "small"),
                  Spacer(1, 4 * mm)])
    specimen_identity = "SPECIMEN - DONNÉES FICTIVES\n" if specimen else ""
    connection_identity = p(f"{specimen_identity}Organisme : {centre_name}\nStagiaire : {name} · {person.get('email', '')}\n"
                            f"Parcours : {course_label} · {order.get('group_name') or 'Accès individuel'}", "small")

    def connection_seconds(connection):
        try:
            seconds = Decimal(str(connection.get("credited_seconds") or 0))
            return seconds if seconds.is_finite() and seconds >= 0 else Decimal(0)
        except (InvalidOperation, ValueError, TypeError):
            return Decimal(0)

    def connection_time(seconds):
        # Preserve hundredths when recorded so line durations and total agree.
        seconds = seconds.quantize(Decimal("0.01"))
        if seconds == int(seconds):
            return time_label(seconds)
        hours, remaining = divmod(seconds, Decimal(3600))
        minutes, remaining = divmod(remaining, Decimal(60))
        remainder_label = f"{remaining:05.2f}".replace(".", ",")
        return f"{int(hours):02d} h {int(minutes):02d} min {remainder_label} s"

    total_connection_seconds = sum((connection_seconds(row) for row in connections), Decimal(0))
    if not connections:
        story.extend([connection_identity, Spacer(1, 3 * mm),
                      p("Aucune connexion au parcours n’est enregistrée à la date d’édition."),
                      p("Total du temps actif dans ce relevé : 00 h 00 min 00 s", "heading")])
    else:
        connection_rows = [[connection_identity, "", "", "", "", ""],
                           [p(value, "th") for value in ("MODULE", "DÉBUT", "DERNIÈRE ACTIVITÉ", "FIN ENREGISTRÉE", "ÉTAT", "TEMPS ACTIF")]]
        for index, connection in enumerate(connections, 1):
            end = str(connection.get("ended_at_label") or "").strip()
            has_end = bool(end and end not in {"—", "-", "Non enregistrée", "Non renseignée"})
            connection_rows.append([
                p(f"{index}. {connection.get('module') or 'Module'}", "cell"),
                p(connection.get("started_at_label") or "Non renseigné", "cell"),
                p(connection.get("last_seen_label") or "Non renseignée", "cell"),
                p(end if has_end else "Non enregistrée", "cell"),
                p("Clôturée" if has_end else "Fin non enregistrée", "cell"),
                p(connection_time(connection_seconds(connection)), "cell"),
            ])
        connection_rows.append([p("TOTAL DU TEMPS ACTIF DANS CE RELEVÉ", "cell"), "", "", "", "",
                                p(connection_time(total_connection_seconds), "cell")])
        connection_table = LongTable(connection_rows,
            colWidths=[43 * mm, 29 * mm, 29 * mm, 29 * mm, 20 * mm, 24 * mm],
            repeatRows=2, hAlign="LEFT")
        connection_table.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf4fb")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#173858")),
            ("ROWBACKGROUNDS", (0, 2), (-1, -2), [colors.white, colors.HexColor("#f3f6fa")]),
            ("SPAN", (0, -1), (4, -1)), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dceaf6")),
            ("NOSPLIT", (0, -2), (-1, -1)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(connection_table)
    story.extend([Spacer(1, 5 * mm),
                  p(f"Relevé édité le {report['generated_at_label']} (heure de Paris).", "small"),
                  p("Données fictives de démonstration : ce document n’atteste d’aucune formation suivie." if specimen else
                    f"Relevé édité pour {centre_name} à partir des traces de sa plateforme. Ce document ne constitue ni une attestation de stage MAC APS ni une attestation SST." if is_mac_aps else
                    f"Attestation éditée pour {centre_name} à partir des traces de sa plateforme e-learning. Elle décrit le suivi pédagogique constaté à la date d’édition ; elle ne vaut ni diplôme ni certification professionnelle.", "small"),
                  p(f"Référence de commande : {order['id']} · Identifiant du stagiaire : {person['id']}", "small")])

    if is_mac_aps and report.get("complement_modules"):
        story.extend([PageBreak(), p("Compléments pédagogiques", "title"), p(identity, "small"),
                      p("Ces ressources et leurs temps sont séparés du parcours principal. Ils ne sont pas ajoutés à sa durée cible ni à son avancement.", "small")])
        rows = [[p(value, "th") for value in ("COMPLÉMENT / ÉDITION", "TEMPS ACTIF", "DURÉE PRÉVUE", "ÉTAT")]]
        for module in report["complement_modules"]:
            rows.append([p(module["title"] + "\n" + module.get("version", ""), "cell"),
                         p(module.get("active_time_label", "Non disponible"), "cell"),
                         p(module.get("required_time_label", "Non disponible"), "cell"), p(module["status_label"], "cell")])
        story.extend([detail_table(rows, [72, 35, 35, 32]), Spacer(1, 5 * mm), p("Connexions aux compléments", "heading")])
        supplementary = report.get("complement_connections") or []
        if supplementary:
            rows = [[p(value, "th") for value in ("COMPLÉMENT", "DÉBUT / DERNIÈRE ACTIVITÉ", "FIN ENREGISTRÉE", "TEMPS ACTIF")]]
            for connection in supplementary:
                rows.append([p(connection["module"], "cell"), p(connection["started_at_label"] + "\n" + connection["last_seen_label"], "cell"),
                             p(connection["ended_at_label"] if connection["ended_at_label"] != "—" else "Non enregistrée", "cell"),
                             p(connection_time(connection_seconds(connection)), "cell")])
            story.append(detail_table(rows, [55, 48, 38, 33]))
            story.append(p("Temps actif des compléments : " + connection_time(sum((connection_seconds(row) for row in supplementary), Decimal(0))), "small"))
        else:
            story.append(p("Aucune connexion aux compléments n'est enregistrée."))

    def footer(canvas, document):
        canvas.saveState()
        if specimen:
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#e1e8ef"))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(40)
            canvas.setFont("Helvetica-Bold", 66)
            canvas.drawCentredString(0, 0, "SPECIMEN")
            canvas.setFont("Helvetica-Bold", 16)
            canvas.drawCentredString(0, -28, "DONNÉES FICTIVES")
            canvas.restoreState()
        canvas.setStrokeColor(colors.HexColor("#d6e1ec"))
        canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
        canvas.setFont(regular_font, 7)
        canvas.setFillColor(colors.HexColor("#526579"))
        footer_name = ("SPECIMEN - " if specimen else "") + centre_name
        while canvas.stringWidth(footer_name + " - Suivi e-learning", regular_font, 7) > 145 * mm:
            footer_name = footer_name[:-2].rstrip()
        canvas.drawString(18 * mm, 10 * mm, footer_name + " - Suivi e-learning")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def register_routes(host, bp, *, page, customer, partner_data):
    def context(oid, learner_id):
        if host._is_super_admin_session() and not host.session.get("assist_partner_id"):
            data = host.load_data()
            order = next((o for o in data.get("manual_orders", []) if learning.is_order(o) and o.get("id") == oid), None)
            if not order:
                abort(404)
            partner = host._partner_or_404(data, order["partner_id"])
        else:
            data, partner = partner_data()
        order = next((o for o in data.get("manual_orders", []) if learning.is_order(o) and o.get("id") == oid
                      and o.get("partner_id") == partner["id"]), None)
        if not order or not learning.entitled(order):
            abort(404)
        person = next((p for p in order.get("learners", []) if p.get("id") == learner_id and p.get("activated_at")), None)
        if not person:
            abort(404)
        group = next((g for g in data.get("manual_orders", []) if g.get("order_type") == "elearning_group"
                      and g.get("partner_id") == partner["id"] and g.get("id") == order.get("group_id")), None)
        return partner, order, person, group

    base = "/admin/organisme/e-learning/commandes/<oid>/stagiaires/<learner_id>/suivi"

    @bp.get(base)
    @customer
    def elearning_progress(oid, learner_id):
        partner, order, person, group = context(oid, learner_id)
        report = ProgressReader(host).report(order, person)
        return page("elearning_progress.html", partner=partner, order=order, person=person, group=group, report=report,
                    course=learning.COURSES[order["course_code"]], staff=host._is_super_admin_session() and not host.session.get("assist_partner_id"))

    @bp.get(base + "/examens/<exam_id>/<version>/<attempt_id>.pdf")
    @customer
    def elearning_progress_exam_copy(oid, learner_id, exam_id, version, attempt_id):
        from elearning_exam_pdf import exam_attempt_pdf
        from organisme_profile import logo_path

        partner, order, person, _ = context(oid, learner_id)
        attempt = ProgressReader(host).exam_attempt(order, person, exam_id, version, attempt_id)
        if attempt is None:
            abort(404)
        filename = secure_filename(f"copie-examen-{exam_id}-{person.get('last_name', '')}-{person.get('first_name', '')}-{attempt_id}.pdf")
        return Response(exam_attempt_pdf(attempt, partner, order, person, logo_path=logo_path(host, partner)),
                        mimetype="application/pdf", headers={
                            "Content-Disposition": f'inline; filename="{filename}"',
                            "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                            "Referrer-Policy": "no-referrer"})

    @bp.get(base + "/programme.pdf")
    @customer
    def elearning_progress_programme(oid, learner_id):
        _, order, _, _ = context(oid, learner_id)
        return programme_download(order["course_code"])

    @bp.get(base + "/attestation.pdf")
    @customer
    def elearning_progress_certificate(oid, learner_id):
        from organisme_profile import logo_path

        partner, order, person, _ = context(oid, learner_id)
        report = ProgressReader(host).report(order, person, detailed=True)
        prefix = "releve-suivi-mac-aps" if order["course_code"] == "mac-aps" else "attestation-suivi"
        filename = secure_filename(f"{prefix}-{person.get('last_name', '')}-{person.get('first_name', '')}.pdf")
        return Response(certificate_pdf(report, partner, order, person, logo_path=logo_path(host, partner)), mimetype="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{filename}"',
                                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer"})

    @bp.get(base + "/connexions.csv")
    @customer
    def elearning_progress_connections(oid, learner_id):
        _, order, person, _ = context(oid, learner_id)
        report = ProgressReader(host).report(order, person)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        mac_aps = order["course_code"] == "mac-aps"
        writer.writerow((["Périmètre", "Édition"] if mac_aps else []) + ["Module", "Connexion (Paris)", "Dernière activité (Paris)", "Fin (Paris)", "Temps actif", "Temps actif (secondes)"])
        for row in report["connections"] + (report.get("complement_connections", []) if mac_aps else []):
            values = [row[k] for k in ("module", "started_at_label", "last_seen_label", "ended_at_label", "active_time_label", "credited_seconds")]
            if mac_aps:
                values = ["Complément" if row.get("pedagogical_scope") == "complement" else "Parcours principal", row.get("version", "")] + values
            writer.writerow(["'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
        return Response("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="releve-connexions.csv"'})


