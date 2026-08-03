import json
import os
import tempfile
import unittest
from unittest import mock

import app as gestion_app


class CrmIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_file = gestion_app.DATA_FILE
        self.original_backup_dir = gestion_app.BACKUP_DIR
        gestion_app.DATA_FILE = os.path.join(self.temp_dir.name, "data.json")
        gestion_app.BACKUP_DIR = os.path.join(self.temp_dir.name, "backups")
        os.makedirs(gestion_app.BACKUP_DIR)
        self.payload = {
            "source": "integrale-connect-crm", "crm_contact_id": "contact-42",
            "prenom": "Lina", "nom": "Martin", "email": "lina@example.com",
            "telephone": "0600000000", "formation": "APS", "parcours": "",
            "centre": "Paris", "session": "Du 1 au 5 septembre 2026", "commentaires": "CRM",
        }
        data = gestion_app._empty_data_payload()
        data["sessions"] = [{
            "id": "session-1", "name": self.payload["session"], "training_type": "APS",
            "crm_center": "Paris", "partner_id": gestion_app.INTEGRALE_PARTNER_ID, "trainees": [],
        }]
        with open(gestion_app.DATA_FILE, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.client = gestion_app.app.test_client()
        self.env = mock.patch.dict(os.environ, {"CRM_INTEGRATION_API_TOKEN": "secret-token"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        gestion_app.DATA_FILE = self.original_data_file
        gestion_app.BACKUP_DIR = self.original_backup_dir
        self.temp_dir.cleanup()

    def post(self, payload=None, key="crm-contact-contact-42", token="secret-token"):
        headers = {"Idempotency-Key": key}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return self.client.post("/api/integrations/crm/stagiaires", json=payload or self.payload, headers=headers)

    def persisted(self):
        with open(gestion_app.DATA_FILE, encoding="utf-8") as handle:
            return json.load(handle)

    def test_missing_or_invalid_token_is_rejected(self):
        self.assertEqual(self.post(token=None).status_code, 401)
        response = self.post(token="wrong")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentification invalide"})

    def test_creates_complete_trainee_and_registration(self):
        response = self.post()
        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(set(body), {"id", "url"})
        self.assertEqual(body["url"], f"https://gestionstagiaires-r5no.onrender.com/stagiaires/{body['id']}")
        saved = self.persisted()
        trainee = saved["sessions"][0]["trainees"][0]
        self.assertEqual((trainee["first_name"], trainee["last_name"]), ("Lina", "MARTIN"))
        self.assertEqual(trainee["crm_contact_id"], "contact-42")
        self.assertEqual(saved["crm_integration_requests"][0]["trainee_id"], body["id"])

    def test_required_data_and_idempotency_key_are_mandatory(self):
        invalid = dict(self.payload, email=" ")
        self.assertEqual(self.post(invalid).status_code, 400)
        response = self.client.post(
            "/api/integrations/crm/stagiaires", json=self.payload,
            headers={"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_session_returns_422(self):
        response = self.post(dict(self.payload, session="Session inexistante"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.persisted()["sessions"][0]["trainees"], [])

    def test_same_request_is_idempotent(self):
        first = self.post()
        second = self.post()
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.get_json(), second.get_json())
        self.assertEqual(len(self.persisted()["sessions"][0]["trainees"]), 1)

    def test_same_key_with_different_data_returns_409(self):
        self.assertEqual(self.post().status_code, 201)
        response = self.post(dict(self.payload, commentaires="différent"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {"error": "Clé d’idempotence déjà utilisée avec des données différentes"})

    def test_registration_failure_leaves_no_partial_person(self):
        with mock.patch.object(gestion_app, "_new_crm_trainee", side_effect=RuntimeError("failure")):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "Impossible de créer l’inscription"})
        saved = self.persisted()
        self.assertEqual(saved["sessions"][0]["trainees"], [])
        self.assertEqual(saved.get("crm_integration_requests", []), [])


if __name__ == "__main__":
    unittest.main()
