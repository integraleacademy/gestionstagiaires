import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as gestion_app


class AdminTraineeCpfQontoInvoiceTests(unittest.TestCase):
    def _data(self, *, status="finalized", paid=0, paid_at=""):
        return {
            "sessions": [{
                "id": "S-CPF",
                "name": "Session APS",
                "training_type": "APS",
                "date_start": "2026-09-01",
                "date_end": "2026-09-30",
                "trainees": [{
                    "id": "T-CPF",
                    "first_name": "Alice",
                    "last_name": "Martin",
                    "cpf_amount": 3050,
                    "personal_amount": 1150,
                    "qonto_invoice": {
                        "qonto_invoice_id": "inv_cpf_3050",
                        "qonto_invoice_number": "F-CPF-2026-42",
                        "qonto_invoice_status": status,
                        "qonto_invoice_amount_paid": paid,
                        "qonto_invoice_paid_at": paid_at,
                        "qonto_invoice_url": "https://qonto.example/inv_cpf_3050",
                        "client_name": gestion_app.CPF_QONTO_CLIENT_NAME,
                        "amount_ttc": 3050,
                        "created_at": "2026-08-12T09:30:00Z",
                    },
                }],
            }],
            "billing_lines": [],
        }

    def _without_local_cpf_invoice(self):
        data = self._data()
        data["sessions"][0]["trainees"][0].pop("qonto_invoice")
        return data

    def _remote_invoice(self, invoice_id="inv_discovered", **changes):
        invoice = {
            "id": invoice_id,
            "number": "F-CPF-2026-77",
            "status": "paid",
            "client_id": "cpf-client",
            "total_amount": {"value": "3050.00"},
            "amount_paid": {"value": "3050.00"},
            "paid_at": "2026-10-02T14:00:00Z",
            "performance_start_date": "2026-09-01",
            "performance_end_date": "2026-09-30",
            "created_at": "2026-10-01T09:00:00Z",
            "items": [{
                "title": "Formation APS - Alice Martin - Session du 01/09/2026 au 30/09/2026",
                "description": "Formation APS - Alice Martin",
            }],
        }
        invoice.update(changes)
        return invoice

    def test_existing_wedof_qonto_cpf_invoice_is_exposed_as_paid(self):
        data = self._data(status="paid", paid=3050, paid_at="2026-08-13T10:15:00Z")

        lines = gestion_app._billing_lines(data)
        cpf_line = next(line for line in lines if line["financingType"] == "CPF")

        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_cpf_3050")
        self.assertEqual(cpf_line["qontoInvoiceNumber"], "F-CPF-2026-42")
        self.assertEqual(cpf_line["qonto_invoice"]["total_amount_cents"], 305000)
        self.assertEqual(cpf_line["qonto_invoice"]["paid_amount_cents"], 305000)
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "paid")
        self.assertEqual(cpf_line["paidAt"], "2026-08-13T10:15:00Z")

        summary = gestion_app.calculate_trainee_financial_summary(
            data["sessions"][0]["trainees"][0], lines
        )
        cpf_bucket = summary["by_financer"]["CPF"]
        self.assertTrue(cpf_bucket["qonto_tracked"])
        self.assertEqual(cpf_bucket["invoiced_amount_cents"], 305000)
        self.assertEqual(cpf_bucket["paid_amount_cents"], 305000)
        self.assertEqual(cpf_bucket["remaining_amount_cents"], 0)
        self.assertEqual(cpf_bucket["payment_status"], "paid")
        self.assertEqual(summary["cpf_invoice_entries"][0]["invoice_id"], "inv_cpf_3050")
        # CPF visibility must not inflate the platform-collected personal totals.
        self.assertEqual(summary["planned_total_cents"], 115000)
        self.assertEqual(summary["paid_total_cents"], 0)

    def test_cpf_line_is_not_created_without_an_existing_invoice(self):
        data = self._data()
        trainee = data["sessions"][0]["trainees"][0]
        trainee.pop("qonto_invoice")
        trainee["personal_amount"] = 0

        self.assertEqual(gestion_app._billing_lines(data), [])

    def test_personal_legacy_invoice_is_not_mistaken_for_cpf(self):
        data = self._data()
        trainee = data["sessions"][0]["trainees"][0]
        trainee["cpf_amount"] = 1150
        trainee["qonto_invoice"].update({
            "client_name": "Alice Martin",
            "amount_ttc": 1150,
        })

        lines = gestion_app._billing_lines(data)

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["financingType"], "PERSONNEL")
        self.assertEqual(lines[0]["qontoInvoiceId"], "inv_cpf_3050")

    def test_trainee_endpoint_refreshes_cpf_payment_from_qonto(self):
        data = self._data()
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        remote_invoice = {
            "client_invoice": {
                "id": "inv_cpf_3050",
                "number": "F-CPF-2026-42",
                "status": "paid",
                "total_amount": {"value": "3050.00"},
                "amount_paid": {"value": "3050.00"},
                "paid_at": "2026-08-13T10:15:00Z",
            }
        }
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "get_qonto_invoice", return_value=remote_invoice):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        cpf_line = next(line for line in payload["lines"] if line["financingType"] == "CPF")
        cpf_bucket = payload["financial_summary"]["by_financer"]["CPF"]
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "paid")
        self.assertEqual(cpf_line["qonto_invoice"]["paid_amount_cents"], 305000)
        self.assertEqual(cpf_line["paidAt"], "2026-08-13T10:15:00Z")
        self.assertEqual(cpf_bucket["payment_status"], "paid")
        self.assertEqual(cpf_bucket["remaining_amount_cents"], 0)
        save_data.assert_called_once_with(data)

    def test_trainee_poll_does_not_resync_a_recent_cpf_invoice(self):
        data = self._data()
        data["sessions"][0]["trainees"][0]["qonto_invoice"]["qonto_last_synced_at"] = gestion_app._now_iso()
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(
                 gestion_app,
                 "_billing_lines_for_trainee_session",
                 wraps=gestion_app._billing_lines_for_trainee_session,
             ) as build_lines, \
             patch.object(
                 gestion_app,
                 "get_qonto_invoice",
                 side_effect=AssertionError("a recent CPF invoice must not be re-fetched during polling"),
             ):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        cpf_line = next(line for line in response.get_json()["lines"] if line["financingType"] == "CPF")
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "unpaid")
        save_data.assert_not_called()
        build_lines.assert_called_once_with(data, "T-CPF", "S-CPF")

    def test_trainee_endpoint_discovers_cpf_invoice_missing_from_local_record(self):
        data = self._without_local_cpf_invoice()
        data["sessions"][0]["trainees"][0].update({
            "cpf_amount": 980,
            "personal_amount": 2520,
        })
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        remote_invoice = self._remote_invoice(
            total_amount={"value": "980.00"}, amount_paid={"value": "980.00"},
        )
        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "list_qonto_invoices", return_value={"client_invoices": [remote_invoice], "meta": {"total_pages": 1}}), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": remote_invoice}):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        cpf_line = next(line for line in payload["lines"] if line["financingType"] == "CPF")
        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_discovered")
        self.assertEqual(cpf_line["qontoInvoiceNumber"], "F-CPF-2026-77")
        self.assertEqual(cpf_line["qonto_invoice"]["payment_status"], "paid")
        self.assertEqual(cpf_line["qonto_invoice"]["total_amount_cents"], 98000)
        self.assertEqual(cpf_line["qonto_invoice"]["paid_amount_cents"], 98000)
        self.assertEqual(payload["financial_summary"]["by_financer"]["CPF"]["payment_status"], "paid")
        self.assertEqual(payload["cpf_invoice_discovery"]["status"], "found")
        persisted = next(line for line in data["billing_lines"] if line["financingType"] == "CPF")
        self.assertEqual(persisted["qontoInvoiceId"], "inv_discovered")
        save_data.assert_called_once_with(data)

    def test_wedof_qonto_invoice_id_is_preferred_without_relying_on_title(self):
        data = self._without_local_cpf_invoice()
        data["wedof_links"] = [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "WEDOF-42",
            "cpf_snapshot": {"qonto_invoice_id": "inv_from_wedof"},
        }]
        remote_invoice = self._remote_invoice(
            "inv_from_wedof", items=[], performance_start_date="", performance_end_date="",
        )
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": remote_invoice}), \
             patch.object(gestion_app, "list_qonto_invoices", side_effect=AssertionError("WEDOF reference must avoid a broad Qonto search")):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        cpf_line = next(line for line in response.get_json()["lines"] if line["financingType"] == "CPF")
        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_from_wedof")
        self.assertEqual(cpf_line["financingRef"], "wedof:WEDOF-42")

    def test_wedof_invoice_number_recovers_and_displays_the_cpf_invoice(self):
        data = self._without_local_cpf_invoice()
        data["wedof_links"] = [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "421643740630",
            "cpf_snapshot": {
                "state": "serviceDoneValidated",
                "billing_state": "billed",
                "invoice_number": "FL-2026-374",
            },
        }]
        remote_invoice = self._remote_invoice(
            "inv_from_wedof_number",
            number="FL-2026-374",
            items=[],
            performance_start_date="",
            performance_end_date="",
        )
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", return_value=remote_invoice) as find_invoice, \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": remote_invoice}), \
             patch.object(gestion_app, "list_qonto_invoices", side_effect=AssertionError("The WEDOF number must avoid a broad Qonto search")):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        cpf_line = next(
            line for line in response.get_json()["lines"]
            if line["financingType"] == "CPF"
        )
        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_from_wedof_number")
        self.assertEqual(cpf_line["qontoInvoiceNumber"], "FL-2026-374")
        self.assertEqual(cpf_line["financingRef"], "wedof:421643740630")
        find_invoice.assert_called_once_with("FL-2026-374")

    def test_automatic_trainee_refresh_never_contacts_wedof(self):
        data = self._without_local_cpf_invoice()
        data["wedof_links"] = [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "421643740630",
            "cpf_snapshot": {
                "state": "serviceDoneValidated",
                "billing_state": "billed",
            },
        }]
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "WedofClient") as wedof_client, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "list_qonto_invoices", return_value={"client_invoices": [], "meta": {"total_pages": 1}}):
            polling_response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")
            auto_sync_response = client.post("/api/billing/sync-qonto", json={
                "traineeId": "T-CPF",
                "sessionId": "S-CPF",
                "source": "admin_trainee_auto",
                "refreshWedof": True,
            })

        self.assertEqual(polling_response.status_code, 200)
        self.assertEqual(auto_sync_response.status_code, 200)
        wedof_client.assert_not_called()

    def test_explicit_manual_sync_refreshes_official_wedof_bill_number(self):
        data = self._without_local_cpf_invoice()
        data["wedof_links"] = [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "421643740630",
            "cpf_snapshot": {
                "state": "serviceDoneValidated",
                "billing_state": "billed",
            },
        }]
        remote_invoice = self._remote_invoice(
            "inv_from_wedof_bill_number",
            number="FL-2026-374",
            items=[],
            performance_start_date="",
            performance_end_date="",
        )
        wedof_client = Mock()
        wedof_client.get_registration_folder_interactive.return_value = {
            "externalId": "421643740630",
            "type": "CPF",
            "state": "serviceDoneValidated",
            "billingState": "billed",
            "billNumber": "FL-2026-374",
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "WedofClient", return_value=wedof_client), \
             patch.object(gestion_app, "sync_folder_automation_status"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", return_value=remote_invoice) as find_invoice, \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": remote_invoice}), \
             patch.object(gestion_app, "list_qonto_invoices", side_effect=AssertionError("The official WEDOF bill number must use an exact lookup")):
            response = client.post("/api/billing/sync-qonto", json={
                "traineeId": "T-CPF",
                "sessionId": "S-CPF",
                "source": "admin_trainee",
                "refreshWedof": True,
            })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        cpf_line = next(line for line in payload["lines"] if line["financingType"] == "CPF")
        self.assertEqual(cpf_line["qontoInvoiceId"], "inv_from_wedof_bill_number")
        self.assertEqual(cpf_line["qontoInvoiceNumber"], "FL-2026-374")
        self.assertEqual(data["wedof_links"][0]["cpf_snapshot"]["invoice_number"], "FL-2026-374")
        self.assertEqual(data["wedof_links"][0]["cpf_snapshot"]["billing_state"], "billed")
        find_invoice.assert_called_once_with("FL-2026-374")
        wedof_client.get_registration_folder_interactive.assert_called_once_with(
            "421643740630", operation="cpf_invoice_manual_refresh",
        )

    def test_discovery_rejects_same_cpf_amount_for_another_trainee(self):
        data = self._without_local_cpf_invoice()
        wrong_invoice = self._remote_invoice(
            items=[{"title": "Formation APS - Bob Dupont - Session du 01/09/2026 au 30/09/2026"}],
        )
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "list_qonto_invoices", return_value={"client_invoices": [wrong_invoice], "meta": {"total_pages": 1}}), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": wrong_invoice}):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(line["financingType"] == "CPF" for line in response.get_json()["lines"]))
        self.assertEqual(response.get_json()["cpf_invoice_discovery"]["status"], "not_found")

    def test_discovery_refuses_two_active_matching_invoices(self):
        data = self._without_local_cpf_invoice()
        first = self._remote_invoice("inv_duplicate_1")
        second = self._remote_invoice("inv_duplicate_2", number="F-CPF-2026-78")
        by_id = {first["id"]: first, second["id"]: second}
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "list_qonto_invoices", return_value={"client_invoices": [first, second], "meta": {"total_pages": 1}}), \
             patch.object(gestion_app, "get_qonto_invoice", side_effect=lambda invoice_id: {"client_invoice": by_id[invoice_id]}):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(line["financingType"] == "CPF" for line in response.get_json()["lines"]))
        self.assertEqual(response.get_json()["cpf_invoice_discovery"]["status"], "ambiguous")

    def test_discovery_rejects_invoice_without_a_verifiable_total(self):
        data = self._without_local_cpf_invoice()
        invoice = self._remote_invoice()
        invoice.pop("total_amount")
        invoice["items"] = [{
            "title": "Formation APS - Alice Martin - Session du 01/09/2026 au 30/09/2026",
        }]
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data"), \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "list_qonto_invoices", return_value={"client_invoices": [invoice], "meta": {"total_pages": 1}}), \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": invoice}):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(line["financingType"] == "CPF" for line in response.get_json()["lines"]))

    def test_failed_discovery_is_throttled_during_page_polling(self):
        data = self._without_local_cpf_invoice()
        data["sessions"][0]["trainees"][0]["cpf_qonto_invoice_discovery"] = {
            "status": "not_found",
            "last_attempt_at": gestion_app._now_iso(),
        }
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_qonto_is_configured", return_value=True), \
             patch.object(gestion_app, "list_qonto_invoices", side_effect=AssertionError("polling must be throttled")):
            response = client.get("/api/billing/trainee/T-CPF/session/S-CPF")

        self.assertEqual(response.status_code, 200)
        save_data.assert_not_called()

    def test_recent_failed_discovery_retries_an_exact_wedof_invoice_number(self):
        data = self._without_local_cpf_invoice()
        data["sessions"][0]["trainees"][0]["cpf_qonto_invoice_discovery"] = {
            "status": "not_found",
            "last_attempt_at": gestion_app._now_iso(),
        }
        data["wedof_links"] = [{
            "active": True,
            "session_id": "S-CPF",
            "trainee_id": "T-CPF",
            "external_id": "421643740630",
            "cpf_snapshot": {"invoice_number": "FL-2026-374"},
        }]
        remote_invoice = self._remote_invoice(
            "inv_exact_after_throttle",
            number="FL-2026-374",
            items=[],
            performance_start_date="",
            performance_end_date="",
        )

        with patch.object(gestion_app, "_cpf_qonto_client_id", return_value="cpf-client"), \
             patch.object(gestion_app, "find_qonto_invoice_by_number", return_value=remote_invoice) as find_invoice, \
             patch.object(gestion_app, "get_qonto_invoice", return_value={"client_invoice": remote_invoice}), \
             patch.object(gestion_app, "list_qonto_invoices", side_effect=AssertionError("Exact WEDOF lookup expected")):
            line, changed = gestion_app._discover_cpf_qonto_invoice(
                data,
                data["sessions"][0],
                data["sessions"][0]["trainees"][0],
            )

        self.assertTrue(changed)
        self.assertIsNotNone(line)
        self.assertEqual(line["qontoInvoiceId"], "inv_exact_after_throttle")
        find_invoice.assert_called_once_with("FL-2026-374")

    def test_paid_qonto_status_without_amount_paid_is_still_settled(self):
        normalized = gestion_app.normalize_qonto_invoice_payment_data({
            "id": "inv-paid",
            "status": "paid",
            "total_amount": {"value": "980.00"},
            "paid_at": "2026-08-13",
        })

        self.assertEqual(normalized["qonto_amount_paid_cents"], 98000)
        self.assertEqual(normalized["qonto_remaining_amount_cents"], 0)
        self.assertEqual(normalized["qonto_payment_status"], "paid")

    def test_historical_cpf_client_name_is_accepted_even_if_client_id_changed(self):
        matches, has_evidence = gestion_app._qonto_invoice_has_cpf_client({
            "client_id": "legacy-cpf-client",
            "client": {"name": "Mon Compte Formation géré par la Caisse des Dépôts"},
        }, cpf_client_id="current-cpf-client")

        self.assertTrue(matches)
        self.assertTrue(has_evidence)

    def test_template_shows_cpf_invoice_and_keeps_it_read_only(self):
        template = (Path(__file__).parents[1] / "templates" / "admin_trainee.html").read_text()

        self.assertIn("Visualiser la facture", template)
        self.assertIn("Facturée dans WEDOF", template)
        self.assertIn("Ouvrir dans WEDOF", template)
        self.assertIn("currentCpfWedofInvoice", template)
        self.assertIn("Facture payée", template)
        self.assertIn("Payée le", template)
        self.assertIn("qonto_tracked", template)
        self.assertIn("!isCpfQontoLine(line)&&!lineHasGeneratedInvoice(line)", template)
        self.assertIn("const cpfTrackingOnly = isCpfQontoLine(l);", template)
        self.assertIn("source:'admin_trainee_auto'", template)
        self.assertNotIn("source:'admin_trainee_auto',refreshWedof:true", template)
        self.assertIn("source:'admin_trainee',refreshWedof:true", template)


if __name__ == "__main__":
    unittest.main()
