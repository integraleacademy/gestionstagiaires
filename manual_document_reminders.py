"""Shared content for manual and scheduled pre-training document reminders."""

import datetime
import hashlib
import json
import unicodedata
from html import escape
from email_design import render_email


def _status(value):
    return "".join(
        char for char in unicodedata.normalize("NFD", str(value or "").upper())
        if unicodedata.category(char) != "Mn"
    ).replace("_", " ").strip()


def document_actions(trainee, required_docs, *, training_type, experience_required):
    """Only ask for work the trainee can do, never for pending staff reviews."""
    documents = {doc.get("key"): doc for doc in trainee.get("documents", []) if isinstance(doc, dict)}
    actions = []
    for required in required_docs:
        key = required["key"]
        if required.get("optional") or (training_type == "A3P" and key == "permis" and trainee.get("no_permis")):
            continue
        doc = documents.get(key, {})
        status = _status(doc.get("status"))
        submitted = bool(doc.get("file") or any(doc.get("files") or []))
        if key == "candidate_info_sheet":
            submitted = submitted or bool(trainee.get("candidate_sheet_saved_at") or trainee.get("candidate_sheet"))
        if status == "CONFORME":
            continue
        if status == "NON CONFORME":
            actions.append({"label": required["label"], "action": "À corriger", "comment": str(doc.get("comment") or "").strip()})
        elif not submitted:
            actions.append({"label": required["label"], "action": "À déposer", "comment": ""})
    if experience_required:
        sheet = trainee.get("professional_experience_sheet")
        if not isinstance(sheet, dict) or not sheet:
            actions.append({"label": "Fiche d’expérience professionnelle", "action": "À compléter", "comment": ""})
        elif _status(sheet.get("status")) == "NON CONFORME":
            actions.append({"label": "Fiche d’expérience professionnelle", "action": "À corriger", "comment": str(sheet.get("comment") or "").strip()})
    return actions


def _email_html(*, first_name, training, date_label, deadline_label, overdue, today_start,
                intro, urgency, portal_link, documents, missing_information, logo_url):
    safe_link = escape(portal_link, quote=True)
    greeting = f"Bonjour {escape(first_name)}," if first_name else "Bonjour,"
    logo = (
        f'<img src="{escape(logo_url, quote=True)}" width="54" alt="Logo Intégrale Academy" '
        'style="display:block;width:54px;height:auto;border:0;outline:none;">'
        if logo_url else ""
    )
    rows = []
    for index, doc in enumerate(documents, 1):
        correction = doc["action"] == "À corriger"
        color, background = ("#b42318", "#fff1f0") if correction else ("#946200", "#fff8e6")
        comment = f'<p style="margin:8px 0 0;font-size:14px;line-height:1.6;color:#64748b;">{escape(doc["comment"])}</p>' if doc["comment"] else ""
        rows.append(f'''<tr>
          <td width="38" valign="top" style="padding:18px 12px 18px 0;border-top:1px solid #e8edf3;color:#94a3b8;font-size:13px;font-weight:700;">{index:02d}</td>
          <td valign="top" style="padding:16px 0;border-top:1px solid #e8edf3;">
            <p style="margin:0 0 8px;font-size:15px;line-height:1.55;font-weight:700;color:#172033;">{escape(doc["label"])}</p>
            <span style="display:inline-block;padding:4px 9px;border-radius:6px;background:{background};color:{color};font-size:12px;line-height:1.4;font-weight:700;">{escape(doc["action"])}</span>{comment}
          </td></tr>''')
    docs_html = (
        '<h2 style="margin:28px 0 14px;font-size:20px;line-height:1.4;color:#172033;">Documents à fournir ou à corriger</h2>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        + "".join(rows) + "</table>"
    ) if rows else ""
    infos_html = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:18px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;"><tr><td style="padding:18px;">'
        '<h2 style="margin:0 0 10px;font-size:16px;color:#172033;">Informations à compléter dans votre espace</h2>'
        '<ul style="margin:0;padding-left:20px;font-size:14px;line-height:1.8;color:#475569;">'
        + "".join(f"<li>{escape(item)}</li>" for item in missing_information)
        + "</ul></td></tr></table>"
    ) if missing_information else ""
    deadline_title = "ÉCHÉANCE DÉPASSÉE · DÉPÔT IMMÉDIAT" if overdue else "À COMPLÉTER AU PLUS TARD LE"
    headline = "Votre formation commence aujourd’hui." if today_start else "Votre formation approche."
    return render_email(f"""
    <p style="margin:0 0 14px;font-size:17px;line-height:1.5;">{greeting}</p>
    <p style="margin:0 0 22px;color:#475569;font-size:15px;line-height:1.75;">{escape(intro)}</p>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fffbf2;border:1px solid #f1d699;border-left:4px solid #db9f2f;border-radius:12px;"><tr><td style="padding:20px;">
      <p style="margin:0 0 7px;color:#8b570d;font-size:11px;line-height:1.5;letter-spacing:.8px;font-weight:700;">{deadline_title}</p>
      <p class="mail-date" style="margin:0 0 10px;color:#172033;font-size:34px;line-height:1.2;font-weight:700;">{deadline_label}</p>
      <p style="margin:0;color:#785722;font-size:14px;line-height:1.7;">{escape(urgency)}</p>
    </td></tr></table>
    {docs_html}{infos_html}
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 18px;"><tr><td align="center" bgcolor="#178047" style="border-radius:10px;background:#178047;">
      <a href="{safe_link}" style="display:block;padding:17px 18px;color:#ffffff;font-size:16px;line-height:1.4;font-weight:700;text-decoration:none;border-radius:10px;">Accéder à mon espace stagiaire&nbsp; →</a>
    </td></tr></table>
    <p style="margin:0;color:#64748b;font-size:13px;line-height:1.7;">Merci de transmettre des documents complets et lisibles. Les pièces déjà déposées et en cours de vérification ne sont pas à renvoyer.</p>
    <p style="margin:18px 0 0;color:#94a3b8;font-size:11px;line-height:1.6;">Si le bouton ne fonctionne pas, copiez ce lien :<br><a href="{safe_link}" style="color:#64748b;word-break:break-all;overflow-wrap:anywhere;">{escape(portal_link)}</a></p>
  """, title="Finalisez votre dossier de formation", eyebrow="ACTION REQUISE", preheader=f"{headline} Date limite : {deadline_label}.")


