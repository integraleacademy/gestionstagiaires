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
from elearning_native.importer import CourseCatalog, CourseImportError
from elearning_native.paths import project_course, project_progress
from elearning_native.store import NativeElearningStore


CUSTOMER_ENDPOINTS = {"manuals_shop." + name for name in (
    "elearning_progress", "elearning_progress_certificate", "elearning_progress_connections",
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
            "exams": """SELECT exam_id, version, submitted_at, result_json FROM aps_exam_attempts
                WHERE session_id = ? AND trainee_id = ? ORDER BY submitted_at DESC""",
        }
        table_name = {"progress": "learner_course_progress", "connections": "tracking_sessions", "exams": "aps_exam_attempts"}[table]
        with sqlite3.connect(self.database_path.as_uri() + "?mode=ro", uri=True, timeout=15) as db:
            db.row_factory = sqlite3.Row
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
            records = [dict(row) for row in db.execute(queries[table], (session_id, learner_id))] if exists else []
        if table == "progress":
            for row in records:
                row.setdefault("video_progress_json", "{}")
            return [NativeElearningStore._serialize_progress(row) for row in records]
        return records

    def report(self, order, person, *, detailed=True):
        session_id, learner_id = "el-" + order["id"], str(person["id"])
        raw_rows = self.rows("progress", session_id, learner_id)
        by_key = {(r["course_id"], r["course_version"]): r for r in raw_rows}
        modules, exam_keys, course_titles = [], set(), {}
        total = completed = active = required = finished = 0
        starts, updates = [], []
        for assignment in order.get("modules", []):
            assigned_key = (str(assignment.get("course_id") or ""), str(assignment.get("course_version") or ""))
            if all(assigned_key):
                # Historical connections remain evidence even if the purchased
                # course files are temporarily unavailable. Do not broaden the
                # allowlist to other editions of the same module.
                course_titles[assigned_key] = assignment.get("title") or assigned_key[0]
            module = {"title": assignment.get("title") or assignment.get("course_id") or "Module",
                      "version": assignment.get("course_version") or "", "available": False,
                      "status_label": "Suivi indisponible", "sections": [], "module_complete": False,
                      "required_time_label": time_label(int(assignment.get("required_minutes") or 0) * 60)}
            try:
                course = self.course(assignment)
            except (CourseImportError, OSError):
                recorded = by_key.get(assigned_key, {})
                recorded_seconds = max(0, float(recorded.get("active_seconds") or 0))
                active += recorded_seconds
                module.update(active_seconds=recorded_seconds, active_time_label=time_label(recorded_seconds))
                if recorded.get("started_at"):
                    starts.append(recorded["started_at"])
                if recorded.get("updated_at"):
                    updates.append(recorded["updated_at"])
                required += int(assignment.get("required_minutes") or 0) * 60
                modules.append(module)
                continue
            key = (course["id"], course["version"])
            course_titles[key] = course["title"]
            progress = project_progress(by_key.get(key, {}), course)
            ids = set(progress["completed_activity_ids"])
            activities = [a for section in course["sections"] for a in section.get("activities", [])]
            questions = [a for a in activities if a.get("scored")]
            answered = sum(a["id"] in progress.get("answers", {}) for a in questions)
            total += len(course["activity_order"])
            completed += len(ids)
            active += progress["active_seconds"]
            required += progress["required_seconds"]
            finished += int(progress["module_complete"])
            if progress.get("started_at"):
                starts.append(progress["started_at"])
            if progress.get("updated_at"):
                updates.append(progress["updated_at"])
            module.update(title=course["title"], version=course["version"], available=True,
                          progress_percent=progress["progress_percent"], active_seconds=progress["active_seconds"],
                          active_time_label=time_label(progress["active_seconds"]),
                          required_time_label=time_label(progress["required_seconds"]),
                          remaining_time_label=time_label(progress["remaining_seconds"]),
                          module_complete=progress["module_complete"], status=progress["status"],
                          status_label=STATUS_LABELS.get(progress["status"], "En cours"),
                          completed_activities=len(ids), total_activities=len(course["activity_order"]),
                          score_percent=progress["score_percent"] if answered else None,
                          answered_questions=answered, total_questions=len(questions),
                          completed_videos=progress["completed_video_count"], total_videos=progress["required_video_count"],
                          started_at_label=date_label(progress.get("started_at")), updated_at_label=date_label(progress.get("updated_at")))
            if course.get("mock_exam_id"):
                exam_keys.add((course["mock_exam_id"], course["version"]))
            if detailed:
                for section in course["sections"]:
                    rows = []
                    for activity in section.get("activities", []):
                        answer = progress.get("answers", {}).get(activity["id"], {})
                        rows.append({"title": activity.get("title") or "Activité", "completed": activity["id"] in ids,
                                     "current": activity["id"] == progress.get("current_activity_id"),
                                     "answer_label": ("Réponse correcte" if answer.get("correct") else "À revoir") if activity.get("scored") and answer else ""})
                        if activity.get("production") and isinstance(answer.get("production_answers"), dict):
                            production = activity["production"]
                            rows[-1]["production"] = {
                                "draft": bool(answer.get("production_draft")),
                                "responses": [{"label": field["label"], "text": answer["production_answers"].get(field["id"], "")}
                                              for field in production["response_fields"]],
                                "review": [{"label": criterion["label"], "needs_help": answer.get("production_self_review", {}).get(criterion["id"]) == "needs_help"}
                                           for criterion in production["rubric"] if answer.get("production_self_review", {}).get(criterion["id"]) in ("checked", "needs_help")],
                            }
                    module["sections"].append({"title": section.get("title") or "Séquence", "activities": rows,
                                               "completed": sum(a["completed"] for a in rows), "total": len(rows)})
            modules.append(module)
        versions = {m["version"] for m in modules if m["available"]}
        if len(versions) == 1:
            exam_keys.add(("vtc-final" if order["course_code"] == "vtc" else "final", next(iter(versions))))
        complete = bool(modules) and finished == len(modules)
        available = bool(modules) and all(m["available"] for m in modules)
        report = {"available": available, "modules": modules, "completed_modules": finished, "total_modules": len(modules),
                  "completed_activities": completed, "total_activities": total,
                  "progress_percent": round(completed / total * 100, 1) if total and available else None,
                  "active_seconds": round(active, 2), "active_time_label": time_label(active),
                  "required_seconds": required, "required_time_label": time_label(required), "complete": complete,
                  "status_label": "Parcours terminé" if complete else "Suivi partiellement indisponible" if not available else "En cours" if starts else "Non commencé",
                  "started_at_label": date_label(min(starts)) if starts else "Pas encore commencé",
                  "updated_at_label": date_label(max(updates)) if updates else "Aucune activité enregistrée",
                  "generated_at_label": date_label(dt.datetime.now(dt.timezone.utc).isoformat()),
                  "connections": [], "exams": []}
        if detailed:
            for connection in self.rows("connections", session_id, learner_id):
                key = (connection["course_id"], connection["course_version"])
                if key not in course_titles:
                    continue
                report["connections"].append({"module": course_titles[key],
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
                title = "Examen blanc final" if attempt["exam_id"] in {"final", "vtc-final"} else "Examen blanc " + attempt["exam_id"].replace("vtc-", "").replace("module-", "module ")
                report["exams"].append({**row, "title": title, "date_label": date_label(attempt["submitted_at"])})
        return report


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
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, Image, PageBreak, LongTable

    output = io.BytesIO()
    centre_name = str(partner.get("name") or partner.get("centre") or "Organisme de formation").strip()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="SPECIMEN - Attestation de suivi e-learning" if specimen else "Attestation de suivi e-learning",
                            author=centre_name)
    styles = {name: ParagraphStyle(name, fontName=font, fontSize=size, leading=leading,
              textColor=colors.HexColor(color), spaceAfter=after, alignment=TA_LEFT) for name, font, size, leading, color, after in (
        ("brand", "Helvetica-Bold", 12, 15, "#2265a8", 16),
        ("title", "Helvetica-Bold", 23, 27, "#172c46", 10),
        ("heading", "Helvetica-Bold", 12, 16, "#172c46", 8),
        ("body", "Helvetica", 10, 15, "#263d55", 8),
        ("small", "Helvetica", 8, 11, "#526579", 4),
        ("cell", "Helvetica", 8, 11, "#263d55", 0),
        ("th", "Helvetica-Bold", 8, 11, "#ffffff", 0))}
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
                        scale = min(48 * mm / width, 22 * mm / height)
                        logo = Image(image_buffer, width=width * scale, height=height * scale)
                        logo.hAlign = "LEFT"
        except (OSError, ValueError, UnidentifiedImageError, PillowImage.DecompressionBombError):
            logo = None
    if logo is not None:
        heading = Table([[logo, issuer]], colWidths=[55 * mm, 119 * mm], hAlign="LEFT")
        heading.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        story = [heading]
    else:
        story = issuer
    story.append(Spacer(1, 7 * mm))
    if specimen:
        story.extend([p("SPECIMEN - DONNÉES FICTIVES", "heading"),
                      p("Exemple de document. Ce spécimen ne prouve aucun suivi de formation et ne constitue pas une attestation délivrée à un stagiaire.", "small")])
    name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
    story.extend([p("Attestation de suivi", "title"),
             p("Parcours e-learning terminé" if report["complete"] else "Relevé de suivi partiel - parcours non terminé", "heading"),
             p(f"Stagiaire : {name}"), p(f"Adresse e-mail : {person.get('email', '')}"),
             p(f"Organisme de formation : {centre_name}"),
             p(f"Formation : {learning.COURSES[order['course_code']]['title']} ({order['course_code'].upper()})"),
             p(f"Groupe / accès : {order.get('group_name') or 'Accès individuel'}"), Spacer(1, 4 * mm)])
    metrics = [[p("TEMPS ACTIF ENREGISTRÉ", "small"), p("MODULES TERMINÉS", "small")],
               [p(report["active_time_label"], "heading"), p(f"{report['completed_modules']} / {report['total_modules']}", "heading")],
               [p("DURÉE PRÉVUE DU PARCOURS", "small"), p("ACTIVITÉS TERMINÉES", "small")],
               [p(report["required_time_label"], "body"), p(f"{report['completed_activities']} / {report['total_activities']}" if report["available"] else "Données partielles", "body")]]
    box = Table(metrics, colWidths=[87 * mm, 87 * mm])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4fb")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story.extend([box, Spacer(1, 6 * mm), p(f"Première activité : {report['started_at_label']}"),
                  p(f"Dernière activité : {report['updated_at_label']}"),
                  p("Le temps indiqué correspond exclusivement au temps actif comptabilisé par la plateforme. La durée prévue n’est pas une durée automatiquement acquise. Un module est terminé lorsque ses activités et sa durée obligatoire sont accomplies.", "small"),
                  Spacer(1, 5 * mm)])
    table_rows = [[p(value, "th") for value in ("MODULE", "PROGRESSION", "TEMPS ACTIF", "ÉTAT")]]
    for module in report["modules"]:
        table_rows.append([p(module["title"], "cell"), p(f"{module['progress_percent']:g} %" if module["available"] else "Indisponible", "cell"),
                           p(module.get("active_time_label", "Indisponible"), "cell"), p(module["status_label"], "cell")])
    table = Table(table_rows, colWidths=[67 * mm, 31 * mm, 36 * mm, 40 * mm], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173858")),
                              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")]),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 9),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.extend([p("Détail du parcours", "heading"), table, Spacer(1, 6 * mm),
                  KeepTogether([p(f"Édité le {report['generated_at_label']} (heure de Paris).", "small"),
                    p("Données fictives de démonstration : ce document n’atteste d’aucune formation suivie." if specimen else
                      f"Attestation éditée pour {centre_name} à partir des traces de sa plateforme e-learning. Elle décrit le suivi pédagogique constaté à la date d’édition ; elle ne vaut ni diplôme ni certification professionnelle.", "small"),
                    p(f"Référence de commande : {order['id']}\nIdentifiant du stagiaire : {person['id']}", "small")])])

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
                            f"Parcours : {order['course_code'].upper()} · {order.get('group_name') or 'Accès individuel'}", "small")

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
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(connection_table)
    story.extend([Spacer(1, 5 * mm),
                  p(f"Relevé édité le {report['generated_at_label']} (heure de Paris).", "small"),
                  p(f"Référence de commande : {order['id']} · Identifiant du stagiaire : {person['id']}", "small")])

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
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526579"))
        footer_name = ("SPECIMEN - " if specimen else "") + centre_name
        while canvas.stringWidth(footer_name + " - Suivi e-learning", "Helvetica", 8) > 145 * mm:
            footer_name = footer_name[:-2].rstrip()
        canvas.drawString(18 * mm, 10 * mm, footer_name + " - Suivi e-learning")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def register_routes(host, bp, *, page, customer, partner_data):
    def context(oid, learner_id):
        data, partner = partner_data()
        order = next((o for o in data.get("manual_orders", []) if learning.is_order(o) and o.get("id") == oid
                      and o.get("partner_id") == partner["id"] == host._current_partner_id()), None)
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
                    course=learning.COURSES[order["course_code"]])

    @bp.get(base + "/attestation.pdf")
    @customer
    def elearning_progress_certificate(oid, learner_id):
        from organisme_profile import logo_path

        partner, order, person, _ = context(oid, learner_id)
        report = ProgressReader(host).report(order, person, detailed=True)
        filename = secure_filename(f"attestation-suivi-{person.get('last_name', '')}-{person.get('first_name', '')}.pdf")
        return Response(certificate_pdf(report, partner, order, person, logo_path=logo_path(host, partner)), mimetype="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @bp.get(base + "/connexions.csv")
    @customer
    def elearning_progress_connections(oid, learner_id):
        _, order, person, _ = context(oid, learner_id)
        report = ProgressReader(host).report(order, person)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Module", "Connexion (Paris)", "Dernière activité (Paris)", "Fin (Paris)", "Temps actif", "Temps actif (secondes)"])
        for row in report["connections"]:
            values = [row[k] for k in ("module", "started_at_label", "last_seen_label", "ended_at_label", "active_time_label", "credited_seconds")]
            writer.writerow(["'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value for value in values])
        return Response("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="releve-connexions.csv"'})
