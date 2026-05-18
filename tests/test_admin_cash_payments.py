import unittest

import app as gestion_app


class AdminCashPaymentsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.data = {
            "sessions": [
                {
                    "id": "S-CASH",
                    "name": "APS Mai",
                    "training_type": "APS",
                    "date_start": "2026-05-20",
                    "date_end": "2026-05-24",
                    "trainees": [
                        {
                            "id": "T-PENDING",
                            "last_name": "DUPONT",
                            "first_name": "Alice",
                            "email": "alice@example.test",
                            "phone": "0600000001",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "300",
                            "cash_payment_installments": [
                                {"amount": 100, "date": "2026-05-16"},
                            ],
                        },
                        {
                            "id": "T-SETTLED",
                            "last_name": "MARTIN",
                            "first_name": "Bruno",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "250",
                            "cash_payment_installments": [
                                {"amount": 125, "date": "2026-05-15"},
                                {"amount": 125, "date": "2026-05-17"},
                            ],
                            "cash_payment_settled": True,
                            "cash_payment_settled_date": "2026-05-17",
                            "cash_payment_settled_comment": "Reçu remis",
                        },
                        {
                            "id": "T-NO-CASH",
                            "last_name": "DURAND",
                            "first_name": "Camille",
                        },
                    ],
                },
                {
                    "id": "S-ARCHIVED",
                    "name": "Session archivée",
                    "training_type": "APS",
                    "archived": True,
                    "trainees": [
                        {
                            "id": "T-ARCHIVED",
                            "last_name": "ARCHIVE",
                            "first_name": "Anne",
                            "cash_payment_enabled": True,
                            "cash_payment_amount": "999",
                        }
                    ],
                },
            ]
        }
        gestion_app.load_data = lambda: self.data
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data

    def test_dashboard_stats_and_rows_include_cash_details(self):
        response = self.client.get("/admin/sessions/paiement-especes")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Paiement espèces", html)
        self.assertIn("DUPONT Alice", html)
        self.assertIn("MARTIN Bruno", html)
        self.assertIn("300,00 €", html)
        self.assertIn("200,00 €", html)
        self.assertIn("550,00 €", html)
        self.assertIn("350,00 €", html)
        self.assertIn("Reçu remis", html)
        self.assertIn("@page{size:A4 landscape;margin:8mm}", html)
        self.assertIn(".cash-table{width:100%!important;min-width:0!important;table-layout:fixed", html)
        self.assertIn(".cash-table-wrap{overflow:visible!important", html)
        self.assertNotIn("ARCHIVE Anne", html)
