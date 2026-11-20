"""Settlement instructions for practical VTC orders. Qonto remains the invoice ledger."""
import exam_retakes_workflow as provider
import exam_retakes
from exam_retakes import date_label, date_value
from manuals_commerce import read_invoice_link_payments

METHODS = {"card": "Carte bancaire", "transfer": "Virement bancaire", "cheque": "Chèque",
           "cash": "Espèces", "sepa": "Prélèvement SEPA", "cpf": "CPF"}


def method(row):
    return row.get("payment_method") or ("cpf" if row["offer"] == "cpf" else "card")


def retire_card_link(host, row):
    link_id = row.get("payment_id")
    if not link_id:
        if any(row.get(key) for key in ("payment_creation_started", "payment_started", "payment_url")):
            raise ValueError("La création du lien carte doit d’abord être rapprochée dans Qonto.")
        return

    path = "/v2/payment_links/" + link_id

    def inspect():
        response = host._qonto_request("GET", path)
        link = response.get("payment_link") or response
        if link.get("id") != link_id or link.get("status") not in {"open", "canceled", "cancelled", "expired"}:
            raise ValueError("Le lien carte est en cours de règlement ou doit être vérifié dans Qonto.")
        if link.get("invoice_id"):
            matches_order = link["invoice_id"] == row.get("invoice_id")
        else:
            matches_order = any(f"[{row['id']}]" in item.get("description", "") for item in link.get("items") or [])
        if not matches_order:
            raise ValueError("Le lien Qonto ne correspond pas à cette commande.")
        captures, pending = read_invoice_link_payments(host, link_id, closing=True)
        if captures or pending:
            raise ValueError("Un règlement carte a été reçu ou est en cours dans Qonto.")
        return link["status"]

    if inspect() == "open":
        host._qonto_request("PATCH", path + "/deactivate", idempotency_key="vtc-close-" + link_id)
        if inspect() == "open":
            raise ValueError("Qonto n’a pas encore confirmé la fermeture du lien carte.")
    row.setdefault("retired_payment_links", []).append(link_id)
    for key in ("payment_id", "payment_started", "payment_creation_started", "payment_url",
                "payment_link_status", "payment_status", "billing_problem"):
        row.pop(key, None)


def set_method(host, row, choice, agreement_locked):
    previous = method(row)
    if choice not in METHODS or (choice == "cpf" and row["offer"] == "vehicule"):
        raise ValueError("Choisissez un mode de paiement proposé pour cette prestation.")
    if choice == previous:
        return False
    if (row["stage"] in {"paid", "funded", "withdrawn"} or row.get("manual_receipt")
            or row.get("confirmed_payment") or row.get("paid_cents")
            or row.get("payment_status") in {"processing", "partially_paid", "paid"}):
        raise ValueError("Le règlement ou la prise en charge est déjà engagé sur cette commande.")
    changes_funding = "cpf" in (previous, choice)
    if changes_funding and (agreement_locked or row.get("invoice_id") or row.get("invoice_started")
                            or row["stage"] not in {"verify", "planning", "calendar"}):
        raise ValueError("Le financement de cette convention est déjà engagé.")
    if row.get("invoice_id"):
        invoice = host._qonto_invoice_payload(host.get_qonto_invoice(row["invoice_id"]))
        provider.invoice_assert(row, invoice)
        actual = host.normalize_qonto_invoice_payment_data(invoice, {"amount_ttc": row["total_cents"] / 100})
        if invoice.get("status") == "paid" or actual["qonto_amount_paid_cents"]:
            raise ValueError("Un règlement figure déjà sur la facture Qonto.")
    if previous == "card":
        retire_card_link(host, row)
    if changes_funding:
        row.setdefault("original_offer", row["offer"])
        if row.get("selected_slot"):
            row["_release_slot_id"] = row["selected_slot"]
            row["selected_slot"] = ""
        row["offer"] = "cpf" if choice == "cpf" else "formation"
        if row["stage"] != "verify":
            row["stage"] = "calendar" if choice == "cpf" else "planning"
    row["payment_method"] = choice
    row["payment_terms"] = "Mode de règlement convenu : " + METHODS[choice] + "."
    if row.get("invoice_id"):
        row["billing_flow"] = "invoice_first"
    return True


def record_receipt(row, form):
    if method(row) in {"card", "cpf"} or row["stage"] != "billing":
        raise ValueError("Le règlement manuel n’est pas ouvert pour cette commande.")
    day = date_value(form.get("paid_day"), "Date d’encaissement")
    reference = (form.get("reference") or "").strip()
    if day > exam_retakes.today() or not 1 <= len(reference) <= 160 or form.get("received") != "yes":
        raise ValueError("Confirmez le montant intégral reçu, la date de réception et sa référence.")
    if row.get("manual_receipt"):
        if row["manual_receipt"] != {"day": day, "reference": reference, "method": method(row)}:
            raise ValueError("Un encaissement est déjà enregistré sur cette commande.")
        return
    row["manual_receipt"] = {"day": day, "reference": reference, "method": method(row)}


def sync_offline_billing(host, store, row):
    receipt = row.get("manual_receipt")
    if not (receipt or row.get("invoice_requested") or row.get("invoice_id") or row.get("invoice_started")):
        return
    if receipt:
        row["payment_terms"] = f"Règlement par {METHODS[receipt['method']]} reçu le {date_label(receipt['day'])}."
    invoice = provider.ensure_invoice(host, store, row)
    actual = host.normalize_qonto_invoice_payment_data(invoice, {"amount_ttc": row["total_cents"] / 100})
    if actual["qonto_amount_paid_cents"] not in (0, row["total_cents"]):
        raise ValueError("Un règlement partiel figure sur la facture. Vérifiez son solde dans Qonto.")
    if not receipt and invoice["status"] != "paid":
        path = store.document(row["id"], "invoice")
        if not path.is_file():
            content, _ = host.fetch_qonto_client_invoice_pdf(invoice["id"])
            provider.store_pdf(path, content)
    if receipt and invoice["status"] != "paid" and not actual["qonto_amount_paid_cents"]:
        host._qonto_request("POST", f"/v2/client_invoices/{invoice['id']}/mark_as_paid",
                            {"paid_at": receipt["day"]}, idempotency_key="vtc-offline-paid-" + row["id"])
        invoice = host._qonto_invoice_payload(host.get_qonto_invoice(invoice["id"]))
        provider.invoice_assert(row, invoice)
        actual = host.normalize_qonto_invoice_payment_data(invoice, {"amount_ttc": row["total_cents"] / 100})
    if invoice["status"] == "paid" and actual["qonto_amount_paid_cents"] == row["total_cents"]:
        provider.record_payment(store, row, "paid", row["total_cents"])
