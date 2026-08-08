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
            self.assertNotIn("Authorization", call.kwargs["headers"])
            self.assertEqual(call.kwargs["timeout"], (5, 20))
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
