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
