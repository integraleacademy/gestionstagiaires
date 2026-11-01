import pytest

from cpf_tracking import build_cpf_financial_status


@pytest.mark.parametrize("state,label", [
    ("pending", "En attente d’acceptation"),
    ("accepted", "Accepté"),
    ("inTraining", "En formation"),
    ("serviceDoneDeclared", "Service fait déclaré"),
    ("serviceDoneValidated", "Service fait validé"),
    ("invoiced", "Facturé"),
    ("cancelled", "Dossier annulé"),
    ("refused", "Dossier refusé"),
    ("abandoned", "Formation abandonnée"),
    ("newUnknownState", "État à vérifier"),
])
def test_dossier_stage_is_preserved_even_when_an_invoice_exists(state, label):
    view = build_cpf_financial_status(
        {"state": state}, {"invoiceStatus": "sent", "qontoInvoiceNumber": "CPF-42"}, linked=True,
    )
    assert view["stage_label"] == label
    assert view["invoice_status"] == "issued"
    assert view["invoice_number"] == "CPF-42"


@pytest.mark.parametrize("snapshot,code,label", [
    ({"billing_state": "billed"}, "issued", "Facture émise"),
    ({"billingState": "billed"}, "issued", "Facture émise"),
    ({"invoice_number": "F-1"}, "issued", "Facture émise"),
    ({"state": "invoiceSent"}, "issued", "Facture émise"),
    ({"invoice_status": "paid"}, "issued", "Facture émise"),
    ({"invoice_status": "partially_paid"}, "issued", "Facture émise"),
    ({"invoice_status": "draft", "invoice_number": "DRAFT-1"}, "draft", "Brouillon"),
    ({"invoice_status": "cancelled", "billing_state": "billed"}, "cancelled", "Facture annulée"),
    ({"billing_state": "notBilled"}, "not_issued", "Non émise"),
    ({"invoice_status": "not_generated"}, "not_issued", "Non émise"),
    ({"invoice_status": "control"}, "unknown", "Émission à vérifier"),
    ({"qonto_invoice_id": "id-only"}, "unknown", "Émission à vérifier"),
    ({"state": "serviceDoneValidated"}, "unknown", "Émission à vérifier"),
    ({}, "unknown", "Émission à vérifier"),
])
def test_invoice_issuance_requires_its_own_evidence(snapshot, code, label):
    view = build_cpf_financial_status(snapshot, {}, linked=True)
    assert view["invoice_status"] == code
    assert view["invoice_label"] == label


def test_current_local_draft_takes_precedence_over_older_remote_billing():
    view = build_cpf_financial_status(
        {"state": "serviceDoneValidated", "billing_state": "billed"},
        {"invoiceStatus": "draft", "qontoDraftId": "draft-id"}, linked=True,
    )
    assert view["stage_label"] == "Service fait validé"
    assert view["invoice_status"] == "draft"


def test_missing_link_does_not_invent_a_dossier_stage():
    view = build_cpf_financial_status({}, {}, linked=False)
    assert view["stage_label"] == "Dossier CPF à rattacher"
    assert view["invoice_status"] == "unknown"
