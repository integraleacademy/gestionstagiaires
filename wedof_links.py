"""Persistance minimale des correspondances fiables WEDOF/locales."""

import datetime as dt
import secrets
from typing import Any, Dict, Iterable, Optional

from wedof_matching import normalize_date


ALLOWED_STATES = {"accepted", "inTraining"}


def evaluate_wedof_link_date_consistency(
    link: Dict[str, Any], local_session: Dict[str, Any], current_wedof_folder: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Calcule le contrôle de dates sans écriture ni appel HTTP."""
    local_start = normalize_date(local_session.get("date_start") or local_session.get("date_debut"))
    local_end = normalize_date(local_session.get("date_end") or local_session.get("date_fin"))
    folder = current_wedof_folder if isinstance(current_wedof_folder, dict) else None
    if folder is not None:
        info = folder.get("trainingActionInfo") if isinstance(folder.get("trainingActionInfo"), dict) else {}
        remote_start = normalize_date(folder.get("start_date") or folder.get("startDate") or info.get("startDate"))
        remote_end = normalize_date(folder.get("end_date") or folder.get("endDate") or info.get("endDate"))
    else:
        remote_start = normalize_date(link.get("wedof_date_start"))
        remote_end = normalize_date(link.get("wedof_date_end"))
    result = {
        "local_date_start": local_start, "local_date_end": local_end,
        "wedof_date_start": remote_start, "wedof_date_end": remote_end,
    }
    if not all((local_start, local_end, remote_start, remote_end)):
        result.update(status="dates_unverifiable", date_gate_ok=False,
                      block_reason="wedof_dates_unverifiable")
    elif (local_start, local_end) != (remote_start, remote_end):
        result.update(status="date_mismatch", date_gate_ok=False,
                      block_reason="wedof_local_dates_mismatch")
    else:
        result.update(status="dates_match", date_gate_ok=True, block_reason=None)
    return result


def evaluate_wedof_date_gate(link: Dict[str, Any], session: Dict[str, Any],
                             current_wedof_folder: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retourne la barrière réutilisable des futures automatisations."""
    consistency = evaluate_wedof_link_date_consistency(link, session, current_wedof_folder)
    # La validation des dates ne suffit pas à autoriser une déclaration : le futur
    # traitement vérifiera aussi l’état WEDOF, démarrage, assiduité, sortie et idempotence.
    return {"allowed": consistency["date_gate_ok"], "reason": consistency["block_reason"]}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _local_registration_exists(data: Dict[str, Any], session_id: str, trainee_id: str) -> bool:
    for session in data.get("sessions", []) or []:
        if not isinstance(session, dict) or str(session.get("id") or "") != session_id:
            continue
        trainees = session.get("trainees", session.get("stagiaires", [])) or []
        return any(isinstance(item, dict) and str(item.get("id") or "") == trainee_id for item in trainees)
    return False


def sync_exact_wedof_links(
    data: Dict[str, Any], matching_results: Iterable[Dict[str, Any]], *, now: Optional[str] = None
) -> Dict[str, int]:
    """Synchronise une liste blanche de champs; ne conserve jamais le dossier brut."""
    links = data.get("wedof_links")
    if not isinstance(links, list):
        links = []
        data["wedof_links"] = links
    summary = {"created": 0, "already_linked": 0, "updated": 0, "conflicts": 0, "skipped": 0}
    timestamp = now or _now_iso()
    for result in matching_results:
        if not isinstance(result, dict) or result.get("status") != "exact_match":
            summary["skipped"] += 1
            continue
        external_id = str(result.get("external_id") or "").strip()
        session_id = str(result.get("session_id") or "").strip()
        trainee_id = str(result.get("trainee_id") or "").strip()
        state = str(result.get("state") or "").strip()
        if (str(result.get("type") or "").strip().casefold() != "cpf" or not external_id
                or state not in ALLOWED_STATES
                or not _local_registration_exists(data, session_id, trainee_id)):
            summary["skipped"] += 1
            continue
        active = [link for link in links if isinstance(link, dict) and link.get("active") is True]
        by_external = next((link for link in active if str(link.get("external_id")) == external_id), None)
        by_registration = next((link for link in active if str(link.get("session_id")) == session_id
                                and str(link.get("trainee_id")) == trainee_id), None)
        if by_external or by_registration:
            if by_external is by_registration and by_external is not None:
                old_state = by_external.get("wedof_state")
                by_external["wedof_state"] = state
                by_external["updated_at"] = timestamp
                by_external["last_seen_at"] = timestamp
                summary["already_linked"] += 1
                if old_state != state:
                    summary["updated"] += 1
            else:
                summary["conflicts"] += 1
            continue
        links.append({
            "id": "WLINK-" + secrets.token_hex(4).upper(),
            "external_id": external_id,
            "session_id": session_id,
            "trainee_id": trainee_id,
            "source": "automatic_exact_match",
            "matching_rule": str(result.get("rule") or ""),
            "wedof_state": state,
            "wedof_type": "cpf",
            "wedof_date_start": str(result.get("start_date") or "")[:10],
            "wedof_date_end": str(result.get("end_date") or "")[:10],
            "active": True,
            "created_at": timestamp,
            "updated_at": timestamp,
            "last_seen_at": timestamp,
        })
        summary["created"] += 1
    return summary


def local_association_status(result: Dict[str, Any], links: Iterable[Dict[str, Any]]) -> str:
    external_id, session_id, trainee_id = (str(result.get(key) or "") for key in ("external_id", "session_id", "trainee_id"))
    active = [item for item in links if isinstance(item, dict) and item.get("active") is True]
    same = next((item for item in active if str(item.get("external_id")) == external_id), None)
    if same:
        if same.get("source") == "manual_admin":
            return "Associée manuellement"
        if (not session_id or not trainee_id or
                (str(same.get("session_id")) == session_id and str(same.get("trainee_id")) == trainee_id)):
            return "Déjà enregistrée automatiquement"
    if result.get("status") != "exact_match":
        return "Non associable automatiquement"
    registration = next((item for item in active if str(item.get("session_id")) == session_id and str(item.get("trainee_id")) == trainee_id), None)
    if same and same is registration:
        return "Déjà enregistrée automatiquement"
    if same or registration:
        return "Conflit avec une association existante"
    return "Nouvelle correspondance fiable"


def save_manual_wedof_link(data: Dict[str, Any], *, external_id: str, session_id: str,
                           trainee_id: str, state: str, date_start: Optional[str],
                           date_end: Optional[str], now: Optional[str] = None) -> str:
    """Crée un lien manuel après validation, avec les mêmes règles d'unicité."""
    links = data.setdefault("wedof_links", [])
    if not isinstance(links, list):
        links = []
        data["wedof_links"] = links
    active = [item for item in links if isinstance(item, dict) and item.get("active") is True]
    by_external = next((item for item in active if str(item.get("external_id")) == external_id), None)
    by_registration = next((item for item in active if str(item.get("session_id")) == session_id
                            and str(item.get("trainee_id")) == trainee_id), None)
    timestamp = now or _now_iso()
    if by_external or by_registration:
        if by_external is by_registration and by_external is not None:
            by_external["wedof_state"] = state
            by_external["updated_at"] = timestamp
            by_external["last_seen_at"] = timestamp
            return "already_linked"
        return "conflict"
    links.append({
        "id": "WLINK-" + secrets.token_hex(4).upper(), "external_id": external_id,
        "session_id": session_id, "trainee_id": trainee_id, "source": "manual_admin",
        "matching_rule": "manual_selection", "wedof_state": state, "wedof_type": "cpf",
        "wedof_date_start": date_start, "wedof_date_end": date_end, "active": True,
        "created_at": timestamp, "updated_at": timestamp, "last_seen_at": timestamp,
    })
    return "created"
