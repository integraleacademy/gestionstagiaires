import logging
import os
import unittest
from unittest.mock import Mock, patch

import app as gestion_app
from wedof_matching import (
    build_matching_preview, extract_folder, match_folder, normalize_email, normalize_name,
    normalize_phone,
)
from wedof_service import WedofClient


def api_response(items, headers=None):
    response = Mock(status_code=200)
    response.json.return_value = items
    response.headers = headers or {}
    return response


def folder(**changes):
    value = {
        "externalId": "W-123", "state": "accepted", "type": " CPF ",
        "attendee": {"firstName": "Élodie", "lastName": "D'Arc", "email": "E@EXAMPLE.FR", "phoneNumber": "+33 6 12 34 56 78"},
        "trainingActionInfo": {"startDate": "2026-09-01", "endDate": "2026-09-02", "title": "APS"},
    }
    value.update(changes)
    return value


def session(trainees=None, **changes):
    value = {"id": "S1", "name": "APS septembre", "date_start": "2026-09-01", "date_end": "2026-09-02", "trainees": trainees or []}
    value.update(changes)
    return value


def trainee(**changes):
    value = {"id": "T1", "first_name": "Elodie", "last_name": "D-Arc", "email": " e@example.fr ", "phone": "06.12.34.56.78"}
    value.update(changes)
    return value


class WedofReadOnlyClientTests(unittest.TestCase):
    def test_states_headers_get_only_and_no_authorization(self):
        http = Mock()
        http.get.side_effect = [api_response([folder()]), api_response([folder(state="inTraining")])]
        client = WedofClient(api_key="secret-test-key", session=http)
        self.assertEqual(len(client.list_registration_folders("accepted")), 1)
        self.assertEqual(len(client.list_registration_folders("inTraining")), 1)
        self.assertEqual([call.kwargs["params"]["state"] for call in http.get.call_args_list], ["accepted", "inTraining"])
        for call in http.get.call_args_list:
            self.assertEqual(call.kwargs["headers"], {"Accept": "application/json", "X-Api-Key": "secret-test-key"})
        for method in ("post", "put", "patch", "delete"):
            getattr(http, method).assert_not_called()

    @patch("wedof_service.time.sleep")
    def test_header_pagination_and_fallback_pagination(self, _sleep):
        http = Mock()
        http.get.side_effect = [
            api_response([folder()] * 100, {"x-current-page": "1", "x-item-per-page": "100", "x-total-count": "101"}),
            api_response([folder()]),
        ]
        self.assertEqual(len(WedofClient(api_key="key", session=http).list_registration_folders("accepted")), 101)
        self.assertEqual(http.get.call_args_list[1].kwargs["params"]["page"], 2)

        http = Mock()
        http.get.side_effect = [api_response([folder()] * 2), api_response([folder()])]
        self.assertEqual(len(WedofClient(api_key="key", session=http).list_registration_folders("accepted", limit=2)), 3)


