import unittest

import app as gestion_app


class QontoClientPayloadTests(unittest.TestCase):
    def test_client_payload_never_includes_phone(self):
        billing_address = {
            "street_address": "10 rue de Paris",
            "city": "Paris",
            "zip_code": "75001",
            "country_code": "FR",
        }
        payload = gestion_app.build_qonto_client_payload(
            {
                "name": "Jean Dupont",
                "first_name": "Jean",
                "last_name": "Dupont",
                "email": "jean@example.com",
                "phone": "0665245271",
            },
            billing_address,
        )

        self.assertNotIn("phone", payload)
        self.assertEqual(
            payload,
            {
                "name": "Jean Dupont",
                "first_name": "Jean",
                "last_name": "Dupont",
                "email": "jean@example.com",
                "currency": "EUR",
                "locale": "FR",
                "address": "10 rue de Paris",
                "city": "Paris",
                "zip_code": "75001",
                "country_code": "FR",
                "billing_address": {
                    "street_address": "10 rue de Paris",
                    "city": "Paris",
                    "zip_code": "75001",
                    "country_code": "FR",
                },
            },
        )

    def test_invalid_string_phone_safety_removes_field(self):
        payload = {"name": "Jean Dupont", "phone": "0665245271"}

        sanitized = gestion_app.remove_invalid_qonto_phone(payload)

        self.assertIs(sanitized, payload)
        self.assertNotIn("phone", sanitized)

    def test_build_qonto_phone_formats_french_numbers_for_future_use(self):
        self.assertEqual(
            gestion_app.build_qonto_phone("06 65 24 52 71"),
            {"country_code": "+33", "number": "665245271"},
        )
        self.assertEqual(
            gestion_app.build_qonto_phone("+33 6 65 24 52 71"),
            {"country_code": "+33", "number": "665245271"},
        )
        self.assertIsNone(gestion_app.build_qonto_phone("12345"))


if __name__ == "__main__":
    unittest.main()
