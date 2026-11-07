"""Operator-initiated CPF transfers from a verified EDOF record to the CRM or Salesforce."""
from contextlib import closing
import os
import time

import cpf_provider
import integrale_edof_crm_delivery

from cpf_transfer_history import TARGETS, historical_delivery, receipt, receipts, respect_native_receipt


def transfer(store, legacy, row, target, official_url):
    folder = row["folder_id"]
    label = TARGETS[target]
    # A name alone is not enough to create an external prospect.
    if not row.get("first_name") or not row.get("last_name") or not row.get("email"):
        raise ValueError("Relisez la fiche détaillée dans EDOF pour vérifier les coordonnées avant le transfert.")
    if target == "crm" and not (os.getenv("CRM_INTEGRATION_API_TOKEN") or "").strip():
        raise ValueError("Le secret de transmission du CRM doit être configuré.")
    known = historical_delivery(legacy, folder, target)
    if cpf_provider.on_test_service() and known != "sent":
        from cpf_provider_bridge import production_request
        production = production_request({"folder": folder, "target": target}, path="/receipt")
        if production.get("receipt") not in {"", "sent", "processing", "uncertain", "refused"}:
            raise ValueError(f"Impossible de vérifier les envois de production au {label}.")
        known = known or production["receipt"]
    if known == "sent":
        return f"Ce dossier a déjà été transmis au {label}."
    if known in {"processing", "uncertain"}:
        raise ValueError(f"Un envoi antérieur au {label} est à vérifier.")
    complete = {"externalId":folder, "type":"cpf", "state":"notProcessed", "permalink":official_url,
                "attendee":{"firstName":row["first_name"],"lastName":row["last_name"],"email":row["email"]},
                "trainingActionInfo":{"title":row.get("title"), "sessionStartDate":row.get("session_start_date"),
                                      "sessionEndDate":row.get("session_end_date")}}
    if target == "crm":
        from integrale_edof_crm import crm_folder
        from integrale_edof_dashboard import category
        complete = crm_folder(row, category, row.get("observed_at") or 0)
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
    delivery = integrale_edof_crm_delivery.send if target == "crm" else legacy._send_wedof_entry_to_salesforce
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
