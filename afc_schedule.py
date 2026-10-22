"""AFC APS + SSIAP calendars and individual enrolment dates.

Legacy AFC sessions are recognised without guessing their component dates.
All projections are copies: generating one trainee's documents must never
change the shared session or another trainee's dates.
"""
import datetime as dt
import hashlib
import json
import re


SESSION_DATES = {
    "afc_aps_start": "Début APS",
    "afc_aps_end": "Fin APS",
    "exam_date": "Examen APS",
    "afc_ssiap_start": "Début SSIAP 1",
    "afc_ssiap_end": "Fin SSIAP 1",
    "ssiap_exam_date": "Examen SSIAP 1",
}
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
    for key, label in {**SESSION_DATES, "date_start": "Début de session", "date_end": "Fin de session"}.items():
        if key in payload:
            result[key] = date(payload[key], label)
    merged.update(result)
    for prefix, label, exam in (("afc_aps", "APS", "exam_date"), ("afc_ssiap", "SSIAP 1", "ssiap_exam_date")):
        start, end = merged.get(prefix + "_start", ""), merged.get(prefix + "_end", "")
        _ordered(start, end, label)
        if merged.get(exam) and (end or start) and merged[exam] < (end or start):
            raise ValueError(f"L’examen {label} ne peut pas précéder la fin de cette formation.")
    # Global dates remain editable (e.g. additional AFC workshops). Derive
    # them from component dates only when no global period has been supplied.
    for key, candidates, operation in (
        ("date_start", ("afc_aps_start", "afc_ssiap_start"), min),
        ("date_end", ("afc_aps_end", "afc_ssiap_end"), max),
    ):
        values = [merged.get(k) for k in candidates if merged.get(k)]
        if not merged.get(key) and values:
            result[key] = merged[key] = operation(values)
    _ordered(merged.get("date_start"), merged.get("date_end"), "Session AFC")
    return result


def trainee_update(training, trainee, payload):
    if not any(key in payload for key in TRAINEE_DATES):
        return {}
    if not enabled(training):
        raise ValueError("Les dates individuelles sont disponibles pour les sessions AFC APS + SSIAP 1.")
    result = {key: date(payload[key], label) for key, label in TRAINEE_DATES.items() if key in payload}
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
        "date_end": trainee.get("training_date_end") or training.get("date_end") or training.get("date_fin") or "",
    }


def document_context(training, trainee, fr_date, *, strict=False):
    if not enabled(training):
        return {}
    if strict:
        missing = [label for key, label in SESSION_DATES.items() if not training.get(key)]
        if missing:
            raise ValueError("Complétez le calendrier AFC dans la session : " + ", ".join(missing) + ".")
        session_update(training, {key: training.get(key) for key in SESSION_DATES})
        trainee_update(training, trainee, {key: trainee.get(key, "") for key in TRAINEE_DATES})
    effective = effective_session(training, trainee)
    def period(start, end):
        return f"du {fr_date(start)} au {fr_date(end)}" if start and end else "À renseigner"
    aps = period(training.get("afc_aps_start"), training.get("afc_aps_end"))
    ssiap = period(training.get("afc_ssiap_start"), training.get("afc_ssiap_end"))
    aps_exam = fr_date(training.get("exam_date") or "") or "À renseigner"
    ssiap_exam = fr_date(training.get("ssiap_exam_date") or "") or "À renseigner"
    return {
        "formation_nom": TITLE, "nom_pedagogique": TITLE,
        "date_debut_formation": fr_date(effective["date_start"]),
        "date_fin_formation": fr_date(effective["date_end"]),
        "date_debut": fr_date(effective["date_start"]), "date_fin": fr_date(effective["date_end"]),
        "date_convocation": fr_date(effective["date_start"]),
        "periode_formation": period(effective["date_start"], effective["date_end"]),
        "periode_aps": aps, "periode_ssiap": ssiap,
        "date_examen_aps": aps_exam, "date_examen_ssiap": ssiap_exam,
        "detail_parcours": f"APS : {aps}\nExamen APS : {aps_exam}\nSSIAP 1 : {ssiap}\nExamen SSIAP 1 : {ssiap_exam}",
    }


def revision(training, trainee):
    if not enabled(training):
        return ""
    value = {"session": view(training), "period": {
        key: effective_session(training, trainee).get(key) for key in ("date_start", "date_end")},
        "trainee": trainee.get("id")}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]
