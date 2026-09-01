import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app
from akto_bts import (
    AktoApiError,
    AktoBtsStore,
    AktoClient,
    AktoConfig,
    redact_sensitive_payload,
    sync_akto_bts,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttpSession:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return _FakeResponse(200, {"access_token": "bearer-test", "expires_in": 3600})

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return _FakeResponse(200, {
            "total": 1,
            "count": 1,
            "page": 1,
            "EtatDossierResult": [{"numeroInterne": "D-1", "etat": "ENGAGE"}],
        })


class _FakeAktoClient:
    def list_dossier_states(self):
        return [{
            "numeroInterne": "D-1",
            "numeroExterne": "2026-APP-01",
            "numeroDeca": "DECA-01",
            "etat": "ENGAGE",
        }]

    def get_dossier(self, internal_number):
        assert internal_number == "D-1"
        return {
            "engagement": 8200.50,
            "cerfa": {
                "numeroInterne": "D-1",
                "numeroExterne": "2026-APP-01",
                "etat": "ENGAGE",
                "apprenti": {
                    "prenom": "Alice",
                    "nom": "Martin",
                    "courriel": "alice@example.test",
                    "telephone": "0600000000",
                    "dateNaissance": "2002-04-03T00:00:00Z",
                    "nir": "2020403001001",
                },
                "employeur": {
                    "denomination": "Entreprise Test",
                    "siret": "12345678901234",
                    "courriel": "rh@example.test",
                },
                "formation": {
                    "intituleQualification": "BTS Management opérationnel de la sécurité",
                    "rncp": "RNCP12345",
                    "codeDiplome": "32031234",
                    "dateDebutFormation": "2026-09-01T00:00:00Z",
                    "dateFinFormation": "2028-06-30T00:00:00Z",
                    "dureeFormation": 1350,
                    "nombreHeuresEnDistanciel": 100,
                },
                "contrat": {
                    "noContrat": "CONTRAT-01",
                    "dateConclusion": "2026-08-20T00:00:00Z",
                    "dateDebutContrat": "2026-09-01T00:00:00Z",
                    "dateFinContrat": "2028-08-31T00:00:00Z",
                    "salaireEmbauche": 1250,
                },
            },
            "echeances": [{
                "numero": 1,
                "montantTotal": 4100.25,
                "montantRegle": 2000,
                "montantEnCoursInstruction": 500,
                "dateDebut": "2026-09-01",
                "dateFin": "2027-02-28",
            }],
            "detailsFacturation": {"IBAN": "FR761234567890", "fraisMobiliteRegles": False},
            "engagementsFraisAnnexe": [{"natureFrais": "RESTAURATION", "montantTotal": 300}],
        }

    def list_invoice_states(self):
        return [{
            "numeroInterneFacture": "F-1",
            "referenceFactureCFA": "FAC-2026-01",
            "montantFacture": 2100,
            "etatFacture": "REGLE",
            "referenceVirement": "VIR-01",
            "dateReglement": "2027-03-02",
            "organismeFormation": {"siret": "98765432100019", "IBAN": "FR769999999999"},
            "dossiers": [{
                "numeroInterneDossier": "D-1",
                "numeroExterneDossier": "2026-APP-01",
                "montant": 2100,
            }],
        }]


class AktoClientTests(unittest.TestCase):
    def test_oauth_and_required_headers_are_sent(self):
        fake_http = _FakeHttpSession()
        config = AktoConfig(
            api_base_url="https://api.akto.example/ApiEchangeCFA",
            oauth_token_url="https://login.akto.example/oauth2/token",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            api_key="cfa-api-key",
        )

        rows = AktoClient(config, http_session=fake_http).list_dossier_states()

        self.assertEqual(rows[0]["numeroInterne"], "D-1")
        self.assertEqual(len(fake_http.post_calls), 1)
        url, kwargs = fake_http.get_calls[0]
        self.assertEqual(url, "https://api.akto.example/ApiEchangeCFA/v2/dossiers/etats")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer bearer-test")
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "cfa-api-key")
        self.assertEqual(kwargs["headers"]["EDITEUR"], "Intégrale Academy")
        self.assertEqual(kwargs["headers"]["LOGICIEL"], "Gestion Stagiaires · Espace BTS")
        self.assertEqual(kwargs["headers"]["VERSION"], "1.0")

    def test_redaction_is_recursive(self):
        redacted = redact_sensitive_payload({
            "apprenti": {"nir": "SECRET-NIR", "nom": "Martin"},
            "organisme": {"IBAN": "SECRET-IBAN"},
            "client_secret": "SECRET-OAUTH",
        })

        serialized = json.dumps(redacted)
        self.assertNotIn("SECRET-NIR", serialized)
        self.assertNotIn("SECRET-IBAN", serialized)
        self.assertNotIn("SECRET-OAUTH", serialized)
        self.assertEqual(redacted["apprenti"]["nom"], "Martin")


class AktoBtsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "akto_bts.sqlite3")
        self.store = AktoBtsStore(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_complete_sync_builds_independent_dashboard_and_safe_export(self):
        self.store.start_run("run-1", started_at="2026-09-01T10:00:00Z")

        result = sync_akto_bts(self.store, _FakeAktoClient(), "run-1")
        dashboard = self.store.dashboard()
        exported = self.store.export_snapshot()

        self.assertEqual(result["status"], "success")
        self.assertEqual(dashboard["stats"]["contracts_total"], 1)
        self.assertEqual(dashboard["stats"]["invoices_total"], 1)
        self.assertEqual(dashboard["stats"]["invoices_paid_count"], 1)
        self.assertAlmostEqual(dashboard["stats"]["engagement_total"], 8200.50)
        contract = dashboard["contracts"][0]
        self.assertEqual(contract["apprentice_first_name"], "Alice")
        self.assertEqual(contract["employer_name"], "Entreprise Test")
        self.assertEqual(contract["state_label"], "Engagé")
        self.assertEqual(contract["invoices"][0]["allocated_amount"], 2100)

        serialized_export = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("2020403001001", serialized_export)
        self.assertNotIn("FR761234567890", serialized_export)
        self.assertNotIn("FR769999999999", serialized_export)
        self.assertIn("[MASQUÉ]", serialized_export)

        with sqlite3.connect(self.db_path) as connection:
            stored_payloads = " ".join(
                row[0] for row in connection.execute(
                    "SELECT payload_json FROM contracts UNION ALL SELECT payload_json FROM invoices"
                )
            )
        self.assertNotIn("2020403001001", stored_payloads)
        self.assertNotIn("FR769999999999", stored_payloads)

    def test_api_failure_before_snapshot_keeps_existing_cache(self):
        self.store.start_run("run-1")
        sync_akto_bts(self.store, _FakeAktoClient(), "run-1")
        self.store.start_run("run-2")

        class FailingClient:
            def list_dossier_states(self):
                raise AktoApiError("AKTO indisponible", status_code=503)

        with self.assertRaises(AktoApiError):
            sync_akto_bts(self.store, FailingClient(), "run-2")

        self.assertEqual(self.store.dashboard()["stats"]["contracts_total"], 1)


class AdminBtsRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "akto_bts.sqlite3")
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _patches(self):
        return (
            patch.object(gestion_app, "AKTO_BTS_DB_FILE", self.db_path),
            patch.object(gestion_app, "AKTO_BTS_SYNC_LOCK_FILE", os.path.join(self.temp_dir.name, "akto.lock")),
            patch.object(gestion_app, "load_data", side_effect=AssertionError("BTS must not read data.json")),
        )

    def test_exact_admin_bts_route_renders_without_contacting_akto(self):
        db_patch, lock_patch, data_patch = self._patches()
        env = {name: "" for name in (
            "AKTO_API_BASE_URL", "AKTO_OAUTH_TOKEN_URL", "AKTO_OAUTH_CLIENT_ID",
            "AKTO_OAUTH_CLIENT_SECRET", "AKTO_API_KEY",
        )}
        with db_patch, lock_patch, data_patch, patch.dict(os.environ, env), patch.object(
            gestion_app, "AktoClient", side_effect=AssertionError("GET must not contact AKTO")
        ):
            response = self.client.get("/admin/BTS")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Contrats d’apprentissage AKTO", html)
        self.assertIn("Base BTS séparée", html)
        self.assertIn("AKTO_OAUTH_CLIENT_ID", html)
        self.assertIn("Aucun contrat AKTO dans le cache BTS", html)

    def test_partner_account_cannot_open_independent_bts_area(self):
        with self.client.session_transaction() as flask_session:
            flask_session["admin_role"] = "partner_admin"
            flask_session["partner_id"] = "partner-test-123"
        db_patch, lock_patch, data_patch = self._patches()
        with db_patch, lock_patch, data_patch:
            response = self.client.get("/admin/BTS")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin/sessions"))

    def test_dashboard_renders_cached_contract_details(self):
        db_patch, lock_patch, data_patch = self._patches()
        with db_patch, lock_patch, data_patch:
            store = AktoBtsStore(self.db_path)
            store.start_run("route-run")
            sync_akto_bts(store, _FakeAktoClient(), "route-run")
            response = self.client.get("/admin/BTS")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Alice Martin", html)
        self.assertIn("Entreprise Test", html)
        self.assertIn("BTS Management opérationnel de la sécurité", html)
        self.assertIn("8 200,50 €", html)
        self.assertIn("FAC-2026-01", html)

    def test_sync_is_not_started_when_oauth_configuration_is_missing(self):
        db_patch, lock_patch, data_patch = self._patches()
        env = {name: "" for name in (
            "AKTO_API_BASE_URL", "AKTO_OAUTH_TOKEN_URL", "AKTO_OAUTH_CLIENT_ID",
            "AKTO_OAUTH_CLIENT_SECRET", "AKTO_API_KEY",
        )}
        with db_patch, lock_patch, data_patch, patch.dict(os.environ, env), patch.object(
            gestion_app.threading, "Thread", side_effect=AssertionError("worker must not start")
        ):
            response = self.client.post("/admin/BTS/akto/sync", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Connexion AKTO incomplète", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
