"""Personalised exam letters for course booklets without a dedicated exam page."""

import re

import ssiap_qualifications
from .source import Block, Cell


def invitations(training, trainee, context, config, fr_date):
    template = config.get("convocation_template")
    family = context["convocation_famille"]
    if template not in ("convocationformation.docx", "convocationafc.docx", "convocationvtc.docx"):
        return None
    if context.get("maintien_ssiap") or ssiap_qualifications.maintenance(training) or family in ("sst", "habilitation", "mac_aps"):
        return None

    name = context.get("convocation_intitule") or context["formation_nom"]
    venue = context.get("convocation_site") or training.get("training_location") or training.get("crm_center") or ""
    if re.fullmatch(r"Puget(?:[ -]sur[ -]Argens)?|Côte d[’']Azur", venue.strip(), re.I):
        venue = context["lieu_formation"]
    rows = []

    def add(label, day, *, settings=None, kind="exam", instructions="", site=""):
        state = (training.get(settings) or {}) if settings else {}
        candidate = (state.get("candidates") or {}).get(str(trainee.get("id") or ""), {})
        if candidate.get("included") is False:
            return
        saved = state.get("config") or {}
        location = ", ".join(filter(None, (saved.get("location"), saved.get("address"))))
        day = fr_date(day) if day else ""
        time = saved.get("time") or ""
        # The common exam field in a combined session belongs to the APS examination.
        if not time and kind != "cma" and not (combined and settings == "ssiap_exam"):
            time = training.get("exam_time") or training.get("heure_examen") or ""
        rows.append(dict(label=label, day=day, kind=kind, instructions=instructions, time=time,
                         place=location or training.get("lieu_examen") or site))

    exam = training.get("exam_date") or training.get("date_examen")
    ssiap_day = training.get("ssiap_exam_date") or ((training.get("ssiap_exam") or {}).get("config") or {}).get("date")
    combined = config.get("slug") == "afc" or ssiap_qualifications.combined_aps_ssiap(" ".join(str(training.get(k) or "") for k in ("training_type", "type_formation", "name", "nom")))
    if combined:
        place = venue or context["lieu_formation"]
        add("APS", exam, settings="security_exam", site=place,
            instructions="Tenue d’examen APS : chemise blanche, veste et pantalon noirs, chaussures noires et cravate de sécurité.")
        add("SSIAP 1", ssiap_day, settings="ssiap_exam", site=place,
            instructions="Prévoyez un pantalon et des chaussures fermées adaptés aux épreuves pratiques.")
    elif family == "vtc":
        if trainee.get("vtc_offer") != "practice":
            add("Examen théorique VTC", training.get("exam_theory_date") or training.get("date_examen_theorique"), kind="cma")
        add("Examen pratique VTC", trainee.get("vtc_practice_exam_date") or training.get("exam_practice_date") or training.get("date_examen_pratique") or exam, kind="cma")
    elif family == "ssiap":
        number = ssiap_qualifications.level(training)
        course = ssiap_qualifications.COURSES.get(number, {})
        add(f"SSIAP {number}", ssiap_day or exam, settings="ssiap_exam", site=venue or context["lieu_formation"],
            instructions=course.get("exams", ""))
    elif family == "vae":
        add(name, exam, kind="jury", site=venue)
    elif exam:
        add(name, exam, site=venue)
    return rows


def add_pages(source, exams, person):
    position = 2
    if exams is None:
        return
    if len(source.pages) > position and "CALENDRIER DES EXAMENS" in source.pages[position][:2]:
        del source.pages[position]
        del source.blocks[position]
    if not exams:
        return

    def block(*lines):
        return Block([[Cell(list(lines), [])]])

    def fields(*pairs):
        return Block([[Cell([label, value], []) for label, value in pairs]])

    training_letter = source.blocks[1]
    signature = training_letter[-1]
    dated = next((b for b in reversed(training_letter) if b.text and b.text[0].startswith("Fait à ")), None)
    for exam in exams:
        label, date, kind = exam["label"], exam["day"], exam["kind"]
        if kind == "cma":
            title = "Informations sur l’examen VTC"
            invite = "La Chambre de métiers et de l’artisanat vous adresse votre convocation officielle. Présentez-la le jour de l’épreuve. Elle précise votre horaire de passage et votre centre d’examen."
        elif not date:
            title = "Examen à programmer" if kind != "jury" else "Jury à programmer"
            invite = "Nous vous adresserons votre convocation dès que la date de passage aura été confirmée."
        elif kind == "jury":
            title = "Convocation officielle au jury"
            invite = "Nous vous convoquons devant le jury de validation des acquis de l’expérience."
        else:
            title = "Convocation officielle à l’examen"
            invite = f"Nous vous convoquons à l’examen {label}."
        section = [block(label, title), block(label), block(person), block(invite)]
        section.append(fields(("Date de l’épreuve", date or "Date à confirmer"),
                              ("Heure de passage", exam["time"] or ("Voir la convocation de la CMA" if kind == "cma" else "Horaire à confirmer par le centre"))))
        section.append(fields(("Lieu de l’épreuve", exam["place"] or ("Voir la convocation de la CMA" if kind == "cma" else "Lieu à confirmer par le centre"))))
        if exam["instructions"]:
            section.append(block(exam["instructions"]))
        if kind != "cma" and date:
            section.append(block("Merci de vous présenter avec cette convocation et une pièce d’identité en cours de validité."))
        if dated:
            section.append(dated)
        section.append(signature)
        source.blocks.insert(position, section)
        source.pages.insert(position, [line for item in section for line in item.text])
        position += 1
