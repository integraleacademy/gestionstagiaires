"""Read-only navigation and operation views for the CPF dashboard."""
from collections import Counter
import datetime as dt

from edof_schedule import scheduled_at

GROUPS = {
    "requests": "Demandes",
    "training": "Formations",
    "billing": "Facturation et paiements",
    "closed": "Refus et annulations",
    "all": "Tous les dossiers",
}
GROUP_TABS = {
    "requests": {"all": "Toutes les demandes", "request": "À traiter",
                 "waiting": "Validation du titulaire", "ft": "Financement FT en cours",
                 "ft_refused": "Financement FT refusé"},
    "training": {"all": "Toutes les formations", "accepted": "Accepté / À démarrer",
                 "training": "En formation", "out": "Sortie déclarée"},
    "billing": {"all": "Toute la facturation", "declared": "Service fait déclaré",
                "billable": "À facturer · Service fait validé", "invoiced": "Facturé · En attente de paiement",
                "paid": "Payé"},
    "closed": {"all": "Refus et annulations", "refused": "Refusé", "canceled": "Annulé"},
    "all": {"all": "Tous les dossiers", "unlinked": "À associer", "association_ignored": "Dossiers masqués", "anomaly": "À vérifier"},
}
AUTOMATION_TABS = {
    "today": "Prévu aujourd’hui", "overdue": "En retard", "attention": "À compléter / À vérifier",
    "blocked": "Bloquées / En erreur", "running": "En cours",
    "planned": "À venir",
}
KIND_GROUP = {"request": "requests", "waiting": "requests", "ft": "requests", "ft_refused": "requests",
              "accepted": "training", "training": "training", "entry": "training", "out": "training",
              "service": "billing", "declared": "billing", "billable": "billing", "invoiced": "billing",
              "paid": "billing", "refused": "closed", "canceled": "closed"}


def navigation(args):
    """Resolve bookmarked legacy views without duplicating navigation entries."""
    section = args.get("section", "state")
    tab = args.get("tab", "")
    group = args.get("group", "")
    if section == "cancellations":
        section, group, tab = "state", "closed", "canceled"
    elif section == "requests":
        section = "state"
        group = KIND_GROUP.get(tab, "requests")
        tab = tab or "request"
    elif section == "automations" and tab in KIND_GROUP:
        section, group = "state", KIND_GROUP[tab]
    elif section == "automations" and tab == "history":
        section = "consumption"
    elif section == "state" and tab == "due":
        section = "automations"
    if section == "automations":
        # The old due bookmark included future and overdue declarations.
        tab = tab if tab in AUTOMATION_TABS or tab == "due" else "overdue"
        return section, "all", AUTOMATION_TABS, tab
    if section != "state":
        return section, "all", GROUP_TABS["all"], "all"
    if tab == "entry":
        tab = "training"
    if not group:
        group = KIND_GROUP.get(tab, "all" if any(k in args for k in ("q", "folder", "matching", "simulation", "tab")) else "requests")
    if group not in GROUPS:
        group = "all"
    if tab == "service":
        group, tab = "billing", "all"
    tabs = GROUP_TABS[group]
    if tab not in tabs:
        tab = "request" if group == "requests" and not args.get("group") else "all"
    return section, group, tabs, tab


def group_counts(rows):
    counts = Counter({"all": len(rows)})
    for row in rows:
        group = KIND_GROUP.get(row["kind"])
        if group:
            counts[group] += 1
    return counts


def in_group(row, group):
    return group == "all" or KIND_GROUP.get(row["kind"]) == group


def in_pending_requests(folder, kind, snapshot):
    return kind == "request" and ("pending_ids" not in snapshot or folder in snapshot["pending_ids"])


def period_key(row):
    return (row.get("session_start_date") or "") + "/" + (row.get("session_end_date") or "")


def operation_rows(rows, dispatches, now, revision, outcomes=None):
    """Separate scheduled work from verified receipts; never enqueue anything."""
    outcomes = outcomes or {}
    records = {(d["folder"], d["action"]): d for d in reversed(dispatches)}
    result = []

    def append(row, action, dispatch=None, current=True):
        date = row.get("session_start_date" if action == "entry_training" else "session_end_date")
        scheduled = scheduled_at(action, date)
        status = dispatch.get("status") if dispatch else None
        outcome_action, outcome = outcomes.get(row["folder_id"], (None, None))
        outcome = outcome if current and outcome_action == action else None
        block = row.get("block") if current else None
        changed = dt.datetime.fromtimestamp(dispatch["changed"], now.tzinfo) if dispatch and dispatch.get("changed") else None
        if status == "confirmed":
            bucket, note = "history", "Réception vérifiée dans EDOF"
        elif status == "queued" and dispatch.get("detail") not in {None, "", "declaration_exit_confirmed"}:
            bucket, note = "blocked", "Transmission différée après un problème de connexion"
        elif status == "sending" or (status == "queued" and dispatch["revision"] == revision and not block):
            bucket, note = "running", "En attente de transmission" if status == "queued" else "Envoi effectué ou en cours de vérification"
        elif status == "uncertain":
            bucket, note = "attention", "Réception à vérifier avant toute nouvelle transmission"
        elif block or status in {"review", "paused", "queued"} or outcome == "blocked":
            bucket, note = "blocked", ("Blocage enregistré sur le dossier" if block else
                                      "Déclaration à vérifier" if status == "review" else "Action suspendue ou bloquée")
        elif outcome == "review" or not scheduled:
            bucket, note = "attention", "Déclaration à vérifier" if outcome == "review" else "Date de formation à compléter"
        elif scheduled <= now:
            bucket = "overdue"
            note = "Envoi automatique prévu au prochain passage"
        else:
            bucket, note = "planned", f"Envoi automatique à {scheduled.hour} h"
        result.append({**row, "action": action, "scheduled": scheduled, "block": block,
                       "scheduled_today": bool(current and scheduled and scheduled.date() == now.date() and bucket != "history"),
                       "due": bool(scheduled and scheduled <= now and bucket not in {"history", "planned"}),
                       "dispatch_status": status, "catchup_outcome": outcome, "operation_bucket": bucket,
                       "operation_note": note, "operation_changed": changed,
                       "operation_detail": dispatch.get("detail", "") if dispatch else "",
                       "operation_date": (dispatch.get("intent") or {}).get("actual_date") if dispatch else None})

    for row in rows:
        current = row.get("action")
        if current:
            append(row, current, records.get((row["folder_id"], current)))
        for action in ("entry_training", "service_done"):
            dispatch = records.get((row["folder_id"], action))
            if action != current and dispatch:
                append(row, action, dispatch, current=False)
    return result


def sort_operations(rows):
    """Oldest overdue first, nearest upcoming first, latest receipts first."""
    priority = {"overdue": 0, "attention": 1, "blocked": 2, "running": 3, "planned": 4, "history": 5}
    def key(row):
        stamp = row.get("operation_changed") if row["operation_bucket"] == "history" else row.get("scheduled")
        value = stamp.timestamp() if stamp else float("inf")
        if row["operation_bucket"] == "history" and stamp:
            value = -value
        return priority[row["operation_bucket"]], value, row["folder_id"], row["action"]
    rows.sort(key=key)
