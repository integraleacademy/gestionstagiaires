"""Individual SSIAP enrolment schedules; legacy sessions remain unchanged."""
import datetime as dt
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation


MAINTENANCE = {
    "recyclage": {
        "label": "Recyclage SSIAP 1", "days": 2, "price": "250",
        "programme": "Prévention (5 h), moyens de secours (3 h) et mises en situation d’intervention (6 h).",
        "objectives": "Actualiser ses connaissances en prévention et intervenir avec les moyens de secours adaptés.",
        "requirements": "Diplôme SSIAP 1 ou équivalent, secourisme en cours de validité, échéance triennale respectée et justificatif de 1 607 h d’activité sur les 36 derniers mois.",
        "certificate": "Attestation de recyclage SSIAP 1",
    },
    "remise_a_niveau": {
        "label": "Remise à niveau SSIAP 1", "days": 3, "price": "350",
        "programme": "Fondamentaux (3 h), exploitation du PC sécurité (2 h), rondes (2 h), prévention (5 h), moyens de secours (3 h) et mises en situation d’intervention (6 h).",
        "objectives": "Reprendre les fondamentaux, exploiter le poste de sécurité, effectuer les rondes et intervenir en équipe.",
        "requirements": "Diplôme SSIAP 1 ou équivalent et secourisme en cours de validité. Certificat médical de moins de trois mois pour le personnel qui n’exerce pas dans un service de sécurité incendie.",
        "certificate": "Attestation de remise à niveau SSIAP 1",
    },
}
CHOICES = {"ssiap": "SSIAP seul", "ssiap_sst": "SSIAP + SST",
           **{key: course["label"] for key, course in MAINTENANCE.items()}}
# Annexe 1 du courrier IA/SSIAP/2027-02 (Puget-sur-Argens).
PUGET_2027 = ("2027-02-24", "2027-06-02", "2027-09-22", "2027-11-17")
PUGET_VENUE = "Intégrale Academy · 54 chemin du Carreou, 83480 Puget-sur-Argens"
MAINTENANCE_SCHEDULE = "9 h à 12 h et 13 h à 17 h"
DEFAULTS = {
    "ssiap_hours": "70", "sst_hours": "14",
    "ssiap_schedule": "08h30–12h30 / 13h30–16h30",
    "sst_schedule": "08h30–12h30 / 13h30–16h30",
    "ssiap_price": "", "ssiap_sst_price": "", "sst_dates": [],
}


def supported(training):
    return str(training.get("training_type") or training.get("type_formation") or training.get("type") or "").upper().startswith("SSIAP")


def level_one(training):
    name = " ".join(str(training.get(k) or "") for k in ("training_type", "type_formation", "type", "name", "nom")).upper()
    return supported(training) and not re.search(r"SSIAP\s*[- ]?[23]\b|\b(?:APS|AFC)\b", name)


def short_course(trainee):
    return (trainee or {}).get("ssiap_pathway") in MAINTENANCE


def suggested_choice(title):
    words = unicodedata.normalize("NFKD", str(title or "").casefold())
    words = "".join(c for c in words if not unicodedata.combining(c))
    if re.search(r"ssiap\s*[- ]?1\b", words):
        if re.search(r"remise\s+a\s+niveau|\bran\b", words):
            return "remise_a_niveau"
        if re.search(r"\brecycl", words):
            return "recyclage"
    return ""


def group_period(training):
    return training.get("_ssiap_group_period") or (
        training.get("date_start") or training.get("date_debut") or "",
        training.get("date_end") or training.get("date_fin") or "",
    )


def scheduled_defaults(training):
    result = {key + "_dates": [] for key in MAINTENANCE}
    center = str(training.get("crm_center") or training.get("center") or training.get("centre") or "").casefold()
    if (not level_one(training) or (center and not any(tag in center for tag in ("puget", "azur", "83480", "var")))
            or training.get("partner_id") not in
            (None, "", "11111111-1111-4111-8111-111111111111")):
        return result
    start, end = group_period(training)
    for iso in PUGET_2027:
        first = dt.date.fromisoformat(iso)
        days = [(first + dt.timedelta(days=i)).isoformat() for i in range(3)]
        if start <= days[0] and days[-1] <= end:
            return {"remise_a_niveau_dates": days, "recyclage_dates": days[1:]}
    return result


def enabled(training):
    return supported(training) and isinstance(training.get("ssiap_pathways"), dict)


def settings(training):
    return {**DEFAULTS, **scheduled_defaults(training),
            **{key + "_price": spec["price"] for key, spec in MAINTENANCE.items()},
            **(training.get("ssiap_pathways") or {})}


def number(value, label, *, optional=False):
    raw = str(value if value is not None else "").strip().replace(",", ".")
    if not raw and optional:
        return ""
    try:
        result = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"{label} : nombre invalide.")
    if not result.is_finite() or result < 0 or (not optional and result == 0):
        raise ValueError(f"{label} : valeur invalide.")
    return format(result.normalize(), "f")


