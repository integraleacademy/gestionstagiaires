"""Readable module evidence with two empty fields for real provider signatures."""
from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo


def duration(value):
    total = max(0, round(float(value or 0) * 100))
    hours, rest = divmod(total, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds, hundredths = divmod(rest, 100)
    suffix = f",{hundredths:02d}" if hundredths else ""
    return f"{hours:02d} h {minutes:02d} min {seconds:02d}{suffix} s"


def date_label(value):
    if not value:
        return "Non enregistrée"
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %H:%M:%S")
    except ValueError:
        return str(value)


def _answer_label(value):
    if value is None:
        return "Non enregistrée"
    return str(value) if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def render_module_pdf(snapshot):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, TableStyle, LongTable, PageBreak, Flowable

    font = "Helvetica"
    bold = "Helvetica-Bold"
    font_root = Path("/usr/share/fonts/truetype/dejavu")
    if (font_root / "DejaVuSans.ttf").is_file():
        if "APSProof" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("APSProof", str(font_root / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("APSProofBold", str(font_root / "DejaVuSans-Bold.ttf")))
            pdfmetrics.registerFontFamily("APSProof", normal="APSProof", bold="APSProofBold")
        font, bold = "APSProof", "APSProofBold"
    navy, blue = colors.HexColor("#183856"), colors.HexColor("#236caf")
    pale, ink, muted = colors.HexColor("#eef4fa"), colors.HexColor("#24374b"), colors.HexColor("#596b7c")
    styles = {name: ParagraphStyle(name, fontName=face, fontSize=size, leading=leading,
                                  textColor=color, spaceAfter=after, alignment=TA_LEFT, splitLongWords=True)
              for name, face, size, leading, color, after in (
                  ("title", bold, 23, 29, navy, 12), ("sub", bold, 13, 18, blue, 9),
                  ("h", bold, 11, 16, navy, 7), ("body", font, 9, 14, ink, 6),
                  ("small", font, 7.5, 11, muted, 4), ("cell", font, 7.2, 10.5, ink, 0),
                  ("th", bold, 7.2, 10, colors.white, 0))}
    def p(value, style="body"):
        return Paragraph(escape(str(value if value is not None else "Non enregistré")).replace("\n", "<br/>"), styles[style])
    def table(rows, widths, header=True):
        value = LongTable(rows, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0, hAlign="LEFT")
        rules = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#dbe5ee"))]
        if header:
            rules += [("BACKGROUND", (0, 0), (-1, 0), navy),
                      ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, pale])]
        value.setStyle(TableStyle(rules))
        return value
    learner, provider, responsible, progress = (snapshot[k] for k in ("learner", "provider", "responsible", "progress"))
    learner_name = learner["first_name"] + " " + learner["last_name"]
    responsible_name = responsible["first_name"] + " " + responsible["last_name"]
    fields = {}

    class SignatureFields(Flowable):
        def __init__(self):
            super().__init__()
            self.width = 174 * mm
            self.person_text = {}
            for role, person in (("learner", learner), ("responsible", responsible)):
                text = p(person["first_name"] + " " + person["last_name"] + "\n" + person["email"] +
                         ("\nTéléphone : " + person["phone"] if person.get("phone") else ""), "small")
                _, height = text.wrap(82 * mm, 100 * mm)
                self.person_text[role] = (text, height)
            self.height = max(59 * mm, max(value[1] for value in self.person_text.values()) + 45 * mm)
        def draw(self):
            canvas = self.canv
            block_width = 82 * mm
            for role, x, label, person in (
                ("learner", 0, "Le stagiaire", learner),
                ("responsible", 92 * mm, "Le responsable du prestataire", responsible),
            ):
                canvas.setFillColor(navy)
                canvas.setFont(bold, 9)
                canvas.drawString(x, self.height - 5 * mm, label)
                text, h = self.person_text[role]
                text.drawOn(canvas, x, self.height - 9 * mm - h)
                canvas.setStrokeColor(colors.HexColor("#9cafc1"))
                canvas.roundRect(x, 2 * mm, block_width, 28 * mm, 4, fill=0, stroke=1)
                canvas.setFillColor(muted)
                canvas.setFont(font, 7)
                canvas.drawString(x + 4 * mm, 32 * mm, "Signature électronique Yousign")
                absolute_x, absolute_y = canvas.absolutePosition(x + 2 * mm, 4 * mm)
                field_height, field_width = 24 * mm, 78 * mm
                fields[role] = {"page": canvas.getPageNumber(), "x": round(absolute_x),
                                "y": round(A4[1] - absolute_y - field_height),
                                "width": round(field_width), "height": round(field_height)}

    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=19 * mm, bottomMargin=20 * mm,
                            title="Tableau de suivi APS - " + snapshot["course"]["title"], author=provider["name"])
    story = [p(provider["name"], "sub"), p("Tableau de suivi de la formation à distance", "title"),
             p(snapshot["course"]["title"], "sub"),
             p("Formation APS asynchrone - tableau individuel par module", "body"), Spacer(1, 3 * mm)]
    if snapshot.get("reissued_from"):
        story.append(p("Réédition du tableau " + snapshot["reissued_from"] + ". Traces initialement figées le " +
                       date_label(snapshot.get("source_captured_at")) + ".", "small"))
    identity_rows = [
        [p("STAGIAIRE", "th"), p("PRESTATAIRE DE FORMATION", "th")],
        [p(learner_name + "\n" + learner["email"] +
           ("\nNé(e) le " + learner["birth_date"] if learner.get("birth_date") else ""), "cell"),
         p(provider["name"] + "\nSIRET : " + (provider.get("siret") or "Non renseigné") + "\n" +
           " ".join(provider.get(k, "") for k in ("address", "postal_code", "city")), "cell")],
        [p("Carte professionnelle / autorisation préalable\n" + learner["cnaps_number"], "cell"),
         p("Responsable : " + responsible_name + "\n" + responsible["email"], "cell")],
        [p("Session : " + snapshot["session"]["name"] + "\nFin de session : " + snapshot["session"]["date_end"], "cell"),
         p("Module : " + snapshot["course_id"] + "\nÉdition : " + snapshot["course_version"], "cell")],
    ]
    story.extend([table(identity_rows, [87, 87]), Spacer(1, 5 * mm), p("Synthèse du module", "h")])
    summary = progress.get("assessment_summary") or {}
    first_score = summary.get("first_attempt_score_percent")
    question_count = summary.get("assessed_items", 0)
    first_label = (f"{first_score:g} % ({summary.get('first_attempt_correct', 0)} / {question_count} " +
                   ("question enregistrée)" if question_count == 1 else "questions enregistrées)")) if isinstance(first_score, (int, float)) else "Non disponible pour les tentatives anciennes"
    practice = summary.get("practice") or {}
    metrics = [
        [p("TEMPS ACTIF ENREGISTRÉ", "th"), p("DURÉE OBLIGATOIRE", "th"), p("ACTIVITÉS TERMINÉES", "th")],
        [p(duration(progress.get("active_seconds")), "cell"), p(duration(progress.get("required_seconds")), "cell"),
         p(str(len(progress.get("completed_activity_ids") or [])), "cell")],
    ]
    story.extend([table(metrics, [58, 58, 58]), Spacer(1, 4 * mm),
                  p("Premier essai enregistré : " + first_label),
                  p(f"Score enregistré après correction : {float(progress.get('score_percent') or 0):g} %"),
                  p("Questions - essais enregistrés : " + str(summary.get("attempt_count", 0)) + "; erreurs avant correction : " +
                    str(summary.get("incorrect_attempt_count", 0)) + "."),
                  p("Ateliers - essais enregistrés : " + str(practice.get("attempt_count", 0)) + "; erreurs avant correction : " +
                    str(practice.get("incorrect_attempt_count", 0)) + "."),
                  p("Le score après correction inclut les reprises pédagogiques. Il ne remplace pas le résultat d'une première réponse.", "small"),
                  p("Début du module : " + date_label(progress.get("started_at"))),
                  p("Tableau figé le : " + date_label(snapshot["frozen_at"])),
                  p("Conservation prévue jusqu'au : " + snapshot["retention_until"] + " (trois ans après la fin de la session).", "small"),
                  p("Ce tableau décrit les traces du module ; il ne vaut ni diplôme ni certification professionnelle.", "small")])
    story.extend([PageBreak(), p("Résultats des évaluations", "title"), p(snapshot["course"]["title"], "sub")])
    activity_titles = {a["id"]: a["title"] for s in snapshot["course"]["sections"] for a in s["activities"]}
    activity_rows = [[p(x, "th") for x in ("SÉQUENCE / ACTIVITÉ", "ÉTAT", "RÉSULTAT ENREGISTRÉ")]]
    for section in snapshot["course"]["sections"]:
        for activity in section["activities"]:
            if not activity["scored"] and not activity.get("answer"):
                continue
            answer = activity.get("answer") or {}
            result = "Réponse correcte" if answer.get("correct") is True else "À revoir" if answer.get("correct") is False else (
                "Exercices corrigés" if answer.get("practice_correct") else "Autoévaluation - sans validation du formateur" if answer.get("production_answers") else "Activité enregistrée")
            question = activity.get("prompt") or activity["title"]
            activity_rows.append([p(section["title"] + "\n" + question, "cell"),
                                  p("Terminée" if activity["completed"] else "Non terminée", "cell"), p(result, "cell")])
    if len(activity_rows) > 1:
        story.append(table(activity_rows, [100, 28, 46]))
    else:
        story.append(p("Aucun résultat d'évaluation disponible dans les traces de ce module."))
    story.extend([Spacer(1, 5 * mm), p("Premières réponses et reprises", "h"),
                  p("Les lignes ci-dessous reproduisent les essais effectivement enregistrés. Aucun essai antérieur absent du suivi n'est inventé.", "small")])
    if snapshot["assessment_attempts"]:
        attempt_rows = [[p(x, "th") for x in ("ACTIVITÉ / QUESTION", "ESSAI / DATE", "RÉPONSE", "RÉSULTAT")]]
        for attempt in snapshot["assessment_attempts"]:
            label = attempt.get("title") or activity_titles.get(attempt.get("activity_id"), attempt.get("activity_id", "Activité"))
            if len(label) > 700:
                label = label[:700] + "… (énoncé intégral dans les traces jointes)"
            if attempt.get("item_id") and attempt.get("item_id") != attempt.get("activity_id"):
                label += "\n" + str(attempt["item_id"])
            answer = attempt.get("answer_text") or _answer_label(attempt.get("answer"))
            # Keep arbitrarily long structured answers in the immutable JSON;
            # PDF cells carry the readable result and never overflow a page.
            if len(answer) > 550:
                answer = answer[:550] + "… (réponse intégrale dans les traces jointes à l'archive)"
            attempt_rows.append([p(label, "cell"), p("N° " + str(attempt.get("attempt_number", "?")) + "\n" + date_label(attempt.get("submitted_at")), "cell"),
                                 p(answer, "cell"), p("Correct" if attempt.get("correct") is True else "Erreur" if attempt.get("correct") is False else "Non évalué", "cell")])
        story.append(table(attempt_rows, [58, 40, 55, 21]))
    else:
        story.append(p("Historique détaillé des essais non disponible. Les résultats finaux ci-dessus restent conservés."))
    story.extend([PageBreak(), p("Relevé des connexions", "title"), p(learner_name + " - " + snapshot["course"]["title"], "sub"),
                  p("Heure de Paris (Europe/Paris). La dernière activité correspond au dernier signal reçu ; une fin non enregistrée n'est pas présentée comme une déconnexion.", "small")])
    connection_rows = [[p(x, "th") for x in ("DÉBUT", "DERNIÈRE ACTIVITÉ", "FIN ENREGISTRÉE", "TEMPS ACTIF")]]
    for connection in snapshot["connections"]:
        connection_rows.append([p(date_label(connection.get("created_at")), "cell"), p(date_label(connection.get("last_seen_at")), "cell"),
                                p(date_label(connection.get("ended_at")), "cell"), p(duration(connection.get("credited_seconds")), "cell")])
    if len(connection_rows) > 1:
        story.append(table(connection_rows, [46, 46, 46, 36]))
        story.append(p("Total du temps actif des connexions : " + duration(sum(float(c.get("credited_seconds") or 0) for c in snapshot["connections"])), "h"))
    else:
        story.append(p("Aucun journal de connexion détaillé disponible dans les traces figées."))
    story.extend([PageBreak(), p("Signatures du tableau de suivi", "title"),
                  p(snapshot["course"]["title"], "sub"),
                  p("Stagiaire : " + learner_name), p("Prestataire : " + provider["name"]),
                  p("Édition du module : " + snapshot["course_version"]),
                  p("Les signatures portent sur l'intégralité de ce tableau et de ses relevés, figés le " + date_label(snapshot["frozen_at"]) + "."),
                  p("Le stagiaire et le responsable du prestataire attestent avoir pris connaissance des temps de connexion, du temps actif et des résultats enregistrés pour ce module."),
                  Spacer(1, 8 * mm), SignatureFields(), Spacer(1, 7 * mm),
                  p("Référence du tableau : " + snapshot["snapshot_id"], "small"),
                  p("Empreinte des données sources : " + snapshot["source_hash"], "small"),
                  p("Référence : article 8 de l'arrêté du 23 octobre 2024 relatif aux conditions matérielles et pédagogiques de la formation aux activités privées de sécurité.", "small"),
                  p("Les traces, ce tableau et les preuves de signature sont conservés jusqu'au " + snapshot["retention_until"] +
                    ". Leur finalité est le suivi pédagogique et la justification de la formation. Les droits relatifs aux données personnelles s'exercent auprès du prestataire.", "small")])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d9e3ed"))
        canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
        canvas.setFont(font, 7)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, "Suivi APS - " + snapshot["snapshot_id"][:16])
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue(), fields
