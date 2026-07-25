import os
from unittest.mock import patch

import app as gestion_app


def test_qonto_cron_requires_a_configured_secret():
    client = gestion_app.app.test_client()
    with patch.dict(os.environ, {}, clear=True):
        response = client.post("/internal/cron/qonto-sync")

    assert response.status_code == 403
    assert response.get_json()["error"] == "forbidden"


def test_qonto_cron_syncs_billing_lines_and_legacy_trainee_invoices():
    data = {
        "sessions": [{
            "id": "S1",
            "name": "Session Qonto",
            "date_start": "2026-08-01",
            "trainees": [{
                "id": "trainee-1",
                "first_name": "Billing",
                "last_name": "Trainee",
                "personal_amount": 100,
            }, {
                "id": "legacy-trainee",
                "first_name": "Legacy",
                "last_name": "Trainee",
                "qonto_invoice": {"qonto_invoice_id": "legacy-invoice", "qonto_invoice_status": "sent"},
            }],
        }],
        "billing_lines": [{
            "id": gestion_app._billing_line_id("S1", "trainee-1", "PERSONNEL", "legacy"),
            "traineeId": "trainee-1",
            "sessionId": "S1",
            "financingType": "PERSONNEL",
            "qontoInvoiceId": "billing-invoice",
        }],
    }
    saved = []
    client = gestion_app.app.test_client()

    def get_invoice(invoice_id):
        return {"client_invoice": {"id": invoice_id, "status": "paid", "total_amount": {"value": "100.00"}, "amount_paid": {"value": "100.00"}}}

    with patch.dict(os.environ, {"CRON_SECRET": "cron-secret"}), \
         patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
         patch.object(gestion_app, "load_data", return_value=data), \
         patch.object(gestion_app, "save_data", side_effect=saved.append), \
         patch.object(gestion_app, "get_qonto_invoice", side_effect=get_invoice):
        response = client.post("/internal/cron/qonto-sync", headers={"X-Cron-Secret": "cron-secret"})

    assert response.status_code == 200
    assert response.get_json()["synced_count"] == 2
    assert data["billing_lines"][0]["paymentStatus"] == "paid"
    assert data["sessions"][0]["trainees"][1]["qonto_invoice"]["qonto_invoice_status"] == "paid"
    assert len(saved) == 1


def test_qonto_cron_reports_unavailable_qonto_without_erasing_data():
    client = gestion_app.app.test_client()
    with patch.dict(os.environ, {"CRON_SECRET": "cron-secret"}), patch.object(gestion_app, "_qonto_is_configured", return_value=False):
        response = client.post("/internal/cron/qonto-sync", headers={"X-Cron-Secret": "cron-secret"})

    assert response.status_code == 503
    assert response.get_json()["error"] == "qonto_not_configured"