def date(value, label):
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except (ValueError, TypeError):
        raise ValueError(f"{label} : date manquante ou invalide.")


def validate(training, values):
    if not supported(training) or not isinstance(values, dict):
        raise ValueError("Ces parcours sont réservés aux sessions SSIAP.")
    start, end = (date(v, "Période SSIAP") for v in group_period(training))
    if end < start:
        raise ValueError("La fin du SSIAP doit suivre son début.")
    raw_dates = values.get("sst_dates") or []
    if not isinstance(raw_dates, list) or len(raw_dates) > 10:
        raise ValueError("Renseignez une liste de dates SST (10 au maximum).")
    dates = sorted({date(d, "Journée SST") for d in raw_dates if d})
    result = {"sst_dates": dates}
    if level_one(training):
        current = settings(training)
        for key, spec in MAINTENANCE.items():
            field = key + "_dates"
            raw = values.get(field, current[field])
            if not isinstance(raw, list):
                raise ValueError(f"Vérifiez les dates du parcours {spec['label']}.")
            days = sorted(date(day, spec["label"]) for day in raw if day)
            if days and (len(set(days)) != spec["days"] or len(days) != spec["days"]
                         or days[0] < start or days[-1] > end):
                raise ValueError(f"{spec['label']} : choisissez {spec['days']} journées distinctes dans la session.")
            result[field] = days
    for key, label in [("ssiap_hours", "Durée SSIAP"), ("sst_hours", "Durée SST")]:
        result[key] = number(values.get(key, DEFAULTS[key]), label)
    for key in ("ssiap_price", "ssiap_sst_price"):
        result[key] = number(values.get(key, ""), "Tarif", optional=True)
    for key in ("ssiap_schedule", "sst_schedule"):
        result[key] = str(values.get(key) or DEFAULTS[key]).strip()
        if len(result[key]) > 100:
            raise ValueError("Les horaires doivent tenir sur 100 caractères.")
    return result


def selected(trainee):
    return trainee.get("ssiap_pathway") or "ssiap"


def validate_choice(training, choice):
    if not supported(training) or choice not in CHOICES:
        raise ValueError("Choisissez un parcours SSIAP disponible.")
    if choice in MAINTENANCE:
        if not level_one(training):
            raise ValueError("Ce parcours est réservé au SSIAP 1.")
        if not settings(training)[choice + "_dates"]:
            raise ValueError(f"Renseignez les journées de {CHOICES[choice]} dans les paramètres de la session.")
    if choice == "ssiap_sst" and (not enabled(training) or not settings(training)["sst_dates"]):
        raise ValueError("Renseignez d’abord les journées SST dans les paramètres de la session.")


def resolve(training, trainee, *, strict=False):
    choice = selected(trainee)
    if not enabled(training) and not (choice in MAINTENANCE and level_one(training)):
        return None
    config = settings(training)
    if strict:
        validate_choice(training, choice)
        config.update(validate(training, config))
    if choice in MAINTENANCE:
        spec = MAINTENANCE[choice]
        days = config[choice + "_dates"]
        start, end = (days[0], days[-1]) if days else ("", "")
        hours = str(spec["days"] * 7)
        return {**config, **spec, "choice": choice, "title": spec["label"], "with_sst": False,
                "short": True, "dates": days, "sst_dates": [], "ssiap_start": start, "ssiap_end": end,
                "date_start": start, "date_end": end, "total_hours": hours, "ssiap_hours": hours,
                "ssiap_schedule": MAINTENANCE_SCHEDULE}
    with_sst = choice == "ssiap_sst"
    dates = config["sst_dates"] if with_sst else []
    start, end = group_period(training)
    all_dates = [d for d in [start, end, *dates] if d]
    total = Decimal(config["ssiap_hours"]) + (Decimal(config["sst_hours"]) if with_sst else 0)
    return {
        **config, "choice": choice, "label": CHOICES.get(choice, CHOICES["ssiap"]),
        "title": "Agent de sécurité incendie SSIAP 1" + (" + Sauveteur secouriste du travail (SST)" if with_sst else ""),
        "with_sst": with_sst, "sst_dates": dates,
        "ssiap_start": start, "ssiap_end": end,
        "date_start": min(all_dates) if all_dates else "", "date_end": max(all_dates) if all_dates else "",
        "total_hours": format(total.normalize(), "f"),
        "price": config[choice + "_price"],
    }


def effective_session(training, trainee):
    path = resolve(training, trainee)
    if path is None:
        return training
    return {**training, "_ssiap_group_period": group_period(training),
            **({"exam_date": "", "date_examen": "", "ssiap_exam_date": ""} if path.get("short") else {}),
            "date_start": path["date_start"], "date_end": path["date_end"],
            "name": path["title"], "_ssiap_pathway_label": path["label"]}


