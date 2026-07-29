import unittest

import app


class OtherFinancingInvoiceRecipientTests(unittest.TestCase):
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

    def test_admin_trainee_modal_collects_company_and_invoice_notes(self):
        template = open("templates/admin_trainee.html", encoding="utf-8").read()
        self.assertIn("Entreprise à facturer", template)
        self.assertIn('id="invoiceCompanyEmail"', template)
        self.assertIn('id="invoiceCompanyAddress"', template)
        self.assertIn('id="invoiceNotes"', template)
        self.assertIn('class="invoice-notes-field"', template)
        self.assertIn("invoiceRecipient", template)


if __name__ == "__main__":
    unittest.main()