class MatchingTests(unittest.TestCase):
    def test_normalizations(self):
        self.assertEqual(normalize_email(" TEST@Example.FR "), "test@example.fr")
        self.assertEqual(normalize_phone("+33 (0)6 12-34.56.78"), "0612345678")
        self.assertEqual(normalize_phone("+33 6 12-34.56.78"), "0612345678")
        self.assertEqual(normalize_phone("0033 6 12 34 56 78"), "0612345678")
        self.assertEqual(normalize_name("Élise D’Arc-Martin"), normalize_name("elise d arc martin"))

    def test_external_id_identity_and_dates_are_required(self):
        for changed in ({"externalId": ""}, {"attendee": {}}, {"trainingActionInfo": {"startDate": "bad", "endDate": "2026-09-02"}}):
            self.assertEqual(match_folder(folder(**changed), [session([trainee()])])["status"], "missing_wedof_data")
        # Aucun identifiant générique ne remplace externalId.
        self.assertEqual(match_folder(folder(externalId="", id="fallback"), [session([trainee()])])["status"], "missing_wedof_data")

    def test_non_cpf_is_excluded(self):
        self.assertEqual(match_folder(folder(type="contract"), [session([trainee()])])["status"], "excluded_non_cpf")
        self.assertEqual(match_folder(folder(type=None), [session([trainee()])])["status"], "excluded_non_cpf")

    def test_both_session_dates_are_exact_and_archived_excluded(self):
        self.assertEqual(match_folder(folder(), [session([trainee()], date_end="2026-09-03")])["status"], "no_session_match")
        self.assertEqual(match_folder(folder(), [session([trainee()], date_start="2026-08-31")])["status"], "no_session_match")
        self.assertEqual(match_folder(folder(), [session([trainee()], archived=True)])["status"], "no_session_match")
        legacy = session([trainee()]); legacy.pop("date_start"); legacy.pop("date_end"); legacy.update(date_debut="2026-09-01", date_fin="2026-09-02")
        self.assertEqual(match_folder(folder(), [legacy])["status"], "exact_match")

    def test_three_strong_rules(self):
        email_only = trainee(phone="", email="e@example.fr")
        self.assertEqual(match_folder(folder(), [session([email_only])])["rule"], "email_identity_dates")
        phone_only = trainee(email="", phone="0612345678")
        self.assertEqual(match_folder(folder(), [session([phone_only])])["rule"], "phone_identity_dates")
        contacts = trainee(first_name="Elo", last_name="Arc", email="e@example.fr", phone="0612345678")
        self.assertEqual(match_folder(folder(), [session([contacts])])["rule"], "email_phone_dates")

    def test_name_only_never_matches_and_duplicate_is_ambiguous(self):
        name_only = trainee(email="other@example.fr", phone="0700000000")
        self.assertEqual(match_folder(folder(), [session([name_only])])["status"], "no_trainee_match")
        self.assertEqual(match_folder(folder(), [session([trainee(id="T1"), trainee(id="T2")])])["status"], "ambiguous_match")

    def test_preview_counts_and_whitelisted_output(self):
        preview = build_matching_preview([folder(rawSecret={"apiKey": "NEVER"}), folder(type="other")], {"sessions": [session([trainee()])]})
        self.assertEqual(preview["counts"]["cpf_analyzed"], 1)
        self.assertEqual(preview["counts"]["exact_match"], 1)
        self.assertNotIn("rawSecret", str(preview))

    def test_invoice_reference_is_whitelisted_from_wedof_folder(self):
        extracted = extract_folder(folder(invoice={
            "qontoInvoiceId": "inv-cpf-1",
            "number": "F-CPF-1",
            "status": "paid",
            "paidAt": "2026-10-02T14:00:00Z",
            "privatePayload": "never",
        }))

        self.assertEqual(extracted["qonto_invoice_id"], "inv-cpf-1")
        self.assertEqual(extracted["qonto_invoice_number"], "F-CPF-1")
        self.assertEqual(extracted["invoice_status"], "paid")
        self.assertEqual(extracted["invoice_paid_at"], "2026-10-02T14:00:00Z")
        self.assertNotIn("privatePayload", extracted)

    def test_wedof_billing_state_and_top_level_invoice_number_are_whitelisted(self):
        extracted = extract_folder(folder(
            state="serviceDoneValidated",
            billingState="billed",
            invoiceNumber="FL-2026-374",
        ))

        self.assertEqual(extracted["state"], "serviceDoneValidated")
        self.assertEqual(extracted["billing_state"], "billed")
        self.assertEqual(extracted["invoice_number"], "FL-2026-374")
        self.assertEqual(extracted["qonto_invoice_number"], "FL-2026-374")

    def test_official_wedof_bill_number_is_whitelisted_for_qonto_lookup(self):
        extracted = extract_folder(folder(
            state="serviceDoneValidated",
            billingState="billed",
            billNumber="FL-2026-374",
        ))

        self.assertEqual(extracted["billing_state"], "billed")
        self.assertEqual(extracted["invoice_number"], "FL-2026-374")
        self.assertEqual(extracted["qonto_invoice_number"], "FL-2026-374")


class PreviewRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()

    def test_admin_authentication_is_required(self):
        with patch.object(gestion_app, "WedofClient") as client:
            response = self.client.post("/admin/wedof/matching/preview")
        self.assertIn(response.status_code, (302, 303))
        client.assert_not_called()

    def test_route_is_read_only_and_does_not_pass_raw_folder(self):
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
        client = Mock()
        client.list_registration_folders.side_effect = [[folder(privateFinancial="NEVER_RENDER")], []]
        fake_data = {"sessions": [session([trainee()])]}
        with patch.object(gestion_app, "WedofClient", return_value=client), \
             patch.object(gestion_app, "load_data", return_value=fake_data), \
             patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
             patch.object(gestion_app, "save_data") as save_data, \
             patch.object(gestion_app, "_save_wedof_webhooks") as save_webhooks:
            response = self.client.post("/admin/wedof/matching/preview")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.list_registration_folders.call_args_list[0].args, ("accepted",))
        self.assertEqual(client.list_registration_folders.call_args_list[1].args, ("inTraining",))
        save_data.assert_not_called(); save_webhooks.assert_not_called()
        self.assertNotIn("NEVER_RENDER", html)
        self.assertIn("Correspondance fiable", html)

    def test_api_key_is_absent_from_logs_and_messages(self):
        http = Mock(); http.get.return_value = api_response([])
        with self.assertLogs("wedof_service", logging.INFO) as captured:
            WedofClient(api_key="ultra-secret-value", session=http).list_registration_folders("accepted")
        self.assertNotIn("ultra-secret-value", " ".join(captured.output))


if __name__ == "__main__":
    unittest.main()