def document_context(training, trainee, fr_date):
    path = resolve(training, trainee, strict=True)
    if path is None:
        return {}
    ssiap_period = f"du {fr_date(path['ssiap_start'])} au {fr_date(path['ssiap_end'])}"
    sst_dates = " et ".join(fr_date(d) for d in path["sst_dates"])
    detail = f"SSIAP 1 : {ssiap_period} — {path['ssiap_hours']} h"
    if path["with_sst"]:
        detail += f"\nSST : {sst_dates} — {path['sst_hours']} h"
    context = {
        "formation_nom": path["title"], "nom_pedagogique": path["title"],
        "parcours_label": path["label"], "detail_parcours": detail,
        "date_debut_formation": fr_date(path["date_start"]), "date_fin_formation": fr_date(path["date_end"]),
        "date_debut": fr_date(path["date_start"]), "date_fin": fr_date(path["date_end"]),
        "date_convocation": fr_date(path["date_start"]),
        "periode_formation": f"du {fr_date(path['date_start'])} au {fr_date(path['date_end'])}",
        "periode_ssiap": ssiap_period, "dates_sst": sst_dates,
        "horaires_ssiap": path["ssiap_schedule"], "horaires_sst": path["sst_schedule"],
        "h_ssiap": path["ssiap_hours"], "h_sst": path["sst_hours"] if path["with_sst"] else "0",
        "h_total": path["total_hours"], "h_presentiel": path["total_hours"], "h_elearning": "0",
        "avec_sst": path["with_sst"],
    }
    if path.get("short"):
        dates_label = ", ".join(fr_date(d) for d in path["dates"])
        venue = (str(trainee.get("lieu_formation") or "").strip()
                 or str(training.get("lieu_formation") or "").strip() or PUGET_VENUE)
        puget_map = bool(re.search(r"\b54[\s,]+(?:chemin|ch\.?)\s+du\s+carr[ée]ou\b", venue, re.I)
                         and re.search(r"\b83480\b|\bpuget[\s-]+sur[\s-]+argens\b", venue, re.I))
        context.update(maintien_ssiap=True, jours_parcours=path["days"], plan_acces_puget=puget_map,
                       lieu_formation=venue, detail_parcours=f"{path['label']} · {path['total_hours']} h · {dates_label}",
                       dates_parcours=dates_label, periode_formation=dates_label,
                       programme_parcours=path["programme"], objectifs_parcours=path["objectives"],
                       prerequis_parcours=path["requirements"], attestation_parcours=path["certificate"],
                       diplome_origine=trainee.get("ssiap_original_diploma") or "",
                       date_naissance=fr_date(trainee.get("birth_date") or ""),
                       lieu_naissance=trainee.get("birth_city") or "", date_examen="")
    return context


def attendance_complete(training, trainee):
    path = resolve(training, trainee)
    if not path or not path.get("short"):
        return False
    attendance = trainee.get("ssiap_attendance") or {}
    return bool(path["dates"]) and all(attendance.get(day) == "present" for day in path["dates"])


def expected_on(training, trainee, day):
    try:
        when = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return False
    choice = selected(trainee)
    config = settings(training)
    if choice in MAINTENANCE:
        return day in config[choice + "_dates"]
    start, end = group_period(training)
    return (start <= day <= end and when.weekday() < 5
            or choice == "ssiap_sst" and day in config["sst_dates"])


def check_attestation(training, trainee):
    if not attendance_complete(training, trainee):
        raise ValueError("Validez la présence pour chaque journée du parcours avant d’éditer l’attestation.")
    if not all(str(trainee.get(k) or "").strip() for k in ("ssiap_original_diploma", "birth_date", "birth_city")):
        raise ValueError("Complétez le numéro du diplôme SSIAP d’origine, la date et le lieu de naissance.")


def choice_options(training, trainee=None):
    config = settings(training)
    result = []
    for key, label in CHOICES.items():
        if key in MAINTENANCE and not level_one(training):
            continue
        days = config.get(key + "_dates", []) if key in MAINTENANCE else []
        allowed = bool(days) if key in MAINTENANCE else key == "ssiap" or bool(config["sst_dates"])
        result.append({"key": key, "label": label, "price": config[key + "_price"], "dates": days,
                       "available": allowed, "selected": key == selected(trainee or {}),
                       "days": MAINTENANCE.get(key, {}).get("days")})
    return result


def association_options(training, trainee):
    if not level_one(training):
        return []
    options = choice_options(training, trainee)
    for option in options:
        path = resolve(training, {"ssiap_pathway": option["key"]})
        start, end = group_period(training)
        if path:
            start, end = path["date_start"], path["date_end"]
        option.update(start=start, end=end)
    return options


def revision(training, trainee):
    path = resolve(training, trainee)
    if path is None:
        return ""
    value = {"path": path, "session": training.get("id"), "trainee": trainee.get("id"),
             "exam": training.get("exam_date"), "price": trainee.get("training_price")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:12]
