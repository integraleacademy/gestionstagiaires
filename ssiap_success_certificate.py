"""Attestation made available in the certified SSIAP 1 candidate's own space."""
import io
import os
import re
import unicodedata

from flask import abort, redirect, request, send_file, url_for

import ssiap_exam
import ssiap_pathways


def document_fields(host, training, trainee):
    if training.get("partner_id") not in (None, "", host.INTEGRALE_PARTNER_ID):
        return None
    if host._ssiap_exam_status(trainee) != "certified" or host._trainee_registration_is_cancelled(trainee):
        return None
    kind = str(host._session_get(training, "training_type", "") or "")
    title = str(host._session_get(training, "name", "") or "")
    labels = unicodedata.normalize("NFKD", f"{kind} {title}".casefold()).encode("ascii", "ignore").decode()
    if not re.search(r"\bssiap(?:\s*[123])?\b", kind, re.I):
        return None
    if re.search(r"ssiap\s*[23]|\b(?:afc|aps|recyclage|recycl|rec|ran|rn|remise)\b", labels):
        return None
    settings = ssiap_exam.settings(ssiap_exam.for_family(training, "ssiap"))
    if settings.get("level") != "SSIAP 1":
        return None
    first = host._ssiap_diploma_first_name(trainee.get("ssiap_diploma_first_name") or trainee.get("first_name") or trainee.get("prenom"))
    last = host.normalize_last_name(trainee.get("ssiap_diploma_last_name") or trainee.get("last_name") or trainee.get("nom"))
    schedule = ssiap_pathways.effective_session(training, trainee)
    start = host._diploma_date_fr(host._session_get(schedule, "date_start", ""))
    end = host._diploma_date_fr(host._session_get(schedule, "date_end", ""))
    exam = host._ssiap_diploma_exam_date(training, trainee)
    if all((first, last, start, end, exam)):
        return {"name": f"{first} {last}", "start": start, "end": end, "exam": exam}
    return None


def render(fields, root):
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from ssiap_exam_pdf import new_pdf, finish, paragraph, signature_assets, NAVY, MUTED, TEAL, LIGHT, M, W, H, WIDTH

    c, stream = new_pdf("Attestation de réussite à l’examen SSIAP 1")
    assets = signature_assets(root)
    c.setFillColor(NAVY)
    c.rect(0, H-8, W, 8, fill=1, stroke=0)
    c.drawImage(os.path.join(root, "static", "logo-integrale.png"), M, H-100, 106, 66,
                preserveAspectRatio=True, anchor="w", mask="auto")
    paragraph(c, "INTÉGRALE SÉCURITÉ FORMATIONS", W-278, H-51, 226, 9, NAVY, True, alignment=2)
    paragraph(c, "54 chemin du Carreou · 83480 Puget-sur-Argens", W-294, H-70, 242, 8, MUTED, alignment=2)
    c.setStrokeColor(colors.HexColor("#d7e2ea"))
    c.line(M, H-116, W-M, H-116)

    paragraph(c, "SÉCURITÉ INCENDIE  /  SSIAP 1", M, H-147, size=10, color=TEAL, bold=True)
    paragraph(c, "Attestation de réussite", M, H-174, size=30, bold=True)
    paragraph(c, "à l’examen SSIAP 1", M, H-216, size=21, color=NAVY)
    y = paragraph(c, "Je soussigné, Clément VAILLANT, directeur du centre de formation Intégrale Academy, atteste que",
                  M, H-279, size=12)
    y = paragraph(c, fields["name"], M, y-13, size=21, bold=True)
    y = paragraph(c, "a suivi la formation d’agent de service de sécurité incendie et d’assistance à personnes (SSIAP 1) "
                  f"et a réussi l’examen qui s’est déroulé le {fields['exam']}.", M, y-12, size=12)
    top = y-25
    c.setFillColor(LIGHT)
    c.roundRect(M, top-69, WIDTH, 69, 9, fill=1, stroke=0)
    paragraph(c, "DATES DE FORMATION", M+17, top-13, WIDTH-34, 8.5, TEAL, True)
    paragraph(c, f"Du {fields['start']} au {fields['end']}", M+17, top-32, WIDTH-34, 14, NAVY, True)

    paragraph(c, "Attestation établie pour faire valoir ce que de droit.", M, top-92, size=11)
    y = min(top-139, 252)
    paragraph(c, "Clément VAILLANT", M, y, size=12, bold=True)
    paragraph(c, "Directeur du centre de formation", M, y-19, size=10, color=MUTED)
    for key, x, width, height in (("signature", M+3, 110, 58), ("stamp", W-M-176, 176, 58)):
        c.drawImage(ImageReader(io.BytesIO(assets[key])), x, y-106, width, height,
                    preserveAspectRatio=True, mask="auto")
    c.line(M, 58, W-M, 58)
    paragraph(c, "Intégrale Academy  ·  Intégrale Sécurité Formations  ·  SIRET 840 899 884 00026",
              M, 43, size=8, color=MUTED)
    return finish(c, stream)


def register(app, host):
    @app.get("/espace/<token>/attestation-reussite-ssiap-1.pdf")
    def public_ssiap_success(token):
        if not host._public_is_authed(token):
            return redirect(url_for("public_trainee_login", token=token))
        group, trainee = host.find_session_and_trainee_by_token(host.load_data(run_background_tasks=False), token)
        fields = document_fields(host, group, trainee) if group and trainee else None
        if not fields:
            abort(404)
        response = send_file(io.BytesIO(render(fields, app.root_path)), mimetype="application/pdf",
                             download_name="Attestation-reussite-SSIAP-1.pdf", conditional=False,
                             as_attachment=request.args.get("download") == "1")
        response.headers["Cache-Control"] = "private, no-store"
        return response
