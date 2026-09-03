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

# L'état pédagogique du dossier WEDOF et l'état de sa facture sont deux
# informations distinctes. Un dossier facturé peut donc rester techniquement
# en ``serviceDoneValidated`` tandis que la facture Qonto est déjà finalisée,
# envoyée ou en attente de paiement.
GENERATED_INVOICE_STATUSES = {
    "generated", "finalized", "sent", "unpaid", "partiallypaid", "paid",
    "overdue", "issued", "validated", "invoiced", "invoicesent",
    "externalgenerated", "generatedexternally", "billed", "settled",
}
NON_GENERATED_INVOICE_STATUSES = {
    "notgenerated", "notinvoiced", "draft", "cancelled", "canceled",
    "deleted", "control", "missing", "syncerror", "error", "failed",
    "notbilled", "billingpending", "readytobill",
}


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


def format_paris_date(value: Any) -> str:
    """Formate une date WEDOF en date civile française, sans heure."""
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, dt.date):
        return value.strftime("%d/%m/%Y")
    else:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
            return raw
        try:
            parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(PARIS).strftime("%d/%m/%Y")


def _history_date(value: Any) -> Any:
    """Extrait une date d'un événement d'historique WEDOF connu."""
    if isinstance(value, (str, dt.date, dt.datetime)):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("date", "at", "changedAt", "transitionedAt", "createdAt", "updatedAt", "timestamp"):
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return ""


def _step_position(value: Any) -> Optional[int]:
    raw = str(value or "").strip()
    if raw.isdigit() and 0 <= int(raw) < len(CPF_STEPS):
        return int(raw)
    mapped = map_wedof_status(raw)
    if mapped is not None:
        return mapped
    folded = raw.casefold()
    return next((position for position, label in enumerate(CPF_STEPS)
                 if label.casefold() == folded), None)


def _step_history_date(step_dates: Any, position: int) -> Any:
    """Lit aussi bien ``stateDates`` qu'une liste ``statusHistory`` WEDOF."""
    if isinstance(step_dates, dict):
        for key, value in step_dates.items():
            if _step_position(key) == position:
                candidate = _history_date(value)
                if candidate:
                    return candidate
        for nested_key in ("history", "items", "events"):
            candidate = _step_history_date(step_dates.get(nested_key), position)
            if candidate:
                return candidate
    elif isinstance(step_dates, list):
        for event in step_dates:
            if not isinstance(event, dict):
                continue
            state = event.get("state") or event.get("status") or event.get("name")
            if _step_position(state) == position:
                candidate = _history_date(event)
                if candidate:
                    return candidate
    return ""


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


def _normalized_invoice_status(value: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip().casefold())


def _invoice_record_is_generated(record: Dict[str, Any]) -> bool:
    """Détecte une facture réelle sans confondre un brouillon avec une émission."""
    billing_state = _normalized_invoice_status(
        record.get("billing_state") or record.get("billingState")
    )
    if billing_state in GENERATED_INVOICE_STATUSES:
        return True
    status = _normalized_invoice_status(
        record.get("invoice_status") or record.get("invoiceStatus")
        or record.get("qonto_status") or record.get("qontoStatus")
        or record.get("payment_status") or record.get("paymentStatus")
    )
    if status in GENERATED_INVOICE_STATUSES:
        return True
    if status in NON_GENERATED_INVOICE_STATUSES:
        return False
    invoice_number = (
        record.get("qonto_invoice_number") or record.get("qontoInvoiceNumber")
        or record.get("invoice_number") or record.get("invoiceNumber")
    )
    paid_at = (
        record.get("invoice_paid_at") or record.get("paidAt")
        or record.get("qontoPaidAt")
    )
    return bool(str(invoice_number or "").strip() or str(paid_at or "").strip())


def _billing_line_is_cpf(line: Dict[str, Any]) -> bool:
    values = [line.get(key) for key in (
        "financingType", "financing_type", "typeFinanceur", "financeurName",
        "financeur", "financingLabel", "fundingType", "funding_type",
    )]
    return any(
        re.search(r"(^|\W)cpf($|\W)|mon compte formation|caisse des d[ée]p[ôo]ts", str(value or ""), re.I)
        for value in values
    )


def has_generated_cpf_invoice(snapshot: Dict[str, Any], trainee: Dict[str, Any],
                              session_obj: Dict[str, Any], data: Dict[str, Any]) -> bool:
    if _invoice_record_is_generated(snapshot):
        return True
    trainee_id = str(trainee.get("id") or "")
    session_id = str(session_obj.get("id") or "")
    billing_lines = data.get("billing_lines") if isinstance(data.get("billing_lines"), list) else []
    return any(
        isinstance(line, dict)
        and str(line.get("traineeId") or line.get("trainee_id") or "") == trainee_id
        and str(line.get("sessionId") or line.get("session_id") or "") == session_id
        and _billing_line_is_cpf(line)
        and bool(
            line.get("qontoInvoiceId") or line.get("qonto_invoice_id")
            or line.get("qontoInvoiceNumber") or line.get("qonto_invoice_number")
        )
        and _invoice_record_is_generated(line)
        for line in billing_lines
    )