def build_content(*, first_name, training, start_date, today, portal_link, documents, missing_information, logo_url="", automatic_stage=None):
    deadline = start_date - datetime.timedelta(days=10)
    date_label = start_date.strftime("%d/%m/%Y")
    deadline_label = deadline.strftime("%d/%m/%Y")
    subject = f"URGENT – Documents à compléter avant votre formation du {date_label}"
    intro = f"Votre formation {training} commence bientôt, le {date_label}. Votre dossier d’inscription est encore incomplet."
    if start_date == today:
        intro = f"Votre formation {training} commence aujourd’hui, le {date_label}. Votre dossier d’inscription est encore incomplet."
    urgency = (
        f"Merci de déposer les documents demandés sur votre espace stagiaire dès que possible et au plus tard le {deadline_label}, "
        "soit 10 jours avant votre entrée en formation."
    )
    sms_deadline = f"Déposez-les dès que possible, au plus tard le {deadline_label} (10 jours avant l’entrée)."
    if automatic_stage in (25, 15, 10):
        subject = f"Rappel J−{automatic_stage} – Complétez votre dossier avant la formation du {date_label}"
    if automatic_stage == 10 and today == deadline:
        subject = f"URGENT – Dernier jour pour compléter votre dossier : {deadline_label}"
        urgency = (
            f"La date limite de dépôt de vos documents est aujourd’hui, le {deadline_label}, "
            "soit 10 jours avant votre entrée en formation. Merci de déposer les éléments demandés "
            "sur votre espace stagiaire dès maintenant et au plus tard aujourd’hui."
        )
        sms_deadline = f"Date limite aujourd’hui, le {deadline_label} (10 jours avant l’entrée) : déposez-les dès maintenant."
    if today > deadline:
        urgency = (
            f"Votre dossier devait être complet au plus tard le {deadline_label}, soit 10 jours avant votre entrée en formation. "
            "Cette échéance étant dépassée, merci de déposer immédiatement les éléments demandés sur votre espace stagiaire."
        )
        sms_deadline = f"Échéance du {deadline_label} dépassée (10 jours avant l’entrée) : dépôt immédiat demandé."
    items = [f"{doc['label']} — {doc['action']}" + (f" : {doc['comment']}" if doc["comment"] else "") for doc in documents]
    sections = [f"Bonjour {first_name}," if first_name else "Bonjour,", intro, urgency]
    if items:
        sections.append("Documents et formulaires à fournir ou à corriger :\n" + "\n".join(f"- {item}" for item in items))
    if missing_information:
        sections.append("Informations à compléter dans votre espace :\n" + "\n".join(f"- {item}" for item in missing_information))
    sections.extend([
        f"Accéder à mon espace stagiaire : {portal_link}",
        "Merci de transmettre des documents complets et lisibles. Les pièces déjà déposées et en cours de vérification ne sont pas à renvoyer.",
        "Besoin d’assistance pour compléter votre dossier ? Contactez-nous au 04 22 47 07 68.",
        "L’équipe Intégrale Academy",
    ])
    text = "\n\n".join(sections)
    html_body = _email_html(first_name=first_name, training=training, date_label=date_label,
                            deadline_label=deadline_label, overdue=today > deadline, today_start=today == start_date,
                            intro=intro, urgency=urgency, portal_link=portal_link, documents=documents,
                            missing_information=missing_information, logo_url=logo_url)
    sms_items = "; ".join(f"{doc['label']} ({doc['action'].lower()})" for doc in documents)
    sms = f"Intégrale Academy – URGENT. Bonjour {first_name}, " if first_name else "Intégrale Academy – URGENT. "
    sms += f"votre formation {training} débute le {date_label}. Dossier incomplet. "
    if sms_items:
        sms += f"Documents : {sms_items}. "
    if missing_information:
        sms += "Informations à compléter : " + "; ".join(missing_information) + ". "
    sms += f"{sms_deadline} Espace stagiaire : {portal_link} Assistance : 04 22 47 07 68."
    return {"subject": subject, "text": text, "html": html_body, "sms": sms, "deadline": deadline.isoformat(), "documents": documents, "missing_information": missing_information}


def content_fingerprint(content):
    snapshot = {key: content.get(key, "") for key in ("subject", "text", "html", "sms", "email", "phone")}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
