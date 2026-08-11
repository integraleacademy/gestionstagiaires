"""Présentation et règles métier du suivi CPF à partir des instantanés WEDOF.

Ce module ne réalise aucun appel HTTP : il centralise le mapping des états et
transforme uniquement les données WEDOF mises en cache par l'application.
"""

import datetime as dt
import re
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
CPF_STEPS = (
    "En attente d’acceptation", "Accepté", "En formation",
    "Service fait déclaré", "Service fait validé", "Facturé",
)

# Les valeurs sont les états techniques réellement rencontrés dans l'API EDOF/WEDOF.
# Un état absent de cette table reste volontairement non classé.
WEDOF_STATUS_TO_STEP = {
    "pending": 0, "waitingForAttendeeValidation": 0,
    "waitingForFranceTravailValidation": 0, "pendingFranceTravail": 0,
    "accepted": 1, "inTraining": 2, "serviceDoneDeclared": 3,
    "serviceDoneValidated": 4, "invoiced": 5, "invoiceSent": 5,
    "paid": 5,
}
TERMINAL_EXCEPTION_STATES = {"refused", "rejected", "cancelled", "canceled", "abandoned"}


def map_wedof_status(status: Any) -> Optional[int]:
    """Retourne l'index de l'étape, sans jamais rabattre un état inconnu."""
    return WEDOF_STATUS_TO_STEP.get(str(status or "").strip())


def waiting_reason(snapshot: Dict[str, Any]) -> str:
    """Déduit le motif uniquement d'un indicateur WEDOF explicite."""
    value = str(snapshot.get("waiting_reason") or "").strip().casefold()
    if value in {"attendee", "candidate", "candidat", "attendeevalidation"}:
        return "En attente de validation de la part du candidat"
    if value in {"francetravail", "france_travail", "france travail", "instruction"}:
        return "Demande en cours d’instruction par France Travail"
    return "Type d’attente non communiqué"


def format_euro(value: Any) -> str:
    if value in (None, ""):
        return "Non communiqué"
    try:
        amount = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return "Non communiqué"
    return f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "\u202f")


def format_paris_datetime(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "Non communiqué"
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        local = parsed.astimezone(PARIS)
        return local.strftime("%d/%m/%Y à %Hh%M")
    except ValueError:
        return "Non communiqué"


def has_cpf_financing(trainee: Dict[str, Any]) -> bool:
    """Détecte le CPF dans les montants et les financements structurés (y compris mixtes)."""
    try:
        if float(str(trainee.get("cpf_amount") or trainee.get("montant_cpf") or 0).replace(",", ".")) > 0:
            return True
    except (TypeError, ValueError):
        pass
    values = [trainee.get(k) for k in ("financing_type", "funding_type", "financeur", "financement_comment")]
    for item in trainee.get("financings", []) if isinstance(trainee.get("financings"), list) else []:
        if isinstance(item, dict):
            values.extend(item.get(k) for k in ("type", "financing_type", "label", "financeur"))
    return any(re.search(r"(^|\W)cpf($|\W)|mon compte formation|caisse des d[ée]p[ôo]ts", str(v or ""), re.I) for v in values)


def build_steps(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    index = map_wedof_status(snapshot.get("state"))
    dates = snapshot.get("step_dates") if isinstance(snapshot.get("step_dates"), dict) else {}
    steps = []
    for position, label in enumerate(CPF_STEPS):
        state = "future" if index is None or position > index else "current" if position == index else "done"
        steps.append({"label": label, "state": state, "date": format_paris_datetime(dates.get(str(position)) or dates.get(label)) if position < (index or 0) else ""})
    return {"steps": steps, "current_index": index,
            "unknown": bool(snapshot.get("state")) and index is None,
            "waiting_reason": waiting_reason(snapshot) if index == 0 else ""}


def automation_view(external_id: str, statuses: Iterable[Dict[str, Any]], runs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    row = next((x for x in statuses if isinstance(x, dict) and str(x.get("external_id") or "") == external_id), {})
    actions = [("entry_training", "Déclaration d’entrée en formation"), ("service_done", "Déclaration du service fait")]
    actual = []
    for key, label in actions:
        action = row.get(key) if isinstance(row.get(key), dict) else {}
        status = str(action.get("status") or "")
        display = ({"planned": "Programmée", "executed": "Exécutée", "success": "Exécutée",
                    "pending": "En attente", "anomaly": "Échec", "failed": "Échec"}.get(status, "Non programmée"))
        actual.append({"action": label, "status": display, "tone": {"Programmée":"blue", "Exécutée":"green", "En attente":"orange", "Échec":"red"}.get(display,"gray"),
                       "planned_at": format_paris_datetime(action.get("planned_at")), "executed_at": format_paris_datetime(action.get("executed_at")),
                       "error": action.get("last_error_message") or action.get("last_error_code") or "",
                       "retry_at": format_paris_datetime(action.get("next_attempt_at"))})
    relevant_runs = [r for r in runs if isinstance(r, dict) and (not r.get("external_id") or str(r.get("external_id")) == external_id)]
    return {"actions": actual, "last_run": relevant_runs[-1] if relevant_runs else None}


def build_cpf_view(trainee: Dict[str, Any], session_obj: Dict[str, Any], data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not has_cpf_financing(trainee):
        return None
    link = next((x for x in data.get("wedof_links", []) if isinstance(x, dict) and x.get("active") is True
                 and str(x.get("session_id")) == str(session_obj.get("id")) and str(x.get("trainee_id")) == str(trainee.get("id"))), None)
    snapshot = dict(link.get("cpf_snapshot") or {}) if link else {}
    if link:
        snapshot.setdefault("external_id", link.get("external_id"))
        snapshot.setdefault("state", link.get("wedof_state"))
        snapshot.setdefault("start_date", link.get("wedof_date_start"))
        snapshot.setdefault("end_date", link.get("wedof_date_end"))
    result = {"found": bool(link), "snapshot": snapshot, "link": link, "sync_error": (link or {}).get("cpf_sync_error") or ""}
    result.update(build_steps(snapshot))
    result["automation"] = automation_view(str(snapshot.get("external_id") or ""), data.get("wedof_automation_status", []), data.get("wedof_automation_runs", []))
    result["money"] = {k: format_euro(snapshot.get(k)) for k in ("total_amount", "cpf_amount", "france_travail_amount", "candidate_amount")}
    result["last_sync_label"] = format_paris_datetime(snapshot.get("synced_at") or (link or {}).get("last_seen_at"))
    return result
