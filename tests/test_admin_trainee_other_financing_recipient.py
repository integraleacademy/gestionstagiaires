import unittest

import app


class OtherFinancingInvoiceRecipientTests(unittest.TestCase):
    def test_existing_company_is_found_by_siret_before_email(self):
        original_find_tax = app.find_qonto_client_by_tax_identification_number
        original_search = app.search_qonto_client
        app.find_qonto_client_by_tax_identification_number = lambda tax_id: {
            "id": "existing-company", "tax_identification_number": tax_id
        }
        app.search_qonto_client = lambda criteria: self.fail("email/name fallback must not run")
        try:
            client = app.find_existing_qonto_client({
                "kind": "company",
                "name": "AZZERA PROTECT",
                "email": "yannice.libault@azzeraprotect.fr",
                "tax_identification_number": "92492699100010",
            })
        finally:
            app.find_qonto_client_by_tax_identification_number = original_find_tax
            app.search_qonto_client = original_search

        self.assertEqual(client["id"], "existing-company")

    def test_retries_company_creation_without_rejected_optional_siret(self):
        payloads = []
        original_create = app.create_qonto_client

        def fake_create(payload):
            normalized = payload.get("client", payload)
            payloads.append(dict(normalized))
            if normalized.get("tax_identification_number"):
                raise app.QontoApiError(
                    422,
                    '{"errors":[{"field":"tax_identification_number","message":"is invalid"}]}',
                )
            return {"id": "company-client"}

        app.create_qonto_client = fake_create
        try:
            client = app.create_qonto_client_with_optional_tax_id({
                "client": {
                    "kind": "company",
                    "name": "AZZERA PROTECT",
                    "tax_identification_number": "92492699100010",
                }
            })
        finally:
            app.create_qonto_client = original_create

        self.assertEqual(client["id"], "company-client")
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["tax_identification_number"], "92492699100010")
        self.assertNotIn("tax_identification_number", payloads[1])

    def test_does_not_retry_company_creation_for_unrelated_qonto_error(self):
        original_create = app.create_qonto_client
        app.create_qonto_client = lambda payload: (_ for _ in ()).throw(
            app.QontoApiError(422, '{"errors":[{"field":"email","message":"is invalid"}]}')
        )
        try:
            with self.assertRaises(app.QontoApiError):
                app.create_qonto_client_with_optional_tax_id({
                    "kind": "company",
                    "name": "Entreprise Exemple",
                    "tax_identification_number": "12345678900012",
                })
        finally:
            app.create_qonto_client = original_create

    def test_recipient_payload_replaces_trainee_with_company(self):
        line = {
            "financingType": "AUTRE",
            "traineeEmail": "stagiaire@example.com",
            "clientName": "Jean Dupont",
        }

        app._apply_invoice_recipient_payload(line, {
            "invoiceRecipient": {
                "companyName": "Entreprise Exemple",
                "email": "compta@example.com",
                "address": "10 rue des Entreprises",
                "zipCode": "75001",
                "city": "Paris",
                "siret": "12345678900012",
                "invoiceNotes": "Dossier ABC-42",
            }
        })

        self.assertEqual(line["clientName"], "Entreprise Exemple")
        self.assertEqual(line["clientEmail"], "compta@example.com")
        self.assertEqual(line["clientAddress"], "10 rue des Entreprises")
        self.assertEqual(line["clientZipCode"], "75001")
        self.assertEqual(line["clientCity"], "Paris")
        self.assertEqual(line["invoiceNotes"], "Dossier ABC-42")
        client = app.build_qonto_client_payload(line, line, {}, "AUTRE")
        self.assertEqual(client["kind"], "company")
        self.assertEqual(client["name"], "Entreprise Exemple")
        self.assertEqual(client["email"], "compta@example.com")

    def test_personal_financing_ignores_company_recipient_override(self):
        line = {"financingType": "PERSONNEL", "clientName": "Jean Dupont"}
        app._apply_invoice_recipient_payload(line, {
            "invoiceRecipient": {"companyName": "Entreprise Exemple"}
        })
        self.assertEqual(line, {"financingType": "PERSONNEL", "clientName": "Jean Dupont"})

    def test_company_invoice_without_email_does_not_use_trainee_email(self):
        line = {
            "financingType": "AUTRE",
            "companyName": "Entreprise Exemple",
            "clientAddress": "10 rue des Entreprises",
            "clientZipCode": "75001",
            "clientCity": "Paris",
            "traineeEmail": "stagiaire@example.com",
        }

        client = app.build_qonto_client_payload(line, line, {}, "AUTRE")

        self.assertEqual(client["kind"], "company")
        self.assertIsNone(client["email"])
        self.assertEqual(app.validate_qonto_client_payload(client, "AUTRE"), [])

    def test_admin_trainee_modal_collects_company_and_invoice_notes(self):
        with open("templates/admin_trainee.html", encoding="utf-8") as template_file:
            template = template_file.read()
        self.assertIn("Entreprise à facturer", template)
        self.assertIn('id="invoiceCompanyEmail"', template)
        self.assertIn("Email de facturation (facultatif)", template)
        self.assertNotIn("!recipient.companyName||!recipient.email", template)
        self.assertIn('id="invoiceCompanyAddress"', template)
        self.assertIn('id="invoiceNotes"', template)
        self.assertIn('class="invoice-notes-field"', template)
        self.assertIn("invoiceRecipient", template)


if __name__ == "__main__":
    unittest.main()
