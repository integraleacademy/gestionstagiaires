"""Operator-initiated CPF transfers from a verified EDOF record to the CRM or Salesforce."""
from contextlib import closing
from functools import wraps
import os
import time

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


def transfer(store, legacy, row, target, official_url):
    folder = row["folder_id"]
    label = TARGETS[target]
    # A name alone is not enough to create an external prospect.
    if not row.get("first_name") or not row.get("last_name") or not row.get("email"):
        raise ValueError("Relisez la fiche détaillée dans EDOF pour vérifier les coordonnées avant le transfert.")
    from wedof_requests import registration_id
    if target == "crm" and not (os.getenv("CRM_WEDOF_WEBHOOK_SECRET") or os.getenv("WEDOF_WEBHOOK_SECRET") or "").strip():
        raise ValueError("Le secret de transmission du CRM doit être configuré.")
    for entry in legacy._load_wedof_webhooks():
        if not isinstance(entry,dict):
            continue
        known = entry.get("folder_id") or registration_id(entry.get("wedof_folder_details") or entry.get("payload") or {})
        if str(known) == folder and entry.get(target + "_sent"):
            return f"Ce dossier a déjà été transmis au {label}."
        if str(known) == folder and entry.get(target + "_delivery_uncertain"):
            raise ValueError(f"Un envoi antérieur au {label} est à vérifier.")
    complete = {"externalId":folder, "type":"cpf", "state":"notProcessed", "permalink":official_url,
                "attendee":{"firstName":row["first_name"],"lastName":row["last_name"],"email":row["email"]},
                "trainingActionInfo":{"title":row.get("title"), "sessionStartDate":row.get("session_start_date"),
                                      "sessionEndDate":row.get("session_end_date")}}
    # The CRM accepts a complete signed folder from its own management app.
    # Its receiver can persist this envelope locally, without calling WeDoF.
    entry = {"id":"IEDOF-" + folder, "folder_id":folder, "delivery_id":"integrale-edof-request-"+folder,
             "provider":"integrale_edof", "event":"edof.registration", "payload":complete,
             "wedof_folder_details":complete,"permalink":official_url}
    with closing(store.connect()) as db, db:
        receipts(db)
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT state FROM cpf_transfers WHERE folder=? AND target=?", (folder,target)).fetchone()
        if prior and prior[0] == "sent":
            return f"Ce dossier a déjà été transmis au {label}."
        if prior and prior[0] in {"processing","uncertain"}:
            raise ValueError(f"Réception à vérifier dans {label}. Le transfert ne sera pas répété.")
        db.execute("INSERT OR REPLACE INTO cpf_transfers VALUES (?,?,?,?)", (folder,target,"processing",time.time()))
    delivery = legacy._send_wedof_entry_to_crm if target == "crm" else legacy._send_wedof_entry_to_salesforce
    try:
        reply, code = delivery(entry)
        acknowledged = target != "crm" or entry.get("crm_processed") or entry.get("crm_duplicate")
        if 200 <= code < 300 and reply.get("success") and entry.get(target+"_sent") and acknowledged:
            state = "sent"
        elif code in {400,401,403,404,422} or entry.get(target+"_status") in {400,401,403,404,422}:
            state = "refused"
        else:
            state = "uncertain"
    except Exception:
        state = "uncertain"
    with closing(store.connect()) as db, db:
        db.execute("UPDATE cpf_transfers SET state=?, changed=? WHERE folder=? AND target=?", (state,time.time(),folder,target))
    if state == "sent":
        return f"{label} a accusé réception de la transmission."
    if state == "uncertain":
        raise ValueError(f"Réception à vérifier dans {label}. Le transfert ne sera pas répété.")
    raise ValueError(f"{label} a refusé ce transfert. Vérifiez les coordonnées et la configuration.")
