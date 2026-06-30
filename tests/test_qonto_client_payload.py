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
        self.assertEqual(payload["type"], "individual")
        self.assertEqual(payload["kind"], "individual")
        self.assertEqual(payload["name"], "Jean Dupont")
        self.assertEqual(payload["first_name"], "Jean")
        self.assertEqual(payload["last_name"], "Dupont")
        self.assertEqual(payload["billing_address"]["street_address"], "10 rue de Paris")


    def test_build_invoice_customer_uses_caisse_des_depots_for_cpf_variants(self):
        for label in ["CPF", " cpf ", "Compte Personnel de Formation", "Mon Compte Formation"]:
            customer = gestion_app.buildInvoiceCustomer(label, {"first_name": "Clement", "last_name": "VAILLANT"})
            self.assertEqual(customer["name"], gestion_app.CPF_QONTO_CLIENT_NAME)
            self.assertEqual(customer["organization"], "Mon Compte Formation")
            self.assertEqual(customer["address"], "56 rue de Lille")
            self.assertEqual(customer["zip_code"], "75356")
            self.assertEqual(customer["city"], "PARIS 07 SP")

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


class QontoCpfClientTests(unittest.TestCase):
    def test_find_qonto_client_by_name_uses_only_filter_name(self):
        calls = []
        def fake_request(method, path, payload=None, params=None):
            calls.append((method, path, payload, params))
            return {"clients": [{"id": "client_cpf", "name": "Caisse des dépôts"}]}

        original = gestion_app._qonto_request
        gestion_app._qonto_request = fake_request
        try:
            client = gestion_app.find_qonto_client_by_name("Caisse des dépôts")
        finally:
            gestion_app._qonto_request = original

        self.assertEqual(client["id"], "client_cpf")
        self.assertEqual(calls, [("GET", "/v2/clients", None, {"filter[name]": "Caisse des dépôts"})])

    def test_get_or_create_cpf_qonto_client_reuses_existing_client(self):
        original_find = gestion_app.find_qonto_client_by_name
        original_create = gestion_app.create_qonto_client
        gestion_app.find_qonto_client_by_name = lambda name: {"id": "existing", "name": name}
        try:
            gestion_app.create_qonto_client = lambda payload: self.fail("CPF client should not be created when it exists")
            client = gestion_app.get_or_create_cpf_qonto_client()
        finally:
            gestion_app.find_qonto_client_by_name = original_find
            gestion_app.create_qonto_client = original_create

        self.assertEqual(client["id"], "existing")

    def test_get_or_create_cpf_qonto_client_creates_company_when_missing(self):
        created_payloads = []
        original_find = gestion_app.find_qonto_client_by_name
        original_create = gestion_app.create_qonto_client
        gestion_app.find_qonto_client_by_name = lambda name: None
        def fake_create(payload):
            created_payloads.append(payload)
            return {"client": {"id": "created"}}
        gestion_app.create_qonto_client = fake_create
        try:
            client = gestion_app.get_or_create_cpf_qonto_client()
        finally:
            gestion_app.find_qonto_client_by_name = original_find
            gestion_app.create_qonto_client = original_create

        self.assertEqual(client["client"]["id"], "created")
        self.assertEqual(created_payloads[0]["client"]["kind"], "company")
        self.assertEqual(created_payloads[0]["client"]["name"], gestion_app.CPF_QONTO_CLIENT_NAME)
        self.assertEqual(created_payloads[0]["client"]["email"], "")
        self.assertEqual(created_payloads[0]["client"]["tax_identification_number"], "18002002600019")
        self.assertEqual(created_payloads[0]["client"]["billing_address"]["street_address"], "56 rue de Lille")

    def test_invalid_qonto_queryfields_marker_is_blocked_before_api_call(self):
        original_configured = gestion_app._qonto_is_configured
        gestion_app._qonto_is_configured = lambda: True
        try:
            with self.assertRaisesRegex(RuntimeError, "Recherche client Qonto invalide"):
                gestion_app._qonto_request("GET", "/v2/clients?queryfields=first_name", params={})
        finally:
            gestion_app._qonto_is_configured = original_configured

    def test_cpf_billing_line_uses_cpf_client_without_stagiaire_search(self):
        data = {"billing_lines": []}
        line = {
            "id": "line-cpf",
            "financingType": "CPF",
            "traineeFirstName": "Jean",
            "traineeLastName": "Dupont",
            "traineeEmail": "jean@example.com",
            "sessionId": "session-1",
            "amount": 1200,
            "vatRate": 20,
            "description": "Formation test",
            "dateStart": "2026-01-01",
            "dateEnd": "2026-01-02",
        }
        data["billing_lines"].append(line)
        calls = {"cpf_client": 0, "search": 0, "create_client": 0}
        originals = {
            "configured": gestion_app._qonto_is_configured,
            "iban": gestion_app.get_qonto_invoice_iban,
            "cpf_client": gestion_app.get_or_create_cpf_qonto_client,
            "search": gestion_app.search_qonto_client,
            "create_client": gestion_app.create_qonto_client,
            "invoice": gestion_app.create_qonto_invoice,
            "save": gestion_app.save_data,
        }
        gestion_app._qonto_is_configured = lambda: True
        gestion_app.get_qonto_invoice_iban = lambda: "FR7612345678901234567890185"
        def fake_cpf_client():
            calls["cpf_client"] += 1
            return {"id": "cpf-client"}
        gestion_app.get_or_create_cpf_qonto_client = fake_cpf_client
        gestion_app.search_qonto_client = lambda criteria: calls.__setitem__("search", calls["search"] + 1) or None
        gestion_app.create_qonto_client = lambda payload: calls.__setitem__("create_client", calls["create_client"] + 1) or {"client": {"id": "bad"}}
        gestion_app.create_qonto_invoice = lambda payload: {"client_invoice": {"id": "invoice-1", "number": "F-1", "status": "draft"}}
        gestion_app.save_data = lambda _data: None
        try:
            ok, result = gestion_app._create_invoice_for_billing_line(data, line)
        finally:
            gestion_app._qonto_is_configured = originals["configured"]
            gestion_app.get_qonto_invoice_iban = originals["iban"]
            gestion_app.get_or_create_cpf_qonto_client = originals["cpf_client"]
            gestion_app.search_qonto_client = originals["search"]
            gestion_app.create_qonto_client = originals["create_client"]
            gestion_app.create_qonto_invoice = originals["invoice"]
            gestion_app.save_data = originals["save"]

        self.assertTrue(ok, result)
        self.assertEqual(calls, {"cpf_client": 1, "search": 0, "create_client": 0})
        self.assertEqual(result["line"]["qontoClientId"], "cpf-client")
        self.assertEqual(result["line"]["qontoInvoiceId"], "invoice-1")


if __name__ == "__main__":
    unittest.main()
