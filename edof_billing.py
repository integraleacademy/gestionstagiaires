"""Financial status from EDOF's read-only Suivi des règlements table."""
import json
from urllib.parse import urlsplit

import edof_directory as directory


def read_invoices(context, witness, endpoint, folders, checkpoint):
    origin = urlsplit(endpoint)
    source = urlsplit(witness.url) if witness else None
    scope = f"/edof-api/v1/api/private/siret/{directory.SIRET}/"
    if (not source or witness.method != "GET" or source.scheme != "https"
            or source.netloc != "of.moncompteformation.gouv.fr" or not source.path.startswith(scope)
            or (origin.scheme, origin.netloc, origin.path) !=
               (source.scheme, source.netloc, scope + "organisms/current/factures")):
        raise directory.IncompleteDirectory("billing_scope")

    invoices = {}
    total = None
    offset = page = 0
    previous_date = None
    ordered = True
    while True:
        checkpoint()
        reply = context.request.get(endpoint, headers=directory.private_headers(witness),
            params={"page": page, "max": 100, "sort": "dateFacture", "order": "DESC"},
            max_redirects=0, timeout=15000)
        try:
            directory.check_throttling(reply)
            if reply.status != 200 or urlsplit(reply.url)._replace(query="") != origin:
                raise directory.IncompleteDirectory("billing_response")
            body = reply.body()
            if len(body) > 4_000_000:
                raise directory.IncompleteDirectory("billing_size")
            data = json.loads(body)
        finally:
            reply.dispose()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise directory.IncompleteDirectory("billing_format")
        items, count = data["items"], data.get("numberOfItems")
        if (type(count) is not int or not 0 <= count <= directory.MAX_ROWS
                or total not in (None, count) or offset + len(items) > count or not items and offset < count):
            raise directory.IncompleteDirectory("billing_count")
        total = count
        archival_page = bool(items)
        for item in items:
            if not isinstance(item, dict):
                raise directory.IncompleteDirectory("billing_row")
            day = directory.session_date(item.get("emission"))
            if not day or previous_date and day > previous_date:
                ordered = False
            previous_date = day
            archival_page = archival_page and bool(day and day < directory.FIRST_SESSION)
            folder = str(item.get("numeroDossier") or "")
            if folder not in folders or item.get("typeFacture") != "FACTURE" or not item.get("numeroFacture"):
                continue
            # An advance is not a final invoice. A dossier with several final
            # invoices is paid only when the portal reports every one as settled.
            invoices[folder] = invoices.get(folder, True) and item.get("status") == "VERSE"
        offset += len(items)
        if offset == total or ordered and archival_page:
            return invoices
        page += 1


def apply_statements(rows, invoices, previous):
    for folder, row in rows.items():
        if invoices is not None and folder in invoices:
            row["billing_state"] = "billed"
            row["payment_state"] = "Issued" if invoices[folder] else "Waiting"
            row["billing_from_statements"] = True
        elif invoices is None and not row.get("billing_state") and not row.get("payment_state"):
            old = previous.get(folder, {})
            if old.get("billing_from_statements") and row.get("state") == old.get("state"):
                for field in ("billing_state", "payment_state", "billing_from_statements"):
                    row[field] = old[field]
