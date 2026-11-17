import copy
from unittest.mock import Mock, patch

import pytest

import app as portal


@pytest.mark.parametrize("source_partner", [None, "partner-a"])
def test_personal_invoice_list_preserves_legacy_rows_and_scopes_billing_work(monkeypatch, source_partner):
    def training(sid, partner, trainees):
        return {"id": sid, "training_type": "APS", "date_start": "2026-10-01",
                "partner_id": partner, "trainees": trainees}

    def invoice(sid, tid, kind, ref, provider_id, status, **extra):
        # Old persisted lines often only contain the computed line ID.
        return {"id": portal._billing_line_id(sid, tid, kind, ref),
                "qontoInvoiceId": provider_id, "invoiceStatus": status, **extra}

    monkeypatch.setattr(portal, "_now_iso", lambda: "2026-11-01T09:00:00Z")
    person = {"id": "person", "public_token": "own", "first_name": "Learner",
              "personal_amount": 100, "other_amount": 30, "cpf_amount": 500,
              "qonto_invoice": {"qonto_invoice_id": "own-cpf", "amount_ttc": 500,
                                "qonto_invoice_status": "paid", "qonto_invoice_paid_at": "2026-10-15",
                                "client_name": portal.CPF_QONTO_CLIENT_NAME},
              "financings": [{"id": "opco", "type": "OPCO", "amount": 240},
                             {"id": "company", "type": "ENTREPRISE", "amount": 20}]}
    peer = {"id": "peer", "public_token": "other", "first_name": "Peer", "personal_amount": 70}
    source = training("course", source_partner, [peer, person])
    if source_partner is None:
        del source["partner_id"]
    other = training("another-course", "partner-B", [dict(person, public_token="third")])
    data = {"sessions": [other, source], "billing_lines": [
        invoice("course", "person", "PERSONNEL", "legacy", "own-personal", "sent", amountTTC=100),
        invoice("course", "person", "AUTRE", "legacy", "", "draft", qontoDraftId="own-draft"),
        invoice("course", "person", "OPCO", "opco", "own-finalized", "finalized", finalizedAt="2026-10-25"),
        invoice("course", "person", "ENTREPRISE", "company", "hidden", "cancelled"),
        invoice("course", "peer", "PERSONNEL", "legacy", "same-course-peer", "sent"),
        invoice("another-course", "person", "PERSONNEL", "legacy", "different-course", "sent"),
    ]}
    before = copy.deepcopy(data)
    # Run the former global computation as the reference, freezing generated dates.
    with patch.object(portal, "_public_registration_billing_lines", side_effect=lambda d, *args: portal._billing_lines(d)):
        reference = portal._public_invoice_lines_for_trainee(data, source, person)
    assert {r["invoice_id"] for r in reference} == {"own-personal", "own-draft", "own-finalized", "own-cpf"}
    builder = Mock(wraps=portal.buildBillingLinesFromSessions)
    monkeypatch.setattr(portal, "buildBillingLinesFromSessions", builder)
    actual = portal._public_invoice_lines_for_trainee(data, source, person)
    assert actual == reference
    assert portal._public_invoice_lines_for_trainee(data, source, {"trainee_id": "person"}) == reference
    assert [[t["public_token"] for t in s["trainees"]] for s in builder.call_args.args[0]] == [["own"]]
    assert data == before


def test_personal_invoice_download_checks_the_authenticated_registration(monkeypatch):
    person = {"id": "p", "first_name": "Learner", "public_token": "own", "personal_amount": 100}
    peer = dict(person, id="q", public_token="other")
    training = {"id": "s", "training_type": "APS", "date_start": "2026-10-01", "trainees": [person, peer]}
    lid = portal._billing_line_id("s", "q", "PERSONNEL", "legacy")
    data = {"sessions": [training], "billing_lines": [{"id": lid, "qontoInvoiceId": "other", "invoiceStatus": "sent"}]}
    monkeypatch.setattr(portal, "load_data", lambda: data)
    fetch = Mock(return_value=(b"%PDF-mock", "invoice.pdf"))
    monkeypatch.setattr(portal, "fetch_qonto_client_invoice_pdf", fetch)
    with portal.app.test_client() as client:
        other_url = f"/espace/other/factures/{lid}"
        assert client.get(other_url).status_code == 302
        with client.session_transaction() as auth:
            auth["public_auth_own"] = True
        assert client.get(f"/espace/own/factures/{lid}").status_code == 403
        assert client.get(other_url).status_code == 302
        fetch.assert_not_called()
        with client.session_transaction() as auth:
            auth["public_auth_other"] = True
        assert client.get(other_url).data == b"%PDF-mock"
    fetch.assert_called_once_with("other")


def test_same_registration_ids_across_partners_resolve_by_authenticated_token(monkeypatch):
    def course(partner, token):
        return {"id": "same-course", "partner_id": partner, "name": "APS",
                "training_type": "APS", "date_start": "2026-09-01",
                "trainees": [{"id": "same-person", "public_token": token, "first_name": "Learner", "personal_amount": 90}]}
    a, b = course("partner-a", "token-a"), course("partner-b", "token-b")
    lid = portal._billing_line_id("same-course", "same-person", "PERSONNEL", "legacy")
    data = {"sessions": [a, b], "billing_lines": [
        {"id": lid, "partner_id": "partner-a", "qontoInvoiceId": "invoice-a", "invoiceStatus": "sent"},
        {"id": lid, "partner_id": "partner-b", "qontoInvoiceId": "invoice-b", "invoiceStatus": "sent"},
        {"id": lid, "qontoInvoiceId": "ambiguous-untagged", "invoiceStatus": "sent"},
    ]}
    monkeypatch.setattr(portal, "load_data", lambda: data)
    fetch = Mock(return_value=(b"%PDF-own", "invoice.pdf"))
    monkeypatch.setattr(portal, "fetch_qonto_client_invoice_pdf", fetch)
    for training, token, remote_id in [(a, "token-a", "invoice-a"), (b, "token-b", "invoice-b")]:
        rows = portal._public_invoice_lines_for_trainee(data, training, training["trainees"][0])
        assert [row["invoice_id"] for row in rows] == [remote_id]
        with portal.app.test_client() as client:
            with client.session_transaction() as auth:
                auth["public_auth_" + token] = True
            assert client.get(f"/espace/{token}/factures/{lid}").data == b"%PDF-own"
        fetch.assert_called_with(remote_id)
