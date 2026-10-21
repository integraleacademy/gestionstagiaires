"""Read-only copies of saved exam attempts, independent of today's questions."""
from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path
import sqlite3
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from elearning_exam_reporting import number_label, recorded_seconds


def read_stored_attempt(database_path, session_id, learner_id, exam_id, version, attempt_id):
    """The caller must first authorize the order and its pinned exam/version."""
    path = Path(database_path)
    if not path.is_file():
        return None
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15) as db:
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='aps_exam_attempts'").fetchone():
            return None
        row = db.execute("""SELECT exam_id, version, attempt_id, submitted_at, result_json
            FROM aps_exam_attempts WHERE session_id=? AND trainee_id=?
            AND exam_id=? AND version=? AND attempt_id=?""",
            (str(session_id), str(learner_id), exam_id, version, attempt_id)).fetchone()
    if row is None:
        return None
    try:
        result = json.loads(row["result_json"])
    except (ValueError, TypeError):
        return None
    return {**dict(row), "result": result} if isinstance(result, dict) else None


def _date(value):
    try:
        date = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=dt.timezone.utc)
        return date.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S")
    except (ValueError, TypeError):
        return "Non enregistrée"


def _text(value, fallback="Non enregistré"):
    return str(value) if isinstance(value, (str, int, float)) and str(value).strip() else fallback


def _logo(path, max_width, max_height):
    if not isinstance(path, Path) or not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        return None
    from PIL import Image as PillowImage
    from reportlab.platypus import Image
    try:
        with PillowImage.open(io.BytesIO(path.read_bytes())) as source:
            width, height = source.size
            if source.format not in {"PNG", "JPEG", "WEBP"} or not 0 < width * height <= 16_000_000:
                return None
            normalized = source.convert("RGBA")
            normalized.thumbnail((1200, 600))
            buffer = io.BytesIO()
            normalized.save(buffer, format="PNG")
            buffer.seek(0)
        scale = min(max_width / width, max_height / height)
        return Image(buffer, width=width * scale, height=height * scale)
    except (OSError, ValueError, PillowImage.DecompressionBombError):
        return None


