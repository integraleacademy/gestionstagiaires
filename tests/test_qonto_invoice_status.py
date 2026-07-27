import hashlib
import hmac
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as gestion_app


class QontoInvoiceStatusTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "sessions": [
                {
                    "id": "S1",
                    "trainees": [
                        {
                            "id": "T1",
                            "qonto_invoice": {
                                "qonto_invoice_id": "inv_123",
                                "qonto_invoice_number": "F-001",
                                "qonto_invoice_status": "sent",
                            },
                        }
                    ],
                }
            ]
        }
        self.saved = []

    def test_sync_qonto_invoice_status_updates_payment_fields(self):
        remote = {
            "client_invoice": {
                "id": "inv_123",
                "number": "F-001",
                "status": "paid",
                "paid_at": "2026-06-29T10:15:00Z",
                "amount_paid": {"value": "1200.50", "currency": "EUR"},
            }
        }
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(gestion_app, "save_data", side_effect=self.saved.append), patch.object(gestion_app, "get_qonto_invoice", return_value=remote):
            invoice = gestion_app.syncQontoInvoiceStatus("inv_123")

        self.assertEqual(invoice["qonto_invoice_status"], "paid")
        self.assertEqual(invoice["qonto_invoice_paid_at"], "2026-06-29T10:15:00Z")
        self.assertEqual(invoice["qonto_invoice_amount_paid"], 1200.50)
        self.assertEqual(len(self.saved), 1)

    def test_qonto_webhook_verifies_signature_and_updates_local_invoice(self):
        secret = "webhook-secret"
        body = {
            "event": "v1/client-invoices.updated",
            "data": {
                "id": "inv_123",
                "status": "paid",
                "paid_at": "2026-06-29T11:30:00Z",
                "amount_paid": "950",
            },
        }
        raw = json.dumps(body).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": secret}), patch.object(gestion_app, "load_data", return_value=self.data), patch.object(gestion_app, "save_data", side_effect=self.saved.append):
            response = client.post("/api/qonto/webhooks", data=raw, headers={"Content-Type": "application/json", "X-Qonto-Signature": signature})

        self.assertEqual(response.status_code, 200)
        invoice = self.data["sessions"][0]["trainees"][0]["qonto_invoice"]
        self.assertEqual(invoice["qonto_invoice_status"], "paid")
        self.assertEqual(invoice["qonto_invoice_paid_at"], "2026-06-29T11:30:00Z")
        self.assertEqual(invoice["qonto_invoice_amount_paid"], 950.0)
        self.assertEqual(len(self.saved), 1)

    def test_manual_sepa_sync_refreshes_signed_mandate_and_creates_installments(self):
        line = {
            "paymentMode": "sepa_direct_debit",
            "qontoClientId": "client_123",
            "qonto_direct_debit_mandate_id": "mandate_123",
            "qonto_mandate_status": "pending",
            "mandateStatus": "pending",
            "sepa_payment_plan": {"installments": [{"index": 1, "amount": 100, "status": "pending"}]},
        }
        with patch.object(gestion_app, "list_qonto_direct_debit_mandates", return_value={
            "direct_debit_mandates": [{"id": "mandate_123", "status": "signed", "signed_at": "2026-07-24T10:00:00Z"}]
        }), patch.object(gestion_app, "ensure_qonto_sepa_installments_for_line", return_value={"created": 4}):
            gestion_app._sync_qonto_direct_debit_line(line)

        self.assertEqual(line["qonto_mandate_status"], "signed")
        self.assertEqual(line["mandateStatus"], "signed")
        self.assertEqual(line["qonto_mandate_signed_at"], "2026-07-24T10:00:00Z")

    def test_sepa_installments_expose_due_dates_to_the_dashboard(self):
        line = {
            "paymentMode": "sepa_direct_debit",
            "mandateStatus": "signed",
            "sepa_payment_plan": {
                "installments": [
                    {"index": 1, "amount": 582.5, "due_date": "2026-08-24", "status": "scheduled"},
                ],
            },
        }

        gestion_app._sync_sepa_aliases(line)

        installment = line["directDebitInstallments"][0]
        self.assertEqual(installment["date"], "2026-08-24")
        self.assertEqual(installment["due_date"], "2026-08-24")
        self.assertEqual(line["qontoPaymentGlobalStatus"], "Prélèvements programmés")

    def test_trainee_dashboard_supports_legacy_due_date_and_scheduled_mandates(self):
        template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")

        self.assertIn("function installmentDate(installment)", template)
        self.assertIn("installment?.date||installment?.due_date", template)
        self.assertIn("Prélèvements programmés", template)
        self.assertIn("function qontoScheduleState(lines)", template)
        self.assertIn("✅ Mandat OK", template)
        self.assertIn("✅ Échéancier OK", template)
        self.assertIn("qonto_direct_debit_subscription_id", template)

    def test_webhook_subscription_includes_sepa_events(self):
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "s" * 32}), patch.object(gestion_app, "_qonto_request", side_effect=[
            {"webhook_subscriptions": []},
            {"webhook_subscription": {"id": "hook_123"}},
        ]) as request:
            result = gestion_app.ensure_qonto_webhook_subscription()

        self.assertTrue(result["created"])
        self.assertEqual(request.call_args_list[1].args[2], {
            "callback_url": "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto",
            "types": gestion_app.QONTO_WEBHOOK_EVENT_TYPES,
            "secret": "s" * 32,
            "description": "Synchronisation Qonto - Gestion stagiaires",
        })

    def test_webhook_subscription_keeps_existing_valid_subscription(self):
        existing = {"id": "sub_1", "url": "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto", "event_types": list(gestion_app.QONTO_WEBHOOK_EVENT_TYPES)}
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "s" * 32}), patch.object(gestion_app, "_qonto_request", return_value={"webhook_subscriptions": [existing]}) as request:
            result = gestion_app.ensure_qonto_webhook_subscription()
        self.assertTrue(result["ok"])
        self.assertFalse(result["created"])
        self.assertFalse(result["updated"])
        request.assert_called_once_with("GET", "/v2/webhook_subscriptions")

    def test_webhook_subscription_repairs_incomplete_subscription_without_duplicate(self):
        existing = {"id": "sub_1", "url": "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto", "event_types": ["v1/client-invoices"]}
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "s" * 32}), patch.object(gestion_app, "_qonto_request", side_effect=[{"webhook_subscriptions": [existing]}, {"webhook_subscription": {**existing, "event_types": list(gestion_app.QONTO_WEBHOOK_EVENT_TYPES)}}]) as request:
            result = gestion_app.ensure_qonto_webhook_subscription()
        self.assertTrue(result["updated"])
        self.assertFalse(result["created"])
        self.assertEqual(request.call_args_list[1].args[:2], ("PUT", "/v2/webhook_subscriptions/sub_1"))
        self.assertEqual(request.call_args_list[1].args[2], {
            "callback_url": "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto",
            "types": gestion_app.QONTO_WEBHOOK_EVENT_TYPES,
            "description": "Synchronisation Qonto - Gestion stagiaires",
        })

    def test_webhook_subscription_creates_only_when_absent(self):
        created = {"id": "sub_new", "event_types": list(gestion_app.QONTO_WEBHOOK_EVENT_TYPES)}
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "s" * 32}), patch.object(gestion_app, "_qonto_request", side_effect=[{"webhook_subscriptions": []}, {"webhook_subscription": created}]) as request:
            result = gestion_app.ensure_qonto_webhook_subscription()
        self.assertTrue(result["created"])
        self.assertEqual(request.call_args_list[1].args[:2], ("POST", "/v2/webhook_subscriptions"))
        self.assertEqual(request.call_args_list[1].args[2]["secret"], "s" * 32)
        self.assertNotIn("webhook_subscription", request.call_args_list[1].args[2])


    def test_webhook_creation_posts_flat_json_payload_without_params(self):
        oauth_data = {"qonto_oauth": {"access_token": "webhook-token", "refresh_token": "refresh-token", "expires_at": 9999999999, "scope": gestion_app.QONTO_OAUTH_SCOPE, "environment": "production"}}
        response = Mock(ok=True, status_code=201, text='{"webhook_subscription": {"id": "sub_1"}}', headers={})
        response.json.return_value = {"webhook_subscription": {"id": "sub_1"}}
        payload = {
            "callback_url": "https://gestionstagiaires-r5no.onrender.com/api/webhooks/qonto",
            "types": list(gestion_app.QONTO_WEBHOOK_EVENT_TYPES),
            "secret": "s" * 32,
            "description": "Synchronisation Qonto - Gestion stagiaires",
        }
        with patch.dict(os.environ, {"QONTO_API_BASE_URL": "https://qonto.test"}, clear=False), \
             patch.object(gestion_app, "load_data", return_value=oauth_data), \
             patch.object(gestion_app.requests, "post", return_value=response) as post:
            result = gestion_app._qonto_request("POST", "/v2/webhook_subscriptions", payload)

        self.assertEqual(result, {"webhook_subscription": {"id": "sub_1"}})
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://qonto.test/v2/webhook_subscriptions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer webhook-token")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertEqual(kwargs["json"], payload)
        self.assertNotIn("params", kwargs)
        self.assertNotIn("data", kwargs)
        self.assertNotIn("webhook_subscription", kwargs["json"])
        self.assertTrue(kwargs["json"]["secret"])
        self.assertEqual(kwargs["json"]["types"], gestion_app.QONTO_WEBHOOK_EVENT_TYPES)

    def test_webhook_subscription_requires_configured_secret(self):
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": ""}, clear=False):
            with self.assertRaisesRegex(gestion_app.QontoConfigurationError, "QONTO_WEBHOOK_SECRET"):
                gestion_app.ensure_qonto_webhook_subscription()

    def test_webhook_without_secret_is_rejected_and_recorded(self):
        client = gestion_app.app.test_client()
        data = {"sessions": [], "billing_lines": []}
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "", "QONTO_WEBHOOK_SIGNATURE_SECRET": ""}, clear=False), patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"):
            response = client.post("/api/qonto/webhooks", json={"event": "v1/client-invoices", "data": {"id": "inv_1"}})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(data["qonto_webhook_history"][0]["result"], "rejected")

    def test_webhook_records_last_reception(self):
        client = gestion_app.app.test_client()
        data = {"sessions": [], "billing_lines": []}
        raw = b'{"event":"v1/client-invoices","data":{"id":"inv_1"}}'
        secret = "history-secret"
        signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": secret}), patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"), patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": {"id": "inv_1", "status": "paid", "total_amount": 10, "amount_paid": 10}}):
            response = client.post("/api/qonto/webhooks", data=raw, headers={"Content-Type": "application/json", "X-Qonto-Signature": signature})
        self.assertEqual(response.status_code, 200)
        entry = data["qonto_webhook_history"][0]
        self.assertEqual(entry["event"], "v1/client-invoices")
        self.assertEqual(entry["resource_id"], "inv_1")
        self.assertEqual(entry["result"], "ignored")

    def test_mandate_webhook_accepts_singular_event_name(self):
        secret = "webhook-secret"
        body = {"event": "v2/sepa_direct_debit_mandate.signed", "data": {"id": "mandate_123", "status": "signed"}}
        raw = json.dumps(body).encode("utf-8")
        signature = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": secret}), \
             patch.object(gestion_app, "load_data", return_value={"sessions": [], "billing_lines": []}), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_apply_qonto_mandate_webhook", return_value=True) as apply:
            response = client.post("/api/qonto/webhooks", data=raw, headers={"Content-Type": "application/json", "X-Qonto-Signature": signature})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["updated"])
        apply.assert_called_once()


    def test_missing_qonto_billing_invoice_marks_line_to_control(self):
        data = {
            "sessions": [{"id": "S1", "name": "APS NOVEMBRE 2026", "date_start": "2026-11-01", "date_end": "2026-11-05", "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 1200}]}],
            "billing_lines": [{
                "id": gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy"),
                "traineeId": "T1", "sessionId": "S1", "financingType": "PERSONNEL", "financingRef": "legacy",
                "amount": 1200, "invoiceStatus": "draft", "paymentStatus": "unpaid",
                "qontoInvoiceId": "inv_deleted", "qontoInvoiceNumber": "F-2026-001-PROFORMA",
                "invoiceGeneratedAt": "2026-06-29T10:00:00Z", "invoicePdfUrl": "https://qonto.test/inv"
            }]
        }
        line = gestion_app._find_billing_line(data, data["billing_lines"][0]["id"])
        with patch.object(gestion_app, "get_qonto_invoice", side_effect=gestion_app.QontoNotFoundError("Qonto HTTP 404: not found")):
            did_reset, message = gestion_app._sync_billing_line_with_qonto(data, line)

        self.assertTrue(did_reset)
        self.assertIn("à contrôler", message)
        saved_line = gestion_app._find_billing_line(data, data["billing_lines"][0]["id"])
        self.assertEqual(saved_line.get("qontoInvoiceId"), "inv_deleted")
        self.assertEqual(saved_line.get("qontoInvoiceNumber"), "F-2026-001-PROFORMA")
        self.assertEqual(saved_line.get("invoiceGeneratedAt"), "2026-06-29T10:00:00Z")
        self.assertEqual(saved_line["invoiceStatus"], "control")
        self.assertEqual(saved_line["paymentStatus"], "control")
        self.assertIn("introuvable", saved_line.get("syncWarning", ""))

    def test_missing_qonto_billing_invoice_recovers_final_invoice_by_number(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "APS NOVEMBRE 2026", "date_start": "2026-11-01", "date_end": "2026-11-05", "trainees": [{"id": "T1", "first_name": "Rafael", "last_name": "BONELLO-GUTIERREZ", "personal_amount": 1650}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1", "sessionId": "S1", "financingType": "PERSONNEL", "financingRef": "legacy",
                "amount": 1650, "invoiceStatus": "draft", "paymentStatus": "unpaid",
                "qontoInvoiceId": "stale-draft-id", "qontoDraftId": "stale-draft-id",
                "qontoInvoiceNumber": "FL-2026-315-PROFORMA",
                "invoiceGeneratedAt": "2026-07-17T10:00:00Z",
            }]
        }
        remote_final = {
            "id": "final-invoice-id",
            "number": "FL-2026-315",
            "status": "sent",
            "public_url": "https://qonto.test/final-invoice-id",
        }
        line = gestion_app._find_billing_line(data, line_id)
        with patch.object(gestion_app, "get_qonto_invoice", side_effect=gestion_app.QontoNotFoundError("Qonto HTTP 404: not_found")), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", side_effect=[None, remote_final]) as lookup:
            did_reset, message = gestion_app._sync_billing_line_with_qonto(data, line)

        self.assertFalse(did_reset)
        self.assertIn("retrouvée", message)
        self.assertEqual(lookup.call_args_list[0].args[0], "FL-2026-315-PROFORMA")
        self.assertEqual(lookup.call_args_list[1].args[0], "FL-2026-315")
        saved_line = gestion_app._find_billing_line(data, line_id)
        self.assertEqual(saved_line["qontoInvoiceId"], "final-invoice-id")
        self.assertEqual(saved_line["qontoInvoiceNumber"], "FL-2026-315")
        self.assertEqual(saved_line["invoiceStatus"], "sent")
        self.assertEqual(saved_line["paymentStatus"], "unpaid")
        self.assertEqual(saved_line["invoicePdfUrl"], "https://qonto.test/final-invoice-id")
        self.assertFalse(saved_line.get("syncWarning"))

    def test_billing_lines_keep_direct_debit_schedule_from_persisted_line(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{
                "id": "S1",
                "name": "APS NOVEMBRE 2026",
                "date_start": "2026-11-01",
                "date_end": "2026-11-05",
                "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 900}],
            }],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "amount": 900,
                "invoiceStatus": "draft",
                "paymentStatus": "unpaid",
                "qontoInvoiceId": "inv_123",
                "paymentMode": "sepa_direct_debit",
                "paymentPlan": {"mode": "sepa_direct_debit", "installments": 3},
                "directDebitInstallments": [
                    {"date": "2026-07-10", "amount": 300, "status": "scheduled"},
                    {"date": "2026-08-10", "amount": 300, "status": "scheduled"},
                    {"date": "2026-09-10", "amount": 300, "status": "scheduled"},
                ],
                "qontoPaymentGlobalStatus": "Mandat à signer",
                "qonto_direct_debit_mandate_id": "mandate_123",
                "sign_url": "https://qonto.test/sign",
                "mandateStatus": "pending",
            }],
        }

        line = gestion_app._find_billing_line(data, line_id)

        self.assertEqual(line["paymentMode"], "sepa_direct_debit")
        self.assertEqual(line["paymentPlan"]["installments"], 3)
        self.assertEqual(len(line["directDebitInstallments"]), 3)
        self.assertEqual(line["qontoPaymentGlobalStatus"], "Mandat à signer")
        self.assertEqual(line["qonto_direct_debit_mandate_id"], "mandate_123")


    def test_mark_external_billing_line_blocks_qonto_generation(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{
                "id": "S1",
                "name": "VTC",
                "training_type": "VTC",
                "date_start": "2026-11-01",
                "date_end": "2026-11-05",
                "trainees": [{"id": "T1", "first_name": "Clement", "last_name": "VAILLANT", "personal_amount": 1500}],
            }],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "PERSONNEL",
                "financingRef": "legacy",
                "amount": 1500,
                "invoiceStatus": "not_invoiced",
                "paymentStatus": "not_applicable",
                "logs": [],
            }],
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append):
            response = client.post("/api/billing/mark-external", json={"lineId": line_id, "note": "Pennylane F-42"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["line"]["invoiceStatus"], "external_generated")
        self.assertEqual(payload["line"]["paymentStatus"], "not_applicable")
        self.assertEqual(payload["line"]["externalInvoiceNote"], "Pennylane F-42")
        self.assertTrue(payload["line"].get("externalInvoiceMarkedAt"))
        self.assertEqual(len(self.saved), 1)
        ok, result = gestion_app._create_invoice_for_billing_line(data, payload["line"])
        self.assertFalse(ok)
        self.assertTrue(result.get("ignored"))

    def test_billing_dashboard_total_to_invoice_excludes_external_lines(self):
        template = os.path.join(os.path.dirname(__file__), "..", "templates", "admin_sessions_billing.html")
        with open(template, encoding="utf-8") as fh:
            source = fh.read()

        self.assertIn("const statLines=lines;const notGenerated=statLines.filter(l=>!hasInvoice(l)), total=notGenerated.reduce", source)
        self.assertIn("['Total à facturer',fmtMoney(total)]", source)
        self.assertNotIn("Montant non généré", source)
        self.assertIn("['Factures en brouillon',drafts.length]", source)
        self.assertIn("['Factures en attente de paiement',toPay.length]", source)
        self.assertIn("['Factures payées',paid.length]", source)
        self.assertIn("['Factures partiellement payées',partiallyPaid.length]", source)
        self.assertIn("['Factures annulées',cancelled.length]", source)
        self.assertIn("if(nextFilter==='partially_paid')$('paymentFilter').value='partially_paid'", source)
        self.assertIn("if(nextFilter==='cancelled')$('invoiceFilter').value='cancelled'", source)
        self.assertIn('<option value="paid_or_partially_paid">Payée ou partielle</option>', source)
        self.assertIn("['Factures à contrôler',control.length]", source)
        self.assertIn("['a_controler','to_control','needs_review','pending_review']", source)
        self.assertIn("(!knownInvoiceStatuses.includes(invoiceStatus))", source)
        self.assertIn("['canceled','void','voided']", source)

    def test_billing_invoice_download_streams_qonto_pdf_inline(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "CPF", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "CPF",
                "financingRef": "legacy",
                "qontoInvoiceId": "inv_123",
                "qontoInvoiceNumber": "F-001",
                "logs": [],
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "download_qonto_invoice_pdf", return_value=(b"%PDF-1.4 fake", "application/pdf")):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("inline", response.headers.get("Content-Disposition", ""))
        self.assertEqual(response.data, b"%PDF-1.4 fake")
        self.assertTrue(data["billing_lines"][0].get("invoiceDownloadedAt"))

    @unittest.skip("invoicePdfUrl/public_url redirects are forbidden for Qonto PDFs")
    def test_billing_invoice_download_uses_existing_public_url(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "CPF", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "CPF",
                "financingRef": "legacy",
                "qontoInvoiceId": "inv_123",
                "invoicePdfUrl": "https://qonto.test/invoice.pdf",
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://qonto.test/invoice.pdf")

    def test_billing_invoice_download_returns_qonto_error_when_pdf_is_missing(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "Entreprise", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace"}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "traineeFirstName": "Ada",
                "traineeLastName": "Lovelace",
                "formationName": "APS",
                "financingType": "Entreprise",
                "financingRef": "legacy",
                "amount": 1200,
                "vatRate": 20,
                "qontoInvoiceId": "019f6a9e-734e-757c-80b4-5ca32b33b784",
                "qontoInvoiceNumber": "F-001",
                "logs": [],
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "download_qonto_invoice_pdf", side_effect=gestion_app.QontoNotFoundError(404, "Not found")):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.mimetype, "application/json")
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Facture Qonto introuvable", payload["error"])
        self.assertNotIn("Affichage local temporaire", response.get_data(as_text=True))
        log_actions = [entry.get("action") for entry in data["billing_lines"][0]["logs"]]
        self.assertIn("PDF Qonto indisponible", log_actions)

    @unittest.skip("public_url fallback redirects are forbidden for Qonto PDFs")
    def test_billing_invoice_download_redirects_to_qonto_public_url_after_download_404(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "CPF", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace", "cpf_amount": 1200}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "CPF",
                "financingRef": "legacy",
                "qontoInvoiceId": "inv_123",
                "logs": [],
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "download_qonto_invoice_pdf", side_effect=gestion_app.QontoNotFoundError(404, "Not found")), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "public_url": "https://qonto.test/inv_123"}}):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://qonto.test/inv_123")
        self.assertEqual(data["billing_lines"][0]["invoicePdfUrl"], "https://qonto.test/inv_123")


    @unittest.skip("invoice_number/public_url fallback is forbidden for Qonto PDFs")
    def test_billing_invoice_download_recovers_qonto_invoice_by_number_when_id_is_stale(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "Entreprise", "legacy")
        data = {
            "sessions": [{"id": "S1", "name": "Session", "trainees": [{"id": "T1", "first_name": "Ada", "last_name": "Lovelace"}]}],
            "billing_lines": [{
                "id": line_id,
                "traineeId": "T1",
                "sessionId": "S1",
                "financingType": "Entreprise",
                "financingRef": "legacy",
                "qontoInvoiceId": "stale-id",
                "qontoInvoiceNumber": "F-001",
                "logs": [],
            }]
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_find_billing_line", return_value=data["billing_lines"][0]), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "download_qonto_invoice_pdf", side_effect=gestion_app.QontoNotFoundError(404, "Not found")), \
             patch.object(gestion_app, "get_qonto_invoice", side_effect=gestion_app.QontoNotFoundError(404, "Not found")), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", return_value={"id": "fresh-id", "number": "F-001", "public_url": "https://qonto.test/fresh"}):
            response = client.get(f"/api/admin/billing-lines/{line_id}/download-invoice")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://qonto.test/fresh")
        self.assertEqual(data["billing_lines"][0]["qontoInvoiceId"], "fresh-id")
        self.assertEqual(data["billing_lines"][0]["invoicePdfUrl"], "https://qonto.test/fresh")

    @unittest.skip("public_url fallback is forbidden for Qonto PDFs")
    def test_qonto_invoice_download_falls_back_to_invoice_public_url_after_404(self):
        not_found_response = Mock(ok=False, status_code=404, content=b'{"error":"Not found"}', text='{"error":"Not found"}')
        not_found_response.headers = {"Content-Type": "application/json"}
        pdf_response = Mock(ok=True, status_code=200, content=b"%PDF-1.4 fallback")
        pdf_response.headers = {"Content-Type": "application/pdf"}

        with patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_headers", return_value={"Authorization": "login:secret"}), \
             patch.object(gestion_app, "_qonto_base_url", return_value="https://qonto.test"), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "public_url": "https://qonto.test/inv_123.pdf"}}), \
             patch.object(gestion_app.requests, "get", side_effect=[not_found_response, pdf_response]) as mocked_get:
            pdf_bytes, content_type = gestion_app.download_qonto_invoice_pdf("inv_123")

        self.assertEqual(pdf_bytes, b"%PDF-1.4 fallback")
        self.assertEqual(content_type, "application/pdf")
        self.assertEqual(mocked_get.call_args_list[0].args[0], "https://qonto.test/v2/client_invoices/inv_123/download")
        self.assertEqual(mocked_get.call_args_list[1].args[0], "https://qonto.test/inv_123.pdf")

    def test_qonto_webhook_rejects_invalid_signature(self):
        client = gestion_app.app.test_client()
        with patch.dict(os.environ, {"QONTO_WEBHOOK_SECRET": "webhook-secret"}):
            response = client.post("/api/qonto/webhooks", json={"data": {"id": "inv_123"}}, headers={"X-Qonto-Signature": "bad"})

        self.assertEqual(response.status_code, 401)

    def test_billing_lines_reuse_trainee_level_qonto_invoice(self):
        data = {"sessions": [{"id": "S1", "training_type": "APS", "date_start": "2026-09-01", "date_end": "2026-10-01", "trainees": [{
            "id": "T1", "first_name": "Clement", "last_name": "Vaillant", "personal_amount": 1,
            "qonto_invoice": {"qonto_invoice_id": "inv_admin", "qonto_invoice_number": "F-ADMIN", "qonto_invoice_status": "finalized", "amount_ttc": 1, "created_at": "2026-06-30T10:00:00Z"}
        }]}]}
        lines = gestion_app._billing_lines(data)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["qontoInvoiceId"], "inv_admin")
        self.assertEqual(lines[0]["qontoInvoiceNumber"], "F-ADMIN")
        self.assertEqual(lines[0]["invoiceStatus"], "finalized")
        self.assertEqual(lines[0]["paymentStatus"], "unpaid")

    def test_bulk_generate_finalized_refreshes_invoice_number_when_finalize_response_is_sparse(self):
        line_id = gestion_app._billing_line_id("S1", "T1", "PERSONNEL", "legacy")
        data = {
            "sessions": [{
                "id": "S1",
                "name": "APS JUILLET 2026",
                "training_type": "APS",
                "date_start": "2026-07-01",
                "date_end": "2026-07-05",
                "trainees": [{"id": "T1", "first_name": "Alice", "last_name": "Dupont", "email": "alice@example.test", "personal_amount": 900, "address": "1 rue Test", "zip_code": "75001", "city": "Paris"}],
            }],
            "billing_lines": [],
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_invoice_iban", return_value="FR7612345678901234567890123"), \
             patch.object(gestion_app, "search_qonto_client", return_value={"client": {"id": "client_123", "billing_address": {"street_address": "1 rue Test", "zip_code": "75001", "city": "Paris", "country_code": "FR"}}}), \
             patch.object(gestion_app, "create_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "status": "draft"}}), \
             patch.object(gestion_app, "finalize_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "status": "finalized"}}), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "number": "F-2026-123", "status": "finalized"}}), \
             patch.object(gestion_app, "_setup_qonto_direct_debit_for_line"):
            response = client.post("/api/admin/billing-lines/bulk-generate", json={"ids": [line_id], "finalize": True})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["created"][0]["qontoInvoiceNumber"], "F-2026-123")
        self.assertEqual(payload["created"][0]["invoiceStatus"], "finalized")
        saved_line = gestion_app._find_billing_line(data, line_id)
        self.assertEqual(saved_line["qontoInvoiceNumber"], "F-2026-123")
        self.assertTrue(saved_line.get("invoiceGeneratedAt"))

    def test_billing_qonto_generation_updates_existing_client_missing_billing_address(self):
        line = {
            "id": "bill_test",
            "traineeId": "T1",
            "sessionId": "S1",
            "financingType": "PERSONNEL",
            "amount": 4300,
            "clientName": "Alice Dupont",
            "traineeFirstName": "Alice",
            "traineeLastName": "Dupont",
            "traineeEmail": "alice@example.test",
            "clientAddress": "47 allée des cistes",
            "clientZipCode": "83520",
            "clientCity": "Roquebrune sur Argens",
            "dateStart": "2026-07-15",
            "dateEnd": "2026-10-28",
            "formationName": "APS",
            "sessionName": "APS",
            "vatRate": 0,
            "invoiceStatus": "not_invoiced",
            "paymentStatus": "not_applicable",
        }
        data = {"billing_lines": [line], "sessions": []}
        existing_client = {"client": {"id": "client_123", "email": "alice@example.test"}}
        updated_client = {"client": {"id": "client_123", "billing_address": {"street_address": "47 allée des cistes", "zip_code": "83520", "city": "Roquebrune sur Argens", "country_code": "FR"}}}

        with patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_invoice_iban", return_value="FR7612345678901234567890123"), \
             patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data", side_effect=self.saved.append), \
             patch.object(gestion_app, "search_qonto_client", return_value=existing_client), \
             patch.object(gestion_app, "update_qonto_client", return_value=updated_client) as update_client, \
             patch.object(gestion_app, "create_qonto_invoice", return_value={"client_invoice": {"id": "inv_123", "number": "F-123"}}), \
             patch.object(gestion_app, "_setup_qonto_direct_debit_for_line"):
            ok, result = gestion_app._create_invoice_for_billing_line(data, line, {})

        self.assertTrue(ok)
        update_client.assert_called_once()
        payload = update_client.call_args.args[1]
        self.assertEqual(payload["address_line_1"], "47 allée des cistes")
        self.assertEqual(payload["zip_code"], "83520")
        self.assertEqual(payload["city"], "Roquebrune sur Argens")
        self.assertEqual(result["line"]["qontoInvoiceId"], "inv_123")


