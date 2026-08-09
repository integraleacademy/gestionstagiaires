"""Contrat pur de sélection du futur cycle WEDOF (aucun appel mutateur).

Les candidats sont construits exclusivement à partir du dossier distant. Les
liens locaux ne font volontairement pas partie de l'API de ce module.
"""

import datetime as dt
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from wedof_matching import extract_folder, normalize_date


PARIS_TZ = ZoneInfo("Europe/Paris")
ACTION_RULES = {
    "entry": {"state": "accepted", "date_field": "start_date"},
    "service_done": {"state": "inTraining", "date_field": "end_date"},
}
AUTOMATABLE_STATES = {"accepted", "inTraining"}
SERVICE_DONE_STATES = {"serviceDoneDeclared", "serviceDoneValidated"}


def build_automation_dashboard(
    folders: Iterable[Dict[str, Any]], *, links: Iterable[Dict[str, Any]] = (),
    statuses: Iterable[Dict[str, Any]] = (), exceptions: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Construit le tableau de pilotage sans jamais dépendre des données locales.

    Les liens ne servent qu'aux libellés d'association. Une absence de lien n'est
    donc jamais bloquante. Les statuts persistés sont la seule preuve d'un succès
    effectué par l'application.
    """
    links_by_id = {str(x.get("external_id") or ""): x for x in links if isinstance(x, dict) and x.get("active") is True}
    status_by_id = {str(x.get("external_id") or ""): x for x in statuses if isinstance(x, dict)}
    blocked_ids = active_exception_external_ids(exceptions)
    rows = []
    for raw in folders:
        remote = extract_folder(raw)
        external_id = str(remote.get("external_id") or "").strip()
        state = str(remote.get("state") or "").strip()
        start_date, end_date = normalize_date(remote.get("start_date")), normalize_date(remote.get("end_date"))
        link = links_by_id.get(external_id)
        history = status_by_id.get(external_id, {})
        entry = history.get("entry_training") if isinstance(history.get("entry_training"), dict) else {}
        service = history.get("service_done") if isinstance(history.get("service_done"), dict) else {}
        reasons = []
        if not external_id: reasons.append("Numéro externalId WEDOF absent")
        if str(remote.get("type") or "").casefold() != "cpf": reasons.append("Type de dossier différent de CPF")
        if not start_date: reasons.append("Date de début WEDOF absente")
        if not end_date: reasons.append("Date de fin WEDOF absente")
        if state not in AUTOMATABLE_STATES | SERVICE_DONE_STATES: reasons.append("État WEDOF non exploitable")
        if external_id in blocked_ids: reasons.append("Dossier explicitement bloqué côté serveur")
        if link and (link.get("conflict") is True or link.get("status") == "conflict"):
            reasons.append("Conflit de rattachement local")
        current_cycle = entry if state == "accepted" else service if state == "inTraining" else {}
        if current_cycle.get("status") in {"error", "blocked"}:
            reasons.append(str(current_cycle.get("last_error") or "Automatisation bloquée"))
        tab = "anomaly" if reasons else ({"accepted": "accepted", "inTraining": "training"}.get(state, "service"))
        association = ("À rattacher localement" if not link else
                       "Associé manuellement" if link.get("source") == "manual_admin" else
                       "Association automatique fiable")
        rows.append({
            **remote, "external_id": external_id, "start_date": start_date, "end_date": end_date,
            "tab": tab, "anomaly_reasons": reasons, "automation_planned": not reasons and state in AUTOMATABLE_STATES,
            "association": association, "linked": bool(link), "link": link or {},
            "entry_success": entry.get("status") == "success",
            "service_success": service.get("status") == "success",
            "wedof_state_label": {"inTraining": "En formation (état WEDOF)", "serviceDoneDeclared": "Service fait déclaré (état WEDOF)", "serviceDoneValidated": "Service fait validé (état WEDOF)"}.get(state, ""),
        })
    stats = {
        "accepted": sum(x["tab"] == "accepted" for x in rows),
        "training": sum(x["tab"] == "training" for x in rows),
        "service": sum(x["tab"] == "service" for x in rows),
        "anomaly": sum(x["tab"] == "anomaly" for x in rows),
        "planned": sum(x["automation_planned"] for x in rows),
        "entry_success": sum(x["entry_success"] for x in rows),
        "service_success": sum(x["service_success"] for x in rows),
        "unlinked": sum(not x["linked"] for x in rows),
    }
    return {"rows": rows, "stats": stats}


def active_exception_external_ids(exceptions: Iterable[Dict[str, Any]]) -> set[str]:
    """Retourne les exceptions serveur actives, identifiées par externalId."""
    return {
        str(item.get("external_id") or "").strip()
        for item in exceptions
        if isinstance(item, dict) and item.get("active") is True
    } - {""}


def build_automation_candidate(
    folder: Dict[str, Any], action: str, *, now: Optional[dt.datetime] = None,
    exceptions: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Évalue un dossier distant sans consulter session, stagiaire ou lien local.

    Le résultat prépare le rattrapage (date passée acceptée) et sépare bien
    l'état WEDOF, l'état d'automatisation et l'état du rattachement local. Une
    relecture distante et l'idempotence resteront obligatoires avant tout futur
    appel mutateur.
    """
    if action not in ACTION_RULES:
        raise ValueError("Action WEDOF inconnue.")
    current = now or dt.datetime.now(PARIS_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=PARIS_TZ)
    today = current.astimezone(PARIS_TZ).date()
    remote = extract_folder(folder)
    rule = ACTION_RULES[action]
    external_id = str(remote.get("external_id") or "").strip()
    wedof_date = normalize_date(remote.get(rule["date_field"]))
    due = False
    if wedof_date:
        scheduled = dt.date.fromisoformat(wedof_date)
        # Le service fait n'est dû qu'après la fin de la journée parisienne.
        due = scheduled <= today if action == "entry" else scheduled < today
    blocked = external_id in active_exception_external_ids(exceptions)
    eligible = bool(
        str(remote.get("type") or "").casefold() == "cpf"
        and external_id
        and remote.get("state") == rule["state"]
        and due
        and not blocked
    )
    return {
        "external_id": external_id,
        "wedof_state": remote.get("state") or "",
        "wedof_date": wedof_date,
        "action": action,
        "automation_status": "eligible" if eligible else ("excepted" if blocked else "pending"),
        "local_link_status": "independent",
        "eligible": eligible,
        "requires_remote_reread": True,
    }
