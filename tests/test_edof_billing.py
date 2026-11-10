import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import edof_billing
import edof_directory
from integrale_edof_dashboard import associable, category


def test_official_register_separates_final_invoices_from_advances_and_unpaid_items():
    scope = f"https://of.moncompteformation.gouv.fr/edof-api/v1/api/private/siret/{edof_directory.SIRET}/"
    url = scope + "organisms/current/factures"
    witness = Mock(method="GET", url=scope + "organisms/current/registration-folders/pad")
    witness.all_headers.return_value = {}
    rows = {str(n): {"state": "serviceDoneValidated"} for n in range(100000, 100004)}
    def invoice(folder, number, state, kind="FACTURE"):
        return {"numeroDossier": folder, "numeroFacture": number, "emission": "01/10/2026",
                "typeFacture": kind, "status": state}
    pages = [[invoice(100000, "F-1", "VERSE"), invoice(100001, "F-2", "VERSE")],
             [invoice(100001, "F-3", "EN_ATTENTE"), invoice(100002, "A-4", "VERSE", "AVANCE")]]
    request = Mock()
    def read(target, **kwargs):
        assert target == url and kwargs["max_redirects"] == 0
        reply = Mock(url=url + "?page=0", status=200)
        reply.body.return_value = json.dumps({"numberOfItems": 4, "items": pages[kwargs["params"]["page"]]}).encode()
        return reply
    request.get.side_effect = read
    register = edof_billing.read_invoices(SimpleNamespace(request=request), witness, url, rows, lambda:None)
    edof_billing.apply_statements(rows, register, {})
    assert [category(r) for r in rows.values()] == ["paid", "invoiced", "billable", "billable"]
    assert [associable(r) for r in rows.values()] == [False, False, True, True]
    with pytest.raises(edof_directory.IncompleteDirectory):
        edof_billing.read_invoices(SimpleNamespace(request=request), witness, "https://example.invalid/", rows, lambda:None)
    fresh = {key: {"state": "serviceDoneValidated"} for key in rows}
    fresh["100001"]["billing_state"] = "toBill"
    edof_billing.apply_statements(fresh, None, rows)
    assert category(fresh["100000"]) == "paid" and category(fresh["100001"]) == "billable"
