"""Prévisualisation pure et sans écriture du rapprochement WEDOF/local."""

import datetime as dt
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: Any) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+33") and digits.startswith("33"):
        national = digits[2:]
        digits = national if national.startswith("0") else "0" + national
    elif digits.startswith("0033"):
        national = digits[4:]
        digits = national if national.startswith("0") else "0" + national
    return digits


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[’'`\-\s]+", " ", text)
    return text.strip()


def normalize_date(value: Any) -> Optional[str]:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def _nested(source: Dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = source
        for key in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value not in (None, ""):
            return value
    return ""


def extract_folder(folder: Dict[str, Any]) -> Dict[str, Any]:
    """Extrait la liste blanche de données autorisées (jamais le dossier brut)."""
    return {
        "external_id": folder.get("externalId") or "",
        "state": folder.get("state") or "",
        "type": folder.get("type") or "",
        "first_name": _nested(folder, "attendee.firstName", "attendee.firstname", "data.attendee.firstName", "firstName", "trainee.firstName"),
        "last_name": _nested(folder, "attendee.lastName", "attendee.lastname", "data.attendee.lastName", "lastName", "trainee.lastName"),
        "email": _nested(folder, "attendee.email", "data.attendee.email", "email", "trainee.email"),
        "phone": _nested(folder, "attendee.phoneNumber", "attendee.phone", "data.attendee.phoneNumber", "phoneNumber", "phone", "trainee.phoneNumber"),
        "start_date": _nested(folder, "trainingActionInfo.sessionStartDate", "trainingActionInfo.startDate", "trainingActionInfo.session.startDate", "data.trainingActionInfo.sessionStartDate", "session.startDate", "session.sessionStartDate", "session.dateStart", "startDate", "dateStart"),
        "end_date": _nested(folder, "trainingActionInfo.sessionEndDate", "trainingActionInfo.endDate", "trainingActionInfo.session.endDate", "data.trainingActionInfo.sessionEndDate", "session.endDate", "session.sessionEndDate", "session.dateEnd", "endDate", "dateEnd"),
        "training_title": _nested(folder, "trainingActionInfo.title", "trainingActionInfo.name", "data.trainingActionInfo.title", "session.title", "trainingTitle"),
        "training_duration": _nested(folder, "trainingActionInfo.trainingDuration", "trainingActionInfo.duration", "data.trainingActionInfo.trainingDuration", "trainingDuration"),
        "total_amount": _nested(folder, "pricing.totalAmount", "financing.totalAmount", "trainingActionInfo.price", "totalAmount"),
        "cpf_amount": _nested(folder, "pricing.cpfAmount", "financing.cpfAmount", "cpfAmount"),
        "france_travail_amount": _nested(folder, "pricing.franceTravailAmount", "financing.franceTravailAmount", "franceTravailAmount"),
        "candidate_amount": _nested(folder, "pricing.attendeeAmount", "financing.remainingAmount", "attendeeAmount", "remainingAmount"),
        "created_at": _nested(folder, "createdAt", "dateCreated", "data.createdAt"),
        "updated_at": _nested(folder, "updatedAt", "data.updatedAt"),
        "wedof_url": _nested(folder, "url", "links.web", "_links.web.href"),
        "waiting_reason": _nested(folder, "waitingReason", "pendingReason", "data.waitingReason"),
        "step_dates": _nested(folder, "stateDates", "statusHistory", "data.stateDates"),
    }


def find_candidate_sessions(sessions: Iterable[Dict[str, Any]], start: str, end: str) -> List[Dict[str, Any]]:
    candidates = []
    for session in sessions:
        archived = bool(session.get("archived") or session.get("is_archived")) or str(session.get("status") or "").casefold() in {"archived", "archivee", "archivée"}
        local_start = normalize_date(session.get("date_start") or session.get("date_debut"))
        local_end = normalize_date(session.get("date_end") or session.get("date_fin"))
        if not archived and local_start == start and local_end == end:
            candidates.append(session)
    return candidates


def _trainee_rule(wedof: Dict[str, Any], trainee: Dict[str, Any]) -> Optional[str]:
    email = normalize_email(wedof["email"])
    phone = normalize_phone(wedof["phone"])
    local_email = normalize_email(trainee.get("email") or trainee.get("mail"))
    local_phone = normalize_phone(trainee.get("phone") or trainee.get("telephone") or trainee.get("phone_number"))
    identity = (normalize_name(wedof["first_name"]) == normalize_name(trainee.get("first_name") or trainee.get("prenom")) and
                normalize_name(wedof["last_name"]) == normalize_name(trainee.get("last_name") or trainee.get("nom")))
    email_match = bool(email and local_email and email == local_email)
    phone_match = bool(phone and local_phone and phone == local_phone)
    if email_match and phone_match:
        return "email_phone_dates"
    if email_match and identity:
        return "email_identity_dates"
    if phone_match and identity:
        return "phone_identity_dates"
    return None


def find_trainee_cpf_candidates(
    folders: Iterable[Dict[str, Any]],
    session_obj: Dict[str, Any],
    trainee: Dict[str, Any],
    *,
    allowed_states: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Retourne les dossiers CPF ayant exactement le même e-mail et téléphone.

    La fonction reste pure et ne conserve que les champs explicitement extraits
    par :func:`extract_folder`. Une association automatique n'est considérée
    sûre que si l'identité *et* les deux dates concordent également.
    """
    local_email = normalize_email(trainee.get("email") or trainee.get("mail"))
    local_phone = normalize_phone(
        trainee.get("phone") or trainee.get("telephone") or trainee.get("phone_number")
    )
    if not local_email or not local_phone:
        return []

    local_first_name = normalize_name(trainee.get("first_name") or trainee.get("prenom"))
    local_last_name = normalize_name(trainee.get("last_name") or trainee.get("nom"))
    local_start = normalize_date(session_obj.get("date_start") or session_obj.get("date_debut"))
    local_end = normalize_date(session_obj.get("date_end") or session_obj.get("date_fin"))
    permitted = {str(value) for value in allowed_states} if allowed_states is not None else None

    candidates: List[Dict[str, Any]] = []
    for folder in folders:
        if not isinstance(folder, dict):
            continue
        remote = extract_folder(folder)
        state = str(remote.get("state") or "").strip()
        if (
            str(remote.get("type") or "").strip().casefold() != "cpf"
            or not str(remote.get("external_id") or "").strip()
            or (permitted is not None and state not in permitted)
        ):
            continue

        email_match = normalize_email(remote.get("email")) == local_email
        phone_match = normalize_phone(remote.get("phone")) == local_phone
        if not email_match or not phone_match:
            continue

        remote_first_name = normalize_name(remote.get("first_name"))
        remote_last_name = normalize_name(remote.get("last_name"))
        identity_complete = bool(
            local_first_name and local_last_name and remote_first_name and remote_last_name
        )
        identity_match = bool(
            identity_complete
            and remote_first_name == local_first_name
            and remote_last_name == local_last_name
        )
        remote_start = normalize_date(remote.get("start_date"))
        remote_end = normalize_date(remote.get("end_date"))
        dates_complete = bool(local_start and local_end and remote_start and remote_end)
        dates_match = bool(
            dates_complete and remote_start == local_start and remote_end == local_end
        )
        mismatches = []
        if not identity_match:
            mismatches.append("Identité WEDOF incomplète" if not identity_complete else "Identité différente")
        if not dates_match:
            mismatches.append("Dates WEDOF incomplètes" if not dates_complete else "Dates de formation différentes")

        candidates.append({
            **remote,
            "start_date": remote_start,
            "end_date": remote_end,
            "email_match": True,
            "phone_match": True,
            "identity_match": identity_match,
            "dates_match": dates_match,
            "all_fields_match": bool(identity_match and dates_match),
            "match_reasons": [
                "Même e-mail",
                "Même téléphone",
                *(["Même identité"] if identity_match else []),
                *(["Mêmes dates de formation"] if dates_match else []),
            ],
            "mismatches": mismatches,
        })

    candidates.sort(key=lambda item: (
        not item["all_fields_match"],
        not item["dates_match"],
        not item["identity_match"],
        str(item.get("start_date") or "9999-12-31"),
        str(item.get("external_id") or ""),
    ))
    return candidates


def match_folder(folder: Dict[str, Any], sessions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    wedof = extract_folder(folder)
    result = {**wedof, "session": "—", "trainee": "—", "rule": "—", "status": "", "explanation": ""}
    if str(wedof["type"]).strip().casefold() != "cpf":
        result.update(status="excluded_non_cpf", explanation="Le type WEDOF n’est pas explicitement CPF.")
        return result
    start, end = normalize_date(wedof["start_date"]), normalize_date(wedof["end_date"])
    has_contact = bool(normalize_email(wedof["email"]) or normalize_phone(wedof["phone"]))
    if not wedof["external_id"] or not normalize_name(wedof["first_name"]) or not normalize_name(wedof["last_name"]) or not has_contact or not start or not end:
        result.update(status="missing_wedof_data", explanation="Identifiant externalId, identité ou dates WEDOF manquants ou invalides.")
        return result
    result["start_date"], result["end_date"] = start, end
    candidates = find_candidate_sessions(sessions, start, end)
    if not candidates:
        result.update(status="no_session_match", explanation="Aucune session non archivée ne possède exactement ces deux dates.")
        return result
    matches = []
    for session in candidates:
        for trainee in session.get("trainees", session.get("stagiaires", [])) or []:
            rule = _trainee_rule(wedof, trainee)
            if rule:
                matches.append((session, trainee, rule))
    if not matches:
        result.update(status="no_trainee_match", explanation="Une session existe, mais aucun stagiaire ne satisfait une règle forte.",
                      session=_session_label(candidates[0]),
                      session_id=str(candidates[0].get("id") or "") if len(candidates) == 1 else "")
        return result
    if len(matches) > 1:
        result.update(status="ambiguous_match", explanation="Plusieurs couples session/stagiaire satisfont une règle forte.")
        return result
    session, trainee, rule = matches[0]
    result.update(status="exact_match", explanation="Un seul couple session/stagiaire satisfait une règle forte.",
                  session=_session_label(session), trainee=_trainee_label(trainee), rule=rule,
                  session_id=str(session.get("id") or ""), trainee_id=str(trainee.get("id") or ""))
    return result


def _session_label(session: Dict[str, Any]) -> str:
    return str(session.get("name") or session.get("title") or session.get("training_type") or session.get("id") or "Session trouvée")


def _trainee_label(trainee: Dict[str, Any]) -> str:
    return " ".join(filter(None, [str(trainee.get("first_name") or trainee.get("prenom") or "").strip(), str(trainee.get("last_name") or trainee.get("nom") or "").strip()])) or str(trainee.get("id") or "Stagiaire trouvé")


def build_matching_preview(folders: Iterable[Dict[str, Any]], data: Dict[str, Any]) -> Dict[str, Any]:
    results = [match_folder(folder, data.get("sessions", [])) for folder in folders if isinstance(folder, dict)]
    counts = {key: sum(item["status"] == key for item in results) for key in (
        "exact_match", "ambiguous_match", "no_session_match", "no_trainee_match", "missing_wedof_data", "excluded_non_cpf")}
    counts["cpf_analyzed"] = len(results) - counts["excluded_non_cpf"]
    return {"results": results, "counts": counts}
