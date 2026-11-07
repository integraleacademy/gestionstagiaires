"""Read-only CRM feed of dossiers synchronized for the academy's EDOF account."""

from threading import Lock
from time import monotonic

from flask import Blueprint, jsonify, request

from edof_directory import normalized
from edof_readonly_test import ID_RE
from integrale_edof_associations import observed_rows, snapshot_owners


CRM_STATES = {
    "request": "notProcessed", "waiting": "validated", "ft": "waitingAcceptation",
    "ft_refused": "validated", "accepted": "accepted", "training": "inTraining",
    "entry": "inTraining", "out": "terminated", "declared": "serviceDoneDeclared",
    "billable": "serviceDoneValidated", "invoiced": "billed", "paid": "paid",
    "refused": "refused", "canceled": "cancelled",
}


def crm_folder(row, category, observed):
    folder = row["folder_id"]
    kind = category(row)
    attendee = {"firstName": row.get("first_name"), "lastName": row.get("last_name")}
    if row.get("email"):
        attendee["email"] = row["email"]
    if row.get("phone"):
        attendee["phoneNumber"] = row["phone"]
    info = {"title": row.get("title"), "sessionStartDate": row.get("session_start_date"),
            "sessionEndDate": row.get("session_end_date")}
    for key, value in (row.get("offer_summary") or {}).items():
        if key in {"priceTotal", "indicativeDuration", "weeklyDuration", "hoursInCenter", "hoursInCompany"}:
            info["totalIncl" if key == "priceTotal" else key] = value
    ft = row.get("crm_ft_solicitations")
    if ft is not None:
        info["solicitations"] = ft
    elif row.get("ft_pending") or row.get("ft_refused") or kind in {"ft", "ft_refused"}:
        pending = row.get("ft_pending") or kind == "ft"
        info["solicitations"] = [{"fundingType": 9, "status": "inProgress" if pending else "refused",
                                  "submissionDate": row.get("funding_request_at") or (row.get("funding_at") if pending else ""),
                                  "returnDate": "" if pending else row.get("funding_at")}]
    result = {"externalId": folder, "type": "cpf", "provider": "integrale_edof",
              "state": CRM_STATES.get(kind, row.get("state") or ""),
              "attendee": {k:v for k,v in attendee.items() if v},
              "trainingActionInfo": {k:v for k,v in info.items() if v is not None and v != ""},
              "edofObservedAt": observed}
    filed = row.get("created_at") or row.get("filed_at") or (row.get("request_date") if kind == "request" else "")
    if filed:
        result["createdAt"] = filed
    if row.get("state_at"):
        result["updatedAt"] = row["state_at"]
    if row.get("billing_state"):
        result["billingState"] = row["billing_state"]
    return result


def register_crm_feed(app, store, vault, snapshot, category, authorized, active):
    bp = Blueprint("crm_integrale_edof", __name__, url_prefix="/api/integrations/crm/integrale-edof")

    @bp.after_request
    def private(response):
        response.headers["Cache-Control"] = "private, no-store"
        return response

    # Each reconciliation pages over the same local source. Reuse one immutable
    # view briefly across list and detail reads from the same web worker.
    lock = Lock()
    cached = None
    expires = 0.0

    def load_directory():
        rows, checked = {}, None
        for owner in sorted(snapshot_owners(vault())):
            saved = snapshot(owner)
            if saved is None:
                continue
            base = saved.get("checked") or 0
            checked = max(checked or 0, base, *(saved.get(k) or 0 for k in (
                "pending_checked", "accepted_checked", "receipt_checked")))
            subset = saved.get("rows", {})
            pending_contacts = vault().get("crm-pending-contacts:" + owner) or {}
            for ident, row in observed_rows(store, owner, {"rows":subset}).items():
                contact = pending_contacts.get(ident, {})
                if contact and all(row.get(k) and normalized(row[k]) == normalized(contact.get(k) or "")
                                   for k in ("first_name", "last_name")):
                    row = {**row, **{k: contact[k] for k in ("email", "phone") if contact.get(k)}}
                stamp = row.get("observed_at") or base
                if ident not in rows or stamp >= rows[ident][0]:
                    rows[ident] = (stamp, row)
        return rows, checked

    def current_directory():
        nonlocal cached, expires
        with lock:
            if cached is None or monotonic() >= expires:
                cached = load_directory()
                expires = monotonic() + 20
            return cached

    @bp.get("/status")
    @bp.get("/dossiers")
    @bp.get("/dossiers/<folder_id>")
    @authorized
    def read(folder_id=None):
        if not store.connector_key or not active():
            return jsonify(error="Intégrale EDOF indisponible"), 503
        if folder_id and not ID_RE.fullmatch(folder_id):
            return jsonify(error="Numéro de dossier invalide"), 400
        page = request.args.get("page", "1")
        if not page.isascii() or not page.isdigit() or len(page) > 7 or int(page) < 1:
            return jsonify(error="Page invalide"), 400
        page = int(page)
        status_only = request.path.endswith("/status")
        rows, checked = current_directory()
        if checked is None:
            return jsonify(error="Aucune liste EDOF synchronisée"), 503
        if status_only:
            return jsonify(provider="integrale_edof", source_checked_at=checked)
        def export(ident):
            observed, row = rows[ident]
            return crm_folder(row, category, observed)
        if folder_id:
            if folder_id not in rows:
                return jsonify(error="Dossier absent de la liste Intégrale EDOF"), 404
            return jsonify(export(folder_id))
        ids = sorted(rows, reverse=True)
        if request.args.get("scope") == "requests":
            ids = [ident for ident in ids if category(rows[ident][1]) == "request"]
        size = 100
        items = [export(i) for i in ids[(page-1)*size:page*size]]
        return jsonify(items=items), 200, {"X-Current-Page": str(page), "X-Item-Per-Page": str(size),
                                          "X-Total-Count": str(len(ids))}
    app.register_blueprint(bp)
