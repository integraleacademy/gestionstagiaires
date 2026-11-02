"""Persistent anti-duplicate receipts shared across CPF providers."""
from contextlib import closing
from functools import wraps

import cpf_provider

TARGETS = {"crm": "CRM", "salesforce": "Salesforce"}


def receipts(db):
    db.execute("""CREATE TABLE IF NOT EXISTS cpf_transfers (
        folder TEXT NOT NULL, target TEXT NOT NULL, state TEXT NOT NULL, changed REAL NOT NULL,
        PRIMARY KEY(folder,target))""")


def receipt(store, folder, target):
    with closing(store.connect()) as db:
        receipts(db)
        row = db.execute("SELECT state FROM cpf_transfers WHERE folder=? AND target=?", (folder,target)).fetchone()
        return row[0] if row else ""


def respect_native_receipt(target):
    """After a switch back, a WeDoF callback cannot repeat a native transfer."""
    def decorate(send):
        @wraps(send)
        def protected(entry):
            store = cpf_provider.current_store()
            if store is not None and entry.get("provider") != "integrale_edof":
                from wedof_requests import registration_id
                folder = str(entry.get("folder_id") or registration_id(entry.get("payload") or {}) or "")
                if folder:
                    status = receipt(store, folder, target)
                    if status == "sent":
                        return {"success":True, target+"_sent":True, "skipped":True, "reason":"already_sent_by_integrale"}, 200
                    if status in {"processing","uncertain"}:
                        return {"success":False, "error":"Vérifiez la réception de la transmission Intégrale EDOF avant tout nouvel envoi."}, 409
            return send(entry)
        return protected
    return decorate


def historical_delivery(legacy, folder, target):
    from wedof_requests import registration_id
    for entry in legacy._load_wedof_webhooks():
        if not isinstance(entry,dict):
            continue
        known = entry.get("folder_id") or registration_id(entry.get("wedof_folder_details") or entry.get("payload") or {})
        if str(known) == folder and entry.get(target + "_sent"):
            return "sent"
        if str(known) == folder and entry.get(target + "_delivery_uncertain"):
            return "uncertain"
    return ""
