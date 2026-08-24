import os
import unittest
from unittest.mock import Mock, patch

import requests

import app as gestion_app
from wedof_service import (
    WedofApiError,
    WedofClient,
    WedofConfigurationError,
)


def response(status=200, payload=None, json_error=None):
    result = Mock(status_code=status)
    if json_error:
        result.json.side_effect = json_error
    else:
        result.json.return_value = payload
    return result


class WedofClientTests(unittest.TestCase):
    def test_missing_and_empty_key_are_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(WedofConfigurationError, "WEDOF_API_KEY"):
                WedofClient()
        for value in ("", "   "):
            with patch.dict(os.environ, {"WEDOF_API_KEY": value}, clear=True):
                with self.assertRaises(WedofConfigurationError):
                    WedofClient()

    def test_headers_urls_and_two_gets_only(self):
        session = Mock()
        session.get.side_effect = [
            response(payload={"name": "Organisme Test", "siret": "12345678901234"}),
            response(payload={"items": [{"trainee": {"email": "secret@example.test"}}]}),
        ]
        with patch.dict(os.environ, {"WEDOF_API_KEY": "  cle-secrete  "}, clear=True):
            result = WedofClient(session=session).test_connection()

        self.assertEqual(session.get.call_count, 2)
        first, second = session.get.call_args_list
        self.assertEqual(first.args[0], "https://www.wedof.fr/api/organisms/me")
        self.assertEqual(second.args[0], "https://www.wedof.fr/api/registrationFolders")
        self.assertEqual(second.kwargs["params"], {"limit": 1, "page": 1})
        for call in (first, second):
            self.assertEqual(call.kwargs["headers"]["X-Api-Key"], "cle-secrete")
            self.assertEqual(
                call.kwargs["headers"]["User-Agent"],
                "IntegraleAcademy-GestionStagiaires/2026.08",
            )
            self.assertEqual(
                call.kwargs["headers"]["X-Integrale-Application"],
                "gestionstagiaires",
            )
            self.assertNotIn("Authorization", call.kwargs["headers"])
            self.assertEqual(call.kwargs["timeout"], (5, 45))
        self.assertEqual(result["registration_folders_sample_count"], 1)
        self.assertNotIn("trainee", str(result).lower())
        self.assertNotIn("secret@example.test", str(result))
        for method in ("post", "put", "patch", "delete"):
            getattr(session, method).assert_not_called()

    def test_supported_registration_folder_shapes(self):
        shapes = [[], {"items": []}, {"member": [1]}, {"hydra:member": [1]}, {"registrationFolders": [1]}]
        for payload in shapes:
            session = Mock()
            session.get.return_value = response(payload=payload)
            check = WedofClient(api_key="key", session=session).check_registration_folders_access()
            self.assertTrue(check["accessible"])
            self.assertLessEqual(check["result_count"], 1)

    def test_status_errors_are_sanitized(self):
        expectations = {
            401: "invalide ou refusée",
            403: "dossiers WEDOF",
            404: "introuvable",
            429: "trop de demandes",
            503: "temporairement indisponible",
        }
        for status, message in expectations.items():
            session = Mock()
            session.get.return_value = response(status=status, payload={"key": "cle-super-secrete"})
            with self.assertRaisesRegex(WedofApiError, message) as raised:
                WedofClient(api_key="cle-super-secrete", session=session).check_registration_folders_access()
            self.assertNotIn("cle-super-secrete", str(raised.exception))

    def test_timeout_connection_non_json_and_unexpected_json(self):
        errors = [
            (requests.Timeout("cle-super-secrete"), "délai"),
            (requests.ConnectionError("cle-super-secrete"), "connecter"),
        ]
        for error, message in errors:
            session = Mock()
            session.get.side_effect = error
            with self.assertRaisesRegex(WedofApiError, message) as raised:
                WedofClient(api_key="cle-super-secrete", session=session).get_current_organism()
            self.assertNotIn("cle-super-secrete", str(raised.exception))

        session = Mock()
        session.get.return_value = response(json_error=ValueError("raw private response"))
        with self.assertRaisesRegex(WedofApiError, "non JSON"):
            WedofClient(api_key="key", session=session).get_current_organism()
        session.get.return_value = response(payload=[{"private": "data"}])
        with self.assertRaisesRegex(WedofApiError, "inattendue"):
            WedofClient(api_key="key", session=session).get_current_organism()

    def test_boolean_flags_are_fail_closed_and_dry_run_defaults_on(self):
        session = Mock()
        session.get.side_effect = [
            response(payload={"name": "Test", "siret": "1"}), response(payload=[]),
        ]
        with patch.dict(os.environ, {"WEDOF_AUTOMATION_ENABLED": "false", "WEDOF_DRY_RUN": "true"}, clear=True):
            result = WedofClient(api_key="key", session=session).test_connection()
        self.assertFalse(result["automation_enabled"])
        self.assertTrue(result["dry_run"])

        session.get.side_effect = [
            response(payload={"name": "Test", "siret": "1"}), response(payload=[]),
        ]
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(WedofClient(api_key="key", session=session).test_connection()["dry_run"])

    @patch("wedof_service.time.sleep")
    def test_temporary_failures_are_retried(self, sleep):
        for failure in (requests.Timeout(), requests.ConnectionError(), response(502), response(503)):
            session = Mock()
            session.get.side_effect = [failure, response(payload={"name": "Test", "siret": "1"})]
            self.assertEqual(WedofClient(api_key="key", session=session).get_current_organism()["name"], "Test")
            self.assertEqual(session.get.call_count, 2)

    @patch("wedof_service.reserve_request")
    @patch("wedof_service.time.sleep")
    def test_each_http_attempt_is_counted_before_retry(self, sleep, reserve):
        session = Mock()
        session.get.side_effect = [
            requests.Timeout(),
            response(payload={"name": "Test", "siret": "1"}),
        ]
        client = WedofClient(
            api_key="key", session=session, origin="gestionstagiaires-webhook",
        )
        self.assertEqual(client.get_current_organism()["name"], "Test")
        self.assertEqual(reserve.call_count, 2)
        self.assertTrue(all(
            call.kwargs["origin"] == "gestionstagiaires-webhook"
            for call in reserve.call_args_list
        ))
        self.assertEqual(
            session.get.call_args.kwargs["headers"]["X-Integrale-Application"],
            "gestionstagiaires-webhook",
        )

    @patch("wedof_service.reserve_request")
    def test_interactive_read_can_identify_a_manual_cpf_refresh(self, reserve):
        session = Mock()
        session.get.return_value = response(payload={"externalId": "W1"})

        folder = WedofClient(api_key="key", session=session).get_registration_folder_interactive(
            "W1", operation="cpf_invoice_manual_refresh",
        )

        self.assertEqual(folder["externalId"], "W1")
        reserve.assert_called_once_with(
            origin="gestionstagiaires",
            operation="cpf_invoice_manual_refresh",
            method="GET",
            path="/registrationFolders/:id",
        )

    @patch("wedof_service.time.sleep")
    def test_retry_after_and_non_retryable_statuses(self, sleep):
        limited = response(429)
        limited.headers = {"Retry-After": "30"}
        session = Mock()
        session.get.side_effect = [limited, response(payload={"name": "Test", "siret": "1"})]
        WedofClient(api_key="key", session=session).get_current_organism()
        sleep.assert_called_once_with(15)
        for status in (401, 403, 404):
            session = Mock(); session.get.return_value = response(status)
            with self.assertRaises(WedofApiError):
                WedofClient(api_key="key", session=session).check_registration_folders_access()
            self.assertEqual(session.get.call_count, 1)

    @patch("wedof_service.time.sleep")
    def test_exhausted_timeout_is_structured(self, sleep):
        session = Mock(); session.get.side_effect = requests.Timeout("private")
        with self.assertRaises(WedofApiError) as raised:
            WedofClient(api_key="key", session=session).get_current_organism()
        self.assertEqual((raised.exception.code, raised.exception.retryable), ("wedof_timeout", True))
        self.assertEqual(session.get.call_count, 3)

    def test_numeric_configuration_is_bounded_and_page_default_is_50(self):
        session = Mock(); page = response(payload=[]); page.headers = {}
        session.get.return_value = page
        with patch.dict(os.environ, {"WEDOF_CONNECT_TIMEOUT_SECONDS": "8", "WEDOF_READ_TIMEOUT_SECONDS": "60",
                                    "WEDOF_GET_MAX_ATTEMPTS": "4", "WEDOF_PAGE_LIMIT": "75"}, clear=False):
            configured = WedofClient(api_key="key", session=session)
            self.assertEqual(configured._timeout, (8.0, 60.0))
        with patch.dict(os.environ, {"WEDOF_CONNECT_TIMEOUT_SECONDS": "bad", "WEDOF_READ_TIMEOUT_SECONDS": "999",
                                    "WEDOF_GET_MAX_ATTEMPTS": "0", "WEDOF_PAGE_LIMIT": "bad"}, clear=False):
            client = WedofClient(api_key="key", session=session)
            self.assertEqual(client._timeout, (5, 45))
            client.list_registration_folders("accepted")
            self.assertEqual(session.get.call_args.kwargs["params"]["limit"], 50)


class WedofAdminRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()

    def test_route_requires_admin_authentication(self):
        with patch.object(gestion_app, "WedofClient") as client:
            result = self.client.post("/admin/wedof/api/test")
        self.assertIn(result.status_code, (302, 303))
        client.assert_not_called()

    def test_route_flashes_only_clean_summary(self):
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
        clean = {
            "ok": True,
            "organism": {"name": "Centre Test", "siret": "123"},
            "registration_folders_access": True,
            "registration_folders_sample_count": 1,
            "automation_enabled": False,
            "dry_run": True,
        }
        instance = Mock()
        instance.test_connection.return_value = clean
        with patch.object(gestion_app, "WedofClient", return_value=instance):
            result = self.client.post("/admin/wedof/api/test", follow_redirects=True)
        html = result.get_data(as_text=True)
        self.assertIn("Connexion WEDOF réussie", html)
        self.assertIn("Centre Test", html)
        self.assertNotIn("registration_folders_sample_count", html)


if __name__ == "__main__":
    unittest.main()