def exam_attempt_pdf(attempt, partner, order, person, *, logo_path=None):
    """Export stored questions/answers/grades verbatim; never regrade an attempt."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                   TableStyle, HRFlowable, KeepTogether)

    regular, bold = "Helvetica", "Helvetica-Bold"
    font_root = Path("/usr/share/fonts/truetype/dejavu")
    if all((font_root / name).is_file() for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")):
        regular, bold = "ExamCopy", "ExamCopyBold"
        if regular not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular, str(font_root / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont(bold, str(font_root / "DejaVuSans-Bold.ttf")))
    navy, muted = colors.HexColor("#193958"), colors.HexColor("#60758a")
    green, red = colors.HexColor("#167047"), colors.HexColor("#b42332")
    styles = {
        "body": ParagraphStyle("body", fontName=regular, fontSize=9, leading=13, textColor=navy, spaceAfter=5),
        "small": ParagraphStyle("small", fontName=regular, fontSize=7.5, leading=11, textColor=muted, spaceAfter=3),
        "title": ParagraphStyle("title", fontName=bold, fontSize=22, leading=27, textColor=navy, spaceAfter=9, keepWithNext=True),
        "heading": ParagraphStyle("heading", fontName=bold, fontSize=10, leading=14, textColor=navy, spaceAfter=6, keepWithNext=True),
        "option": ParagraphStyle("option", fontName=regular, fontSize=8.5, leading=12, textColor=navy, leftIndent=10, spaceAfter=4),
        "selected": ParagraphStyle("selected", fontName=bold, fontSize=8.5, leading=12, textColor=navy, leftIndent=10, spaceAfter=5),
        "answer_correct": ParagraphStyle("answer_correct", fontName=bold, fontSize=8.5, leading=12,
            textColor=green, backColor=colors.HexColor("#edf8f1"), borderColor=colors.HexColor("#bfe3ce"),
            borderWidth=.5, borderRadius=4, borderPadding=6, leftIndent=10, spaceBefore=5, spaceAfter=10),
        "answer_incorrect": ParagraphStyle("answer_incorrect", fontName=bold, fontSize=8.5, leading=12,
            textColor=red, backColor=colors.HexColor("#fff0f0"), borderColor=colors.HexColor("#f1c5ca"),
            borderWidth=.5, borderRadius=4, borderPadding=6, leftIndent=10, spaceBefore=5, spaceAfter=10),
        "success": ParagraphStyle("success", fontName=bold, fontSize=9, leading=13, textColor=green, spaceAfter=5),
        "error": ParagraphStyle("error", fontName=bold, fontSize=9, leading=13, textColor=red, spaceAfter=5),
        "expected": ParagraphStyle("expected", fontName=regular, fontSize=7.5, leading=11, textColor=green, spaceAfter=3),
    }
    def p(value, style="body"):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), styles[style])

    result = attempt["result"]
    saved = result.get("corrections")
    questions = [q for q in saved if isinstance(q, dict)] if isinstance(saved, list) else []
    total = recorded_seconds(result.get("total"))
    name = " ".join(str(person.get(key) or "").strip() for key in ("first_name", "last_name")).strip()
    centre = str(partner.get("name") or partner.get("centre") or "Organisme de formation")
    label = "MAC APS" if order["course_code"] == "mac-aps" else order["course_code"].upper()
    title = attempt.get("title") or "Examen blanc"
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=17 * mm, bottomMargin=20 * mm,
                            title=f"Copie d’examen blanc - {name}", author=centre)
    issuer = [p(centre, "heading")]
    for line in (partner.get("address"), " ".join(str(partner.get(k) or "") for k in ("postal_code", "city")).strip(),
                 "SIRET : " + str(partner["siret"]) if partner.get("siret") else ""):
        if line:
            issuer.append(p(line, "small"))
    logo = _logo(logo_path, 35 * mm, 16 * mm)
    if logo:
        header = Table([[issuer, logo]], colWidths=[137 * mm, 37 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        story = [header]
    else:
        story = issuer
    story += [Spacer(1, 4 * mm), p("Copie d’examen blanc", "title"), p(title, "heading")]
    passed = result.get("passed")
    outcome = "Objectif atteint" if passed is True else "À retravailler" if passed is False else "Résultat non enregistré"
    outcome_mark = "✓ " if passed is True else "✕ " if passed is False else ""
    outcome_style = "success" if passed is True else "error" if passed is False else "body"
    percent = number_label(result.get("percent")) + " %" if recorded_seconds(result.get("percent")) is not None else "Non enregistré"
    identity = Table([
        [[p("STAGIAIRE", "small"), p(name, "heading"), p(person.get("email") or "", "small")],
         [p("RÉSULTAT ENREGISTRÉ", "small"), p(f"{number_label(result.get('score'))} / {number_label(result.get('total'))} · {percent}", "heading"), p(outcome_mark + outcome, outcome_style)]],
        [[p("Formation : " + label), p("Soumis le " + _date(attempt.get("submitted_at")) + " (Paris)", "small")],
         [p("Seuil : " + number_label(result.get("pass_percent")) + " %" if recorded_seconds(result.get("pass_percent")) is not None else "Seuil non enregistré", "small"),
          p("Durée de la tentative : non enregistrée", "small")]],
    ], colWidths=[87 * mm, 87 * mm])
    identity.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#edf4fa")),
                                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                                 ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [identity, Spacer(1, 4 * mm),
              p("Édition : " + _text(attempt.get("version")), "small"),
              p("Référence de la tentative : " + _text(attempt.get("attempt_id")), "small"),
              p(("Session : " if order.get("source_kind") == "training_session" else "Commande : ") + str(order.get("number") or order["id"]) + " · Stagiaire : " + str(person["id"]), "small"),
              p("Copie établie à partir des réponses et de la correction enregistrées lors de cette tentative.", "small"),
              Spacer(1, 4 * mm)]
    if not questions or total is None or len(questions) != total:
        story += [p("Détails de la tentative incomplets", "heading"),
                  p(f"{len(questions)} question(s) conservée(s) sur {number_label(total)}. Les informations absentes de l’archive ne sont pas reconstituées.")]
    for index, question in enumerate(questions, 1):
        question_block = [HRFlowable(width="100%", thickness=.5, color=colors.HexColor("#dce6ef")), Spacer(1, 4 * mm),
                  p(f"Question {index} — {_text(question.get('prompt'), 'Intitulé non enregistré')}", "heading")]
        if question.get("module"):
            question_block.append(p(question["module"], "small"))
        options = question.get("options")
        options = [option for option in options if isinstance(option, dict)] if isinstance(options, list) else []
        correct = question.get("correct")
        labels = {}
        for position, option in enumerate(options, 1):
            key = option.get("id")
            option_label = f"{position}. {_text(option.get('text'), 'Proposition non enregistrée')}"
            if key is not None:
                labels[str(key)] = option_label
            selected = key is not None and key == question.get("selected")
            expected_option = key is not None and key == question.get("answer")
            style = "selected" if selected else "option"
            mark = ""
            if selected and correct is False:
                style, mark = "answer_incorrect", "✕ "
            elif (selected and correct is True) or (not selected and expected_option):
                style, mark = "answer_correct", "✓ "
            suffix = " — Réponse du stagiaire" if selected else " — Bonne réponse" if expected_option else ""
            question_block.append(p(mark + option_label + suffix, style))
        selected = labels.get(str(question.get("selected"))) if question.get("selected") is not None else None
        if not selected:
            question_block.append(p("Réponse du stagiaire : non enregistrée", "small"))
        status = "Réponse correcte" if correct is True else "Réponse incorrecte" if correct is False else "Correction non enregistrée"
        status_mark = "✓ " if correct is True else "✕ " if correct is False else ""
        status_style = "success" if correct is True else "error" if correct is False else "body"
        question_block.append(p(status_mark + status, status_style))
        expected = labels.get(str(question.get("answer"))) if question.get("answer") is not None else None
        question_block.append(p("Réponse attendue : " + (expected or "non enregistrée"), "expected" if expected else "small"))
        if question.get("explanation"):
            question_block.append(p("Corrigé : " + _text(question["explanation"]), "small"))
        question_block.append(Spacer(1, 3 * mm))
        story.append(KeepTogether(question_block))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#dce6ef"))
        canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
        canvas.setFont(regular, 7)
        canvas.setFillColor(muted)
        caption = name + " · " + str(attempt.get("exam_id") or "Examen blanc")
        while pdfmetrics.stringWidth(caption, regular, 7) > 145 * mm:
            caption = caption[:-2].rstrip()
        canvas.drawString(18 * mm, 10 * mm, caption)
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
