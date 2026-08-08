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
        result.update(status="no_trainee_match", explanation="Une session existe, mais aucun stagiaire ne satisfait une règle forte.", session=_session_label(candidates[0]))
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
