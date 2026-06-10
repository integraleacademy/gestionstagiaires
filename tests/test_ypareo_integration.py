import os
import unittest
from unittest.mock import patch

import app as gestion_app


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.ok = 200 <= status_code < 400

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class YpareoPayloadTests(unittest.TestCase):
    def test_nettoyer_payload_removes_empty_nested_values_but_keeps_false_and_zero(self):
        payload = {
            "empty": "   ",
            "none": None,
            "false": False,
            "zero": 0,
            "object": {"empty": "", "value": " ok "},
            "list": [None, "", {}, [], "value"],
        }

        self.assertEqual(
            gestion_app.nettoyer_payload(payload),
            {
                "false": False,
                "zero": 0,
                "object": {"value": "ok"},
                "list": ["value"],
            },
        )

    def test_construire_payload_uses_only_existing_platform_fields(self):
        trainee = {
            "last_name": " MARTIN ",
            "first_name": " Alice ",
            "email": " alice@example.test ",
            "phone": " 0612345678 ",
            "address": " 10 rue des Lilas ",
            "zip_code": " 75001 ",
            "city": " Paris ",
            "birth_date": "1990-02-03",
            "birth_city": "Lyon",
            "birth_department": "69",
            "numero_ine": "INE-123",
            "is_rqth": False,
            "id_nationalite": None,
        }

        self.assertEqual(
            gestion_app.construire_payload_apprenant(trainee),
            {
                "adresse": {
                    "ligne1": "10 rue des Lilas",
                    "codePostal": "75001",
                    "ville": "Paris",
                    "paysAlpha": "FR",
                },
                "dateNaissance": "1990-02-03",
                "emails": [{"adresse": "alice@example.test", "isDefault": True}],
                "nom": "MARTIN",
                "nomNaissance": "MARTIN",
                "prenom": "Alice",
                "telephones": [{
                    "indicatif": "+33",
                    "isDefaultAppel": True,
                    "isDefaultSms": True,
                    "numero": "0612345678",
                }],
                "villeNaissance": "Lyon",
                "departementNaissance": "69",
                "numeroINE": "INE-123",
                "isRqth": False,
            },
        )

    def test_construire_payload_omits_empty_contact_containers_and_fixed_values(self):
        payload = gestion_app.construire_payload_apprenant({"last_name": "DUPONT", "first_name": "Léa"})

        self.assertEqual(payload, {"nom": "DUPONT", "nomNaissance": "DUPONT", "prenom": "Léa"})
        self.assertNotIn("adresse", payload)
        self.assertNotIn("emails", payload)
        self.assertNotIn("telephones", payload)


class YpareoRequestTests(unittest.TestCase):
    def test_creer_apprenant_posts_with_environment_configuration_and_saves_id(self):
        trainee = {"id": "T1", "last_name": "MARTIN", "first_name": "Alice"}
        response = FakeResponse(payload={"data": {"id": "YP-42"}})

        with patch.dict(
            os.environ,
            {"YPAREO_API_TOKEN": "secret-token", "YPAREO_API_URL": "https://ypareo.example/"},
            clear=False,
        ), patch.object(gestion_app.requests, "post", return_value=response) as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertTrue(result)
        self.assertEqual(trainee["ypareo_statut"], "Créé")
        self.assertEqual(trainee["ypareo_id"], "YP-42")
        self.assertEqual(trainee["ypareo_erreur"], "")
        post.assert_called_once_with(
            "https://ypareo.example/personne",
            headers={
                "Authorization": "Bearer secret-token",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"nom": "MARTIN", "nomNaissance": "MARTIN", "prenom": "Alice"},
            timeout=gestion_app.YPAREO_REQUEST_TIMEOUT_SECONDS,
        )

    def test_creer_apprenant_records_api_error_without_deleting_local_data(self):
        trainee = {"id": "T1", "last_name": "MARTIN", "first_name": "Alice"}
        response = FakeResponse(status_code=422, payload={"message": "Données invalides"})

        with patch.dict(os.environ, {"YPAREO_API_TOKEN": "secret-token"}, clear=False), patch.object(
            gestion_app.requests, "post", return_value=response
        ):
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(trainee["last_name"], "MARTIN")
        self.assertEqual(trainee["ypareo_statut"], "Erreur")
        self.assertEqual(trainee["ypareo_erreur"], "Données invalides")

    def test_missing_token_is_recorded_without_http_request(self):
        trainee = {"id": "T1", "last_name": "MARTIN"}

        with patch.dict(os.environ, {}, clear=True), patch.object(gestion_app.requests, "post") as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(trainee["ypareo_statut"], "Erreur")
        self.assertIn("YPAREO_API_TOKEN", trainee["ypareo_erreur"])
        post.assert_not_called()


class YpareoAdminIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
        self.data = {
            "sessions": [{
                "id": "S1",
                "name": "Session test",
                "training_type": "APS",
                "date_start": "2026-07-01",
                "date_end": "2026-07-05",
                "trainees": [{
                    "id": "T1",
                    "last_name": "MARTIN",
                    "first_name": "Alice",
                    "email": "alice@example.test",
                    "phone": "0612345678",
                    "ypareo_statut": "Erreur",
                    "ypareo_erreur": "Erreur API",
                    "documents": [],
                }],
            }]
        }

    def test_admin_table_displays_status_and_manual_send_button(self):
        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ):
            response = self.client.get("/admin/sessions/S1/trainees")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th class="col-ypareo">YPAREO</th>', html)
        self.assertIn("Erreur", html)
        self.assertIn("Envoyer vers YPAREO", html)
        self.assertIn('/admin/sessions/S1/trainees/T1/ypareo', html)

    def test_manual_send_updates_and_persists_trainee(self):
        def fake_send(trainee):
            trainee["ypareo_statut"] = "Créé"
            trainee["ypareo_id"] = "YP-99"
            trainee["ypareo_erreur"] = ""
            return True

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ) as save, patch.object(gestion_app, "creer_apprenant_ypareo", side_effect=fake_send):
            response = self.client.post("/admin/sessions/S1/trainees/T1/ypareo")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.data["sessions"][0]["trainees"][0]["ypareo_id"], "YP-99")
        save.assert_called_once_with(self.data)

    def test_new_local_trainee_is_kept_when_automatic_ypareo_send_fails(self):
        def fake_failure(trainee):
            trainee["ypareo_statut"] = "Erreur"
            trainee["ypareo_erreur"] = "YPAREO indisponible"
            return False

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ) as save, patch.object(gestion_app, "creer_apprenant_ypareo", side_effect=fake_failure) as send:
            response = self.client.post(
                "/api/sessions/S1/trainees/create",
                json={"last_name": "DURAND", "first_name": "Bob", "send_access": False},
            )

        self.assertEqual(response.status_code, 200)
        created = self.data["sessions"][0]["trainees"][0]
        self.assertEqual(created["last_name"], "DURAND")
        self.assertEqual(created["ypareo_statut"], "Erreur")
        self.assertEqual(created["ypareo_erreur"], "YPAREO indisponible")
        send.assert_called_once_with(created)
        self.assertGreaterEqual(save.call_count, 2)


if __name__ == "__main__":
    unittest.main()
