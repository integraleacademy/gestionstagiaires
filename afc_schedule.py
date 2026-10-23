"""One AFC training period, two exam dates and individual enrolment dates.

APS and SSIAP 1 are included in the same overall AFC training period.
All projections are copies: generating one trainee's documents must never
change the shared session or another trainee's dates.
"""
import datetime as dt
import hashlib
import json
import re


SESSION_DATES = {
    "exam_date": "Examen APS",
    "ssiap_exam_date": "Examen SSIAP 1",
}
PERIOD_DATES = {"date_start": "Début de formation", "date_end": "Fin de formation"}
TRAINEE_DATES = {
    "training_date_start": "Début de formation du stagiaire",
    "training_date_end": "Fin de formation du stagiaire",
}
TITLE = "AFC APS + SSIAP 1"


def enabled(training):
    if "afc_enabled" in training:
        return training["afc_enabled"] is True
    name = str(training.get("name") or training.get("nom") or "").upper()
    kind = str(training.get("training_type") or training.get("type") or "").upper()
    return bool(re.search(r"\bAFC\b", name) and ("APS" in kind or "APS" in name))


def date(value, label):
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise ValueError(f"{label} : date invalide.")
    try:
        return dt.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{label} : date invalide.") from None


def _ordered(start, end, label):
    if start and end and end < start:
        raise ValueError(f"{label} : la date de fin doit suivre la date de début.")


def session_update(training, payload):
    """Validate a partial update completely before mutating persistent data."""
    result = {}
    if "afc_enabled" in payload:
        if not isinstance(payload["afc_enabled"], bool):
            raise ValueError("Le choix du parcours AFC est invalide.")
        result["afc_enabled"] = payload["afc_enabled"]
    merged = {**training, **payload, **result}
    if not enabled(merged):
        return result
    for key, label in {**SESSION_DATES, **PERIOD_DATES}.items():
        if key in payload:
            result[key] = date(payload[key], label)
    merged.update(result)
    # Exams can occur during the overall AFC period. Retired component
    # dates, if present on older records, never constrain this calendar.
    _ordered(merged.get("date_start"), merged.get("date_end"), "Session AFC")
    return result


def trainee_update(training, trainee, payload):
    if not any(key in payload for key in TRAINEE_DATES):
        return {}
    if not enabled(training):
        raise ValueError("Les dates individuelles sont disponibles pour les sessions AFC APS + SSIAP 1.")
    # Retire individual end dates, including values sent by an older open form.
    # The empty stored value always follows subsequent session end-date changes.
    result = {"training_date_end": ""}
    if "training_date_start" in payload:
        result["training_date_start"] = date(payload["training_date_start"], TRAINEE_DATES["training_date_start"])
    effective = effective_session(training, {**trainee, **result})
    _ordered(effective.get("date_start"), effective.get("date_end"), "Période du stagiaire")
    return result


def view(training):
    return {"afc_enabled": enabled(training), **{key: training.get(key) or "" for key in SESSION_DATES}}


def effective_session(training, trainee):
    if not enabled(training):
        return training
    return {
        **training, "afc_enabled": True,
        "date_start": trainee.get("training_date_start") or training.get("date_start") or training.get("date_debut") or "",
        "date_end": training.get("date_end") or training.get("date_fin") or "",
    }


def document_context(training, trainee, fr_date, *, strict=False):
    if not enabled(training):
        return {}
    effective = effective_session(training, trainee)
    if strict:
        required = {**PERIOD_DATES, **SESSION_DATES}
        missing = [label for key, label in required.items() if not effective.get(key)]
        if missing:
            raise ValueError("Complétez le calendrier AFC dans la session : " + ", ".join(missing) + ".")
        session_update(effective, {key: effective.get(key) for key in required})
        trainee_update(training, trainee, {key: trainee.get(key, "") for key in TRAINEE_DATES})
    def period(start, end):
        return f"du {fr_date(start)} au {fr_date(end)}" if start and end else "À renseigner"
    aps_exam = fr_date(training.get("exam_date") or "") or "À renseigner"
    ssiap_exam = fr_date(training.get("ssiap_exam_date") or "") or "À renseigner"
    return {
        "formation_nom": TITLE, "nom_pedagogique": TITLE,
        "date_debut_formation": fr_date(effective["date_start"]),
        "date_fin_formation": fr_date(effective["date_end"]),
        "date_debut": fr_date(effective["date_start"]), "date_fin": fr_date(effective["date_end"]),
        "date_convocation": fr_date(effective["date_start"]),
        "periode_formation": period(effective["date_start"], effective["date_end"]),
        "date_examen_aps": aps_exam, "date_examen_ssiap": ssiap_exam,
        "detail_parcours": f"Parcours AFC : APS + SSIAP 1\nExamen APS : {aps_exam}\nExamen SSIAP 1 : {ssiap_exam}",
    }


def revision(training, trainee):
    if not enabled(training):
        return ""
    value = {"session": view(training), "period": {
        key: effective_session(training, trainee).get(key) for key in ("date_start", "date_end")},
        "trainee": trainee.get("id")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]