class BillingStartDateFilterTests(unittest.TestCase):
    def test_billing_lines_include_only_sessions_starting_from_june_2026(self):
        sessions = [
            {
                "id": "S-MAY",
                "name": "APS MAI 2026",
                "date_start": "2026-05-31",
                "date_end": "2026-06-04",
                "trainees": [{"id": "T-MAY", "first_name": "Alice", "last_name": "Avant", "personal_amount": 100}],
            },
            {
                "id": "S-JUNE",
                "name": "APS JUIN 2026",
                "date_start": "2026-06-01",
                "date_end": "2026-06-05",
                "trainees": [{"id": "T-JUNE", "first_name": "Bruno", "last_name": "Debut", "personal_amount": 200}],
            },
            {
                "id": "S-FR",
                "nom": "APS JUIN FR 2026",
                "date_debut": "01/06/2026",
                "date_fin": "05/06/2026",
                "trainees": [{"id": "T-FR", "first_name": "Camille", "last_name": "France", "personal_amount": 300}],
            },
        ]

        lines = gestion_app.buildBillingLinesFromSessions(sessions)

        self.assertEqual({line["sessionId"] for line in lines}, {"S-JUNE", "S-FR"})
        self.assertTrue(all(line["dateStart"] >= "2026-06-01" for line in lines))

    def test_billing_lines_include_vae_sessions_started_before_general_rollout(self):
        sessions = [{
            "id": "S-VAE",
            "training_type": "DIRIGEANT VAE",
            "date_start": "2026-05-01",
            "date_end": "2026-05-30",
            "trainees": [{
                "id": "T-VAE",
                "first_name": "Valerie",
                "last_name": "A",
                "personal_amount": 2640,
            }],
        }]

        lines = gestion_app.buildBillingLinesFromSessions(sessions)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["sessionId"], "S-VAE")
        self.assertEqual(lines[0]["financingType"], "PERSONNEL")
        self.assertEqual(lines[0]["amount"], 2640)


if __name__ == "__main__":
    unittest.main()
