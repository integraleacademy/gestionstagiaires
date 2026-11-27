"""Teaching and examination terms for SSIAP supervisor and manager contracts."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# Arrêté du 2 mai 2005 modifié, articles 5 à 7 et annexes III, IV, IX et XII.
COURSES = {
    2: {
        "title": "Chef d’équipe de sécurité incendie et d’assistance à personnes",
        "hours": 70, "maximum": 12,
        "objectives": "Encadrer les agents, animer leur formation et diriger le poste de sécurité en situation de crise.",
        "requirements": "Qualification d’agent admise à l’article 4 § 2 de l’arrêté du 2 mai 2005, "
            "1 607 heures d’activité d’agent au cours des 24 derniers mois justifiées par l’employeur ou le contrat de travail, "
            "et certificat médical conforme à l’annexe VII datant de moins de trois mois.",
        "programme": "Encadrement de l’équipe et missions du chef d’équipe (38 h). "
            "Exploitation des systèmes de sécurité incendie (10 h). Hygiène, sécurité et commissions (6 h). "
            "Conduite du poste central en situation de crise (16 h).",
        "exams": "Un questionnaire écrit, l’animation d’une séquence pédagogique et une mise en situation au poste de sécurité.",
    },
    3: {
        "title": "Chef de service de sécurité incendie et d’assistance à personnes",
        "hours": 216, "maximum": 10,
        "objectives": "Diriger le service de sécurité incendie, conseiller le chef d’établissement et préparer les visites "
            "de la commission de sécurité. Organiser la prévention, encadrer l’équipe et gérer son budget.",
        "requirements": "Diplôme de niveau 4 ou supérieur, ou SSIAP 2 (ou ancien ERP 2 / IGH 2 délivré avant le "
            "31 décembre 2005) avec trois ans dans la fonction de chef d’équipe, justifiés par l’employeur ou le contrat de travail.",
        "programme": "Phénomènes du feu (12 h). Comportement des bâtiments (65 h). Réglementation incendie (70 h). "
            "Analyse et gestion des risques (23 h). Conseil au chef d’établissement (6 h). Relations avec les commissions "
            "de sécurité (6 h). Management du service (26 h). Gestion budgétaire, achats et maintenance (8 h).",
        "exams": "Un questionnaire écrit, la rédaction d’une notice technique de sécurité à partir de plans "
            "et un entretien oral avec le jury.",
    },
}
FIRST_AID = "Secourisme requis également : AFPS ou PSC de moins de deux ans, ou SST ou PSE 1 en cours de validité."


def level(training):
    # An explicit type takes precedence over a free-text session label.
    for key in ("training_type", "type_formation", "type", "name", "nom"):
        value = str(training.get(key) or "")
        match = re.search(r"\bS\.?S\.?I\.?A\.?P\.?\s*(?:[-–/]\s*)?(?:niveau\s*)?([123])\b", value, re.I)
        if match:
            return int(match[1])
    return 1


def combined_aps_ssiap(text):
    return bool(re.search(r"\bAPS\b", text, re.I)
                and re.search(r"\bSSIAP(?:[\s-]*1\b|(?![\s-]*[123])\b)", text, re.I))


def maintenance(training):
    name = " ".join(str(training.get(k) or "") for k in ("training_type", "type_formation", "name", "nom"))
    words = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    if re.search(r"remise a niveau|\bran\b", words):
        return "Remise à niveau"
    if re.search(r"recyclage|\brec\b", words):
        return "Recyclage"
    return ""


def title(number):
    return f"SSIAP {number} – {COURSES[number]['title']}"


def contract_terms(training, trainee, path, fr_date):
    number = level(training)
    course = COURSES[number]
    mode = maintenance(training)
    diploma = title(number)
    outcome = diploma
    name = path["title"] if path else diploma
    hours = path["total_hours"] if path else initial_hours(training, training.get("h_total"))
    programme = course["programme"]
    objectives = course["objectives"]
    requirements = course["requirements"] + " " + FIRST_AID
    assessment = course["exams"]
    award = f"Le jury délivre le diplôme SSIAP {number} après réussite aux trois épreuves."
    day = fr_date(trainee.get("date_examen") or training.get("ssiap_exam_date") or training.get("exam_date") or training.get("date_examen"))
    exam = f"Examen le {day}." if day else "La date de l’examen sera communiquée par le centre."
    if mode:
        name = f"{mode} SSIAP {number}"
        outcome = f"Attestation de {mode.lower()} SSIAP {number}"
        hours = str(({2: 14, 3: 21} if mode == "Recyclage" else {2: 21, 3: 35})[number])
        objectives = f"Actualiser les compétences nécessaires à l’exercice des fonctions de {course['title'].lower()}."
        requirements = f"Diplôme SSIAP {number} ou qualification équivalente. Conditions de l’article 7 de l’arrêté du 2 mai 2005. {FIRST_AID}"
        programme = f"Programme de {mode.lower()} de niveau {number} fixé à l’annexe XII de l’arrêté du 2 mai 2005 modifié."
        assessment = "Le formateur évalue les mises en situation et vérifie la participation aux séquences prévues."
        award = f"À l’issue du parcours, le centre remet une attestation de {mode.lower()} SSIAP {number}."
        exam = ""
    elif path and path["with_sst"]:
        programme += f" Module complémentaire de sauveteur secouriste du travail ({path['sst_hours']} h)."
    return dict(formation_nom=name, nom_pedagogique=name, ssiap_diplome=outcome, h_total=hours,
                objectifs_parcours=objectives, prerequis_parcours=requirements, programme_parcours=programme,
                evaluation_ssiap=assessment, validation_ssiap=award, examen_ssiap=exam,
                effectif_maximum=str(course["maximum"]))


def initial_hours(training, configured=None):
    number = level(training)
    if number not in COURSES:
        return configured or "70"
    # Older level-3 sessions may have inherited a 70-hour level-1 setting.
    minimum = COURSES[number]["hours"]
    value = str(configured or training.get("h_total") or minimum).replace(",", ".")
    try:
        hours = Decimal(value)
        if hours.is_finite() and hours >= minimum:
            return format(hours.normalize(), "f")
    except InvalidOperation:
        pass
    return str(minimum)
