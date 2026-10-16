"""Individual SSIAP enrolment schedules; legacy sessions remain unchanged."""
import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation


CHOICES = {"ssiap": "SSIAP seul", "ssiap_sst": "SSIAP + SST"}
DEFAULTS = {
    "ssiap_hours": "70", "sst_hours": "14",
    "ssiap_schedule": "08h30–12h30 / 13h30–16h30",
    "sst_schedule": "08h30–12h30 / 13h30–16h30",
    "ssiap_price": "", "ssiap_sst_price": "", "sst_dates": [],
}


def supported(training):
    return str(training.get("training_type") or training.get("type") or "").upper().startswith("SSIAP")


def enabled(training):
    return supported(training) and isinstance(training.get("ssiap_pathways"), dict)


def settings(training):
    return {**DEFAULTS, **(training.get("ssiap_pathways") or {})}


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
    start = date(training.get("date_start"), "Début SSIAP")
    end = date(training.get("date_end"), "Fin SSIAP")
    if end < start:
        raise ValueError("La fin du SSIAP doit suivre son début.")
    raw_dates = values.get("sst_dates") or []
    if not isinstance(raw_dates, list) or len(raw_dates) > 10:
        raise ValueError("Renseignez une liste de dates SST (10 au maximum).")
    dates = sorted({date(d, "Journée SST") for d in raw_dates if d})
    result = {"sst_dates": dates}
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
        raise ValueError("Choisissez SSIAP seul ou SSIAP + SST.")
    if choice == "ssiap_sst" and (not enabled(training) or not settings(training)["sst_dates"]):
        raise ValueError("Renseignez d’abord les journées SST dans les paramètres de la session.")


def resolve(training, trainee, *, strict=False):
    if not enabled(training):
        return None
    config = settings(training)
    choice = selected(trainee)
    if strict:
        validate_choice(training, choice)
        config = validate(training, config)
    with_sst = choice == "ssiap_sst"
    dates = config["sst_dates"] if with_sst else []
    start = str(training.get("date_start") or training.get("date_debut") or "")
    end = str(training.get("date_end") or training.get("date_fin") or "")
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
    return {**training, "date_start": path["date_start"], "date_end": path["date_end"],
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
    return {
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


def revision(training, trainee):
    path = resolve(training, trainee)
    if path is None:
        return ""
    value = {"path": path, "session": training.get("id"), "trainee": trainee.get("id"),
             "exam": training.get("exam_date"), "price": trainee.get("training_price")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:12]
