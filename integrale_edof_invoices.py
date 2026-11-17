"""Resolve existing CPF invoice PDFs without creating or sending an invoice."""


def linked_registration(data, folder, partner_id):
    links = [link for link in data.get("wedof_links", [])
             if link.get("active") and str(link.get("external_id")) == folder]
    if len(links) != 1:
        return None
    link = links[0]
    training = next((s for s in data.get("sessions", [])
                     if s.get("id") == link.get("session_id")
                     and s.get("partner_id") in (None, "", partner_id)), None)
    if not training:
        return None
    trainee = next((t for t in training.get("trainees", []) if t.get("id") == link.get("trainee_id")), None)
    return (link, training, trainee) if trainee else None


def find_local_invoice(data, folder, partner_id):
    registration = linked_registration(data, folder, partner_id)
    if not registration:
        return ""
    link, _, _ = registration
    snapshot = link.get("cpf_snapshot") or {}
    reference = snapshot.get("qonto_invoice_id") or link.get("qonto_invoice_id") or link.get("qontoInvoiceId")
    if reference:
        return str(reference)
    rows = [row for row in data.get("billing_lines", [])
            if row.get("sessionId") == link.get("session_id") and row.get("traineeId") == link.get("trainee_id")
            and str(row.get("financingType") or row.get("typeFinanceur") or "").upper() == "CPF"
            and row.get("invoiceStatus") not in ("draft", "cancelled", "canceled", "not_invoiced")
            and row.get("qontoInvoiceId")]
    exact = [row for row in rows if row.get("financingRef") == "wedof:" + folder]
    fallback = [row for row in rows if not str(row.get("financingRef") or "").startswith("wedof:")]
    ids = {row["qontoInvoiceId"] for row in (exact or fallback)}
    return next(iter(ids)) if len(ids) == 1 else ""