def build_steps(snapshot: Dict[str, Any], *, invoice_generated: Optional[bool] = None) -> Dict[str, Any]:
    raw_index = map_wedof_status(snapshot.get("state"))
    if invoice_generated is None:
        invoice_generated = _invoice_record_is_generated(snapshot)
    index = 5 if invoice_generated else raw_index
    dates = snapshot.get("step_dates")
    steps = []
    for position, label in enumerate(CPF_STEPS):
        state = "future" if index is None or position > index else "current" if position == index else "done"
        raw_date = _step_history_date(dates, position)
        if not raw_date and position == 0:
            raw_date = snapshot.get("created_at")
        if not raw_date and position == 2 and index is not None and position <= index:
            raw_date = snapshot.get("start_date")
        if not raw_date and index is not None and position == index:
            raw_date = snapshot.get("updated_at")
        steps.append({
            "label": label,
            "state": state,
            "date": format_paris_date(raw_date) if index is not None and position <= index else "",
        })
    return {"steps": steps, "current_index": index,
            "unknown": bool(snapshot.get("state")) and raw_index is None and not invoice_generated,
            "waiting_reason": waiting_reason(snapshot) if index == 0 else ""}


def automation_view(external_id: str, statuses: Iterable[Dict[str, Any]], runs: Iterable[Dict[str, Any]],
                    snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    row = next((x for x in statuses if isinstance(x, dict) and str(x.get("external_id") or "") == external_id), {})
    remote_state = str(row.get("wedof_state") or (snapshot or {}).get("state") or "")
    actions = [("entry_training", "Déclaration d’entrée en formation"), ("service_done", "Déclaration du service fait")]
    actual = []
    for key, label in actions:
        action = row.get(key) if isinstance(row.get(key), dict) else {}
        status = str(action.get("status") or "")
        planned_at = format_paris_datetime(action.get("planned_at"))
        executed_at = format_paris_datetime(action.get("executed_at"))
        error = action.get("last_error_message") or action.get("last_error_code") or ""
        if not status and key == "service_done" and remote_state == "accepted":
            display, tone = "À venir", "gray"
            detail = "Sera programmée lorsque le dossier passera « En formation »."
        elif status == "planned":
            display, tone = "Programmée", "blue"
            detail = f"Prévue le {planned_at}."
        elif status in {"executed", "success"}:
            display, tone = "Exécutée", "green"
            detail = (f"Exécutée automatiquement le {executed_at}." if executed_at != "Non communiqué"
                      else "Exécutée automatiquement.")
        elif status in {"already_done", "completed_in_wedof"}:
            display, tone = "Étape franchie", "green"
            detail = "Déjà réalisée dans WEDOF."
        elif status == "waiting_for_in_training" or (
            status == "not_applicable" and key == "service_done" and remote_state == "accepted"
        ):
            display, tone = "À venir", "gray"
            detail = "Sera programmée lorsque le dossier passera « En formation »."
            if planned_at != "Non communiqué":
                detail += f" Date cible : {planned_at}."
        elif status == "not_applicable" and key == "entry_training" and remote_state in {
            "inTraining", "serviceDoneDeclared", "serviceDoneValidated", "terminated",
        }:
            display, tone = "Étape franchie", "green"
            detail = "Le dossier a déjà dépassé cette étape dans WEDOF."
        elif status in {"pending", "processing"}:
            display, tone = "En cours", "orange"
            detail = "Traitement WEDOF en cours."
        elif status in {"dry_run_due", "dry_run_due_late"}:
            display, tone = "À traiter", "orange" if status == "dry_run_due" else "red"
            detail = "Échéance atteinte : traitement au prochain passage automatique."
        elif status == "blocked":
            display, tone = "Suspendue", "red"
            detail = "Automatisation suspendue par un administrateur."
        elif status == "uncertain_after_timeout":
            display, tone = "À vérifier", "red"
            detail = "WEDOF n’a pas confirmé le résultat de la dernière tentative."
        elif status in {"anomaly", "failed", "error"}:
            display, tone = "Échec", "red"
            detail = str(error or "Une anomalie empêche le traitement automatique.")
        elif not status:
            display, tone = "À calculer", "gray"
            detail = "Programmation en attente du prochain contrôle WEDOF."
        else:
            display, tone = "Non applicable", "gray"
            detail = "Cette automatisation ne s’applique pas au statut WEDOF actuel."
        actual.append({"action": label, "status": display, "tone": tone,
                       "planned_at": planned_at, "executed_at": executed_at,
                       "detail": detail, "error": error,
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
        if not snapshot.get("created_at"):
            snapshot["created_at"] = link.get("created_at")
    result = {"found": bool(link), "snapshot": snapshot, "link": link, "sync_error": (link or {}).get("cpf_sync_error") or ""}
    invoice_generated = has_generated_cpf_invoice(snapshot, trainee, session_obj, data)
    result.update(build_steps(snapshot, invoice_generated=invoice_generated))
    result["automation"] = automation_view(
        str(snapshot.get("external_id") or ""), data.get("wedof_automation_status", []),
        data.get("wedof_automation_runs", []), snapshot,
    )
    result["money"] = {k: format_euro(snapshot.get(k)) for k in ("total_amount", "cpf_amount", "france_travail_amount", "candidate_amount")}
    result["last_sync_label"] = format_paris_datetime(snapshot.get("synced_at") or (link or {}).get("last_seen_at"))
    return result
