import os
import unittest
from unittest.mock import patch

import app as gestion_app


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
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
                    "numero": "612345678",
                }],
                "villeNaissance": "Lyon",
                "departementNaissance": "69",
                "numeroINE": "INE-123",
                "isRqth": False,
            },
        )

    def test_construire_payload_normalizes_french_phone_for_ypareo(self):
        phone_numbers = [
            "+33749424742",
            "0033749424742",
            "0749424742",
            "07 49 42 47 42",
            "07.49.42.47.42",
            "07-49-42-47-42",
            "(+33) 7 49 42 47 42",
            "+33 (0)7 49 42 47 42",
        ]

        for phone_number in phone_numbers:
            with self.subTest(phone_number=phone_number):
                payload = gestion_app.construire_payload_apprenant({"phone": phone_number})

                self.assertEqual(
                    payload["telephones"],
                    [{
                        "indicatif": "+33",
                        "isDefaultAppel": True,
                        "isDefaultSms": True,
                        "numero": "749424742",
                    }],
                )

    def test_construire_payload_omits_empty_contact_containers_and_fixed_values(self):
        payload = gestion_app.construire_payload_apprenant({"last_name": "DUPONT", "first_name": "Léa"})

        self.assertEqual(payload, {"nom": "DUPONT", "nomNaissance": "DUPONT", "prenom": "Léa"})
        self.assertNotIn("adresse", payload)
        self.assertNotIn("emails", payload)
        self.assertNotIn("telephones", payload)


class YpareoRequestTests(unittest.TestCase):
    def setUp(self):
        gestion_app._clear_ypareo_access_token_cache()

    def tearDown(self):
        gestion_app._clear_ypareo_access_token_cache()

    def test_authenticate_posts_initial_token_and_accepts_supported_response_formats(self):
        response_payloads = [
            {"token": "access-token"},
            {"access_token": "access-token"},
            {"data": {"token": "access-token"}},
            {"data": {"access_token": "access-token"}},
        ]

        for response_payload in response_payloads:
            with self.subTest(response_payload=response_payload):
                gestion_app._clear_ypareo_access_token_cache()
                response = FakeResponse(payload=response_payload)
                with patch.dict(
                    os.environ,
                    {
                        "YPAREO_API_URL": "https://ypareo.example/",
                        "YPAREO_AUTH_TOKEN": " initial-token ",
                        "YPAREO_AUTH_ENDPOINT": "/custom-authenticate",
                    },
                    clear=True,
                ), patch.object(gestion_app.requests, "post", return_value=response) as post:
                    token = gestion_app.get_ypareo_access_token()

                self.assertEqual(token, "access-token")
                post.assert_called_once_with(
                    "https://ypareo.example/custom-authenticate",
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json={"token": "initial-token"},
                    timeout=gestion_app.YPAREO_REQUEST_TIMEOUT_SECONDS,
                )

    def test_access_token_is_cached_for_default_thirty_minutes(self):
        response = FakeResponse(payload={"access_token": "cached-access-token"})
        with patch.dict(
            os.environ,
            {"YPAREO_AUTH_TOKEN": "initial-token"},
            clear=True,
        ), patch.object(gestion_app.requests, "post", return_value=response) as post, patch.object(
            gestion_app.time, "monotonic", side_effect=[100.0, 100.0, 100.0 + 1799]
        ):
            first_token = gestion_app.get_ypareo_access_token()
            second_token = gestion_app.get_ypareo_access_token()

        self.assertEqual(first_token, "cached-access-token")
        self.assertEqual(second_token, "cached-access-token")
        post.assert_called_once()
        self.assertEqual(gestion_app._ypareo_access_token_cache["expires_at"], 1900.0)

    def test_authentication_response_without_token_logs_only_its_structure(self):
        response = FakeResponse(payload={"data": {"credential": "sensitive-value"}, "status": "ok"})
        with patch.dict(os.environ, {"YPAREO_AUTH_TOKEN": "initial-token"}, clear=True), patch.object(
            gestion_app.requests, "post", return_value=response
        ), self.assertLogs(gestion_app.app.logger, level="ERROR") as logs:
            with self.assertRaisesRegex(
                gestion_app.YpareoAuthenticationError,
                "Authentification YPAREO impossible",
            ):
                gestion_app.get_ypareo_access_token()

        combined_logs = "\n".join(logs.output)
        self.assertIn('"credential": "<str>"', combined_logs)
        self.assertNotIn("sensitive-value", combined_logs)
        self.assertNotIn("initial-token", combined_logs)

    def test_creer_apprenant_authenticates_then_posts_with_access_token_and_saves_id(self):
        trainee = {"id": "T1", "last_name": "MARTIN", "first_name": "Alice"}
        auth_response = FakeResponse(payload={"data": {"access_token": "real-access-token"}})
        creation_response = FakeResponse(payload={"data": {"id": "YP-42"}})

        with patch.dict(
            os.environ,
            {
                "YPAREO_AUTH_TOKEN": "initial-token",
                "YPAREO_API_URL": "https://ypareo.example/",
                "YPAREO_AUTH_ENDPOINT": "/authenticate",
                "YPAREO_APPRENANTS_ENDPOINT": "/personne",
            },
            clear=True,
        ), patch.object(
            gestion_app.requests, "post", side_effect=[auth_response, creation_response]
        ) as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertTrue(result)
        self.assertEqual(trainee["ypareo_statut"], "Créé")
        self.assertEqual(trainee["ypareo_id"], "YP-42")
        self.assertEqual(trainee["ypareo_erreur"], "")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"], {"token": "initial-token"})
        self.assertEqual(post.call_args_list[1].args[0], "https://ypareo.example/personne")
        self.assertEqual(
            post.call_args_list[1].kwargs["headers"]["Authorization"],
            "Bearer real-access-token",
        )
        self.assertNotIn("initial-token", post.call_args_list[1].kwargs["headers"]["Authorization"])
        self.assertEqual(
            post.call_args_list[1].kwargs["json"],
            {"nom": "MARTIN", "nomNaissance": "MARTIN", "prenom": "Alice"},
        )

    def test_personne_401_clears_cache_reauthenticates_and_retries_once(self):
        trainee = {"id": "T1", "last_name": "MARTIN"}
        responses = [
            FakeResponse(payload={"token": "first-access-token"}),
            FakeResponse(status_code=401),
            FakeResponse(payload={"token": "second-access-token"}),
            FakeResponse(payload={"data": {"id": "YP-43"}}),
        ]
        with patch.dict(os.environ, {"YPAREO_AUTH_TOKEN": "initial-token"}, clear=True), patch.object(
            gestion_app.requests, "post", side_effect=responses
        ) as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertTrue(result)
        self.assertEqual(post.call_count, 4)
        self.assertEqual(post.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer first-access-token")
        self.assertEqual(post.call_args_list[3].kwargs["headers"]["Authorization"], "Bearer second-access-token")

    def test_second_personne_401_is_not_retried_again(self):
        trainee = {"id": "T1", "last_name": "MARTIN"}
        responses = [
            FakeResponse(payload={"token": "first-access-token"}),
            FakeResponse(status_code=401),
            FakeResponse(payload={"token": "second-access-token"}),
            FakeResponse(status_code=401),
        ]
        with patch.dict(os.environ, {"YPAREO_AUTH_TOKEN": "initial-token"}, clear=True), patch.object(
            gestion_app.requests, "post", side_effect=responses
        ) as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(post.call_count, 4)
        self.assertEqual(
            trainee["ypareo_erreur"],
            "Erreur YPAREO HTTP 401 : réponse API (réponse vide)",
        )

    def test_authentication_failure_records_clear_admin_error(self):
        trainee = {"id": "T1", "last_name": "MARTIN"}
        with patch.dict(os.environ, {"YPAREO_AUTH_TOKEN": "bad-initial-token"}, clear=True), patch.object(
            gestion_app.requests, "post", return_value=FakeResponse(status_code=401)
        ):
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(trainee["ypareo_erreur"], gestion_app.YPAREO_AUTH_ERROR_MESSAGE)
        self.assertNotIn("bad-initial-token", trainee["ypareo_erreur"])

    def test_personne_failure_keeps_local_data_and_records_clear_admin_error(self):
        trainee = {"id": "T1", "last_name": "MARTIN", "first_name": "Alice"}
        responses = [
            FakeResponse(payload={"token": "access-token"}),
            FakeResponse(status_code=422, payload={"message": "Données invalides"}),
        ]
        with patch.dict(os.environ, {"YPAREO_AUTH_TOKEN": "initial-token"}, clear=True), patch.object(
            gestion_app.requests, "post", side_effect=responses
        ):
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(trainee["last_name"], "MARTIN")
        self.assertEqual(trainee["ypareo_statut"], "Erreur")
        self.assertEqual(trainee["ypareo_erreur"], "Données invalides")

    def test_personne_logs_complete_request_context_without_tokens(self):
        trainee = {"id": "T-LOG", "last_name": "MARTIN", "first_name": "Alice"}
        responses = [
            FakeResponse(payload={"access_token": "secret-access-token"}),
            FakeResponse(
                status_code=422,
                payload={"message": "Données invalides"},
                text=(
                    '{"message":"Données invalides","access_token":"secret-access-token",'
                    '"Authorization":"Bearer secret-access-token",'
                    '"YPAREO_AUTH_TOKEN":"initial-token"}'
                ),
            ),
        ]
        with patch.dict(
            os.environ,
            {"YPAREO_AUTH_TOKEN": "initial-token", "YPAREO_API_URL": "https://ypareo.example"},
            clear=True,
        ), patch.object(gestion_app.requests, "post", side_effect=responses), self.assertLogs(
            gestion_app.app.logger, level="ERROR"
        ) as logs:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        api_log = next(line for line in logs.output if "réponse API" in line)
        self.assertIn('"operation": "POST /personne"', api_log)
        self.assertIn('"url": "https://ypareo.example/personne"', api_log)
        self.assertIn('"status_code": 422', api_log)
        self.assertIn('"trainee_id": "T-LOG"', api_log)
        self.assertIn('"payload": {"nom": "MARTIN"', api_log)
        self.assertIn("Données invalides", api_log)
        self.assertNotIn("initial-token", api_log)
        self.assertNotIn("secret-access-token", api_log)
        self.assertNotIn("Bearer secret-access-token", api_log)

    def test_missing_initial_token_is_recorded_without_http_request(self):
        trainee = {"id": "T1", "last_name": "MARTIN"}

        with patch.dict(os.environ, {}, clear=True), patch.object(gestion_app.requests, "post") as post:
            result = gestion_app.creer_apprenant_ypareo(trainee)

        self.assertFalse(result)
        self.assertEqual(trainee["ypareo_statut"], "Erreur")
        self.assertEqual(trainee["ypareo_erreur"], gestion_app.YPAREO_AUTH_ERROR_MESSAGE)
        post.assert_not_called()


class YpareoCursusTests(unittest.TestCase):
    def setUp(self):
        gestion_app._clear_ypareo_access_token_cache()
        self.session = {
            "id": "S1",
            "name": "APS Juillet 2026",
            "training_type": "APS",
            "date_start": "2026-07-01",
        }
        self.trainee = {"id": "T1", "ypareo_id": "YP-42"}

    def tearDown(self):
        gestion_app._clear_ypareo_access_token_cache()

    def test_platform_training_names_and_requested_aliases_map_to_render_variables(self):
        expected = {
            "APS": "YPAREO_ID_FORMATION_APS",
            "SSIAP": "YPAREO_ID_FORMATION_SSIAP1",
            "SSIAP 1": "YPAREO_ID_FORMATION_SSIAP1",
            "A3P": "YPAREO_ID_FORMATION_A3P",
            "VTC": "YPAREO_ID_FORMATION_VTC",
            "BTS MOS": "YPAREO_ID_FORMATION_BTS_MOS",
            "BTS MCO": "YPAREO_ID_FORMATION_BTS_MCO",
            "BTS NDRC": "YPAREO_ID_FORMATION_BTS_NDRC",
            "BTS PI": "YPAREO_ID_FORMATION_BTS_PI",
            "BTS CI": "YPAREO_ID_FORMATION_BTS_CI",
            "DIRIGEANT initial": "YPAREO_ID_FORMATION_DSSP",
            "DIRIGEANT VAE": "YPAREO_ID_FORMATION_DSSP",
            "Dirigeant sécurité privée": "YPAREO_ID_FORMATION_DSSP",
            "Dirigeant d’une entreprise de sécurité privée": "YPAREO_ID_FORMATION_DSSP",
            "DSSP": "YPAREO_ID_FORMATION_DSSP",
            "DO-ESP": "YPAREO_ID_FORMATION_DSSP",
            "DOESP": "YPAREO_ID_FORMATION_DSSP",
        }
        for training_name, environment_name in expected.items():
            with self.subTest(training_name=training_name):
                self.assertEqual(
                    gestion_app._ypareo_formation_environment_name(
                        {"training_type": training_name, "name": f"Session {training_name}"}
                    ),
                    environment_name,
                )

    def test_cursus_payload_uses_session_and_render_configuration(self):
        with patch.dict(os.environ, {
            "YPAREO_ID_FORMATION_APS": "formation-uuid",
            "YPAREO_ID_ORGANISME": "organisme-uuid",
            "YPAREO_ID_STATUT_CURSUS": "statut-uuid",
        }, clear=True):
            payload, error = gestion_app.construire_payload_cursus(self.session)

        self.assertIsNone(error)
        self.assertEqual(payload, {
            "dateDebutValiditeCertification": "2026-07-01",
            "idFormation": "formation-uuid",
            "idOrganisme": "organisme-uuid",
            "idSituationAvantApprentissage": 1,
            "nom": "APS Juillet 2026",
            "idStatut": "statut-uuid",
            "resultatCertification": 1,
        })

    def test_creer_cursus_posts_with_real_access_token_and_saves_response_id(self):
        responses = [
            FakeResponse(payload={"data": {"access_token": "real-access-token"}}),
            FakeResponse(payload={"data": {"id": "CURSUS-9"}}),
        ]
        with patch.dict(os.environ, {
            "YPAREO_AUTH_TOKEN": "initial-token",
            "YPAREO_API_URL": "https://ypareo.example/",
            "YPAREO_ID_FORMATION_APS": "formation-uuid",
            "YPAREO_ID_ORGANISME": "organisme-uuid",
            "YPAREO_ID_STATUT_CURSUS": "statut-uuid",
        }, clear=True), patch.object(gestion_app.requests, "post", side_effect=responses) as post:
            result = gestion_app.creer_cursus_ypareo("YP-42", self.trainee, self.session)

        self.assertTrue(result)
        self.assertEqual(self.trainee["ypareo_cursus_statut"], "Créé")
        self.assertEqual(self.trainee["ypareo_cursus_id"], "CURSUS-9")
        self.assertEqual(self.trainee["ypareo_cursus_erreur"], "")
        self.assertEqual(post.call_args_list[1].args[0], "https://ypareo.example/personne/YP-42/cursus")
        self.assertEqual(post.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer real-access-token")

    def test_cursus_logs_complete_context_without_tokens(self):
        responses = [
            FakeResponse(payload={"token": "secret-access-token"}),
            FakeResponse(
                status_code=422,
                payload={"message": "Cursus invalide"},
                text='{ "detail": "Cursus invalide", "access_token": "secret-access-token" }',
            ),
        ]
        with patch.dict(os.environ, {
            "YPAREO_AUTH_TOKEN": "initial-token",
            "YPAREO_API_URL": "https://ypareo.example",
            "YPAREO_ID_FORMATION_APS": "formation-uuid",
        }, clear=True), patch.object(
            gestion_app.requests, "post", side_effect=responses
        ), self.assertLogs(gestion_app.app.logger, level="ERROR") as logs:
            result = gestion_app.creer_cursus_ypareo("YP-42", self.trainee, self.session)

        self.assertFalse(result)
        api_log = next(line for line in logs.output if "réponse API" in line)
        self.assertIn('"operation": "POST /personne/{IdPersonne}/cursus"', api_log)
        self.assertIn('"url": "https://ypareo.example/personne/YP-42/cursus"', api_log)
        self.assertIn('"status_code": 422', api_log)
        self.assertIn('"trainee_id": "T1"', api_log)
        self.assertIn('"idPersonne": "YP-42"', api_log)
        self.assertIn('"nom_formation": "APS"', api_log)
        self.assertIn('"idFormation": "formation-uuid"', api_log)
        self.assertIn('"payload": {', api_log)
        self.assertIn("Cursus invalide", api_log)
        self.assertNotIn("initial-token", api_log)
        self.assertNotIn("secret-access-token", api_log)

    def test_missing_mapping_records_error_without_http_request(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(gestion_app.requests, "post") as post:
            result = gestion_app.creer_cursus_ypareo(
                "YP-42", self.trainee, {"training_type": "CHEF DE POSTE", "name": "Session chef"}
            )

        self.assertFalse(result)
        self.assertEqual(self.trainee["ypareo_cursus_statut"], "Erreur")
        self.assertEqual(self.trainee["ypareo_cursus_erreur"], gestion_app.YPAREO_FORMATION_NOT_LINKED_ERROR)
        post.assert_not_called()

    def test_missing_dssp_configuration_has_specific_error(self):
        with patch.dict(os.environ, {}, clear=True):
            result = gestion_app.creer_cursus_ypareo(
                "YP-42", self.trainee, {"training_type": "DIRIGEANT VAE", "name": "VAE dirigeant"}
            )

        self.assertFalse(result)
        self.assertEqual(self.trainee["ypareo_cursus_erreur"], gestion_app.YPAREO_DSSP_NOT_CONFIGURED_ERROR)

    def test_api_failure_keeps_person_and_records_api_message(self):
        responses = [
            FakeResponse(payload={"token": "access-token"}),
            FakeResponse(status_code=422, payload={"message": "Cursus invalide"}),
        ]
        with patch.dict(os.environ, {
            "YPAREO_AUTH_TOKEN": "initial-token",
            "YPAREO_ID_FORMATION_APS": "formation-uuid",
        }, clear=True), patch.object(gestion_app.requests, "post", side_effect=responses):
            result = gestion_app.creer_cursus_ypareo("YP-42", self.trainee, self.session)

        self.assertFalse(result)
        self.assertEqual(self.trainee["ypareo_id"], "YP-42")
        self.assertEqual(self.trainee["ypareo_cursus_statut"], "Erreur")
        self.assertEqual(self.trainee["ypareo_cursus_erreur"], "Cursus invalide")

    def test_person_creation_automatically_creates_cursus(self):
        responses = [
            FakeResponse(payload={"token": "access-token"}),
            FakeResponse(payload={"data": {"id": "YP-42"}}),
            FakeResponse(payload={"data": {"id": "CURSUS-10"}}),
        ]
        trainee = {"id": "T1", "last_name": "MARTIN"}
        with patch.dict(os.environ, {
            "YPAREO_AUTH_TOKEN": "initial-token",
            "YPAREO_ID_FORMATION_APS": "formation-uuid",
        }, clear=True), patch.object(gestion_app.requests, "post", side_effect=responses):
            result = gestion_app.creer_apprenant_ypareo(trainee, self.session)

        self.assertTrue(result)
        self.assertEqual(trainee["ypareo_id"], "YP-42")
        self.assertEqual(trainee["ypareo_cursus_id"], "CURSUS-10")


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
        def fake_send(trainee, session_obj):
            self.assertEqual(session_obj["id"], "S1")
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
        def fake_failure(trainee, session_obj):
            self.assertEqual(session_obj["id"], "S1")
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
        send.assert_called_once_with(created, self.data["sessions"][0])
        self.assertGreaterEqual(save.call_count, 2)

    def test_manual_send_flashes_real_ypareo_api_error(self):
        def fake_failure(trainee, session_obj):
            trainee["ypareo_statut"] = "Erreur"
            trainee["ypareo_erreur"] = "Erreur YPAREO HTTP 422 : réponse API champ nom obligatoire"
            return False

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ), patch.object(gestion_app, "creer_apprenant_ypareo", side_effect=fake_failure):
            response = self.client.post("/admin/sessions/S1/trainees/T1/ypareo")

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            flashed_messages = [message for _category, message in session.get("_flashes", [])]
        self.assertTrue(any(
            "Erreur YPAREO HTTP 422 : réponse API champ nom obligatoire" in message
            for message in flashed_messages
        ))

    def test_manual_cursus_button_and_route_only_create_cursus(self):
        trainee = self.data["sessions"][0]["trainees"][0]
        trainee["ypareo_id"] = "YP-99"

        def fake_cursus(id_personne, target, session_obj):
            self.assertEqual(id_personne, "YP-99")
            self.assertEqual(session_obj["id"], "S1")
            target["ypareo_cursus_statut"] = "Créé"
            target["ypareo_cursus_id"] = "CURSUS-99"
            target["ypareo_cursus_erreur"] = ""
            return True

        with patch.object(gestion_app, "load_data", return_value=self.data), patch.object(
            gestion_app, "save_data"
        ) as save, patch.object(gestion_app, "creer_cursus_ypareo", side_effect=fake_cursus) as create:
            page = self.client.get("/admin/sessions/S1/trainees")
            save.reset_mock()
            response = self.client.post("/admin/sessions/S1/trainees/T1/ypareo/cursus")

        self.assertIn("Créer cursus YPAREO", page.get_data(as_text=True))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(trainee["ypareo_cursus_id"], "CURSUS-99")
        create.assert_called_once()
        save.assert_called_once_with(self.data)


if __name__ == "__main__":
    unittest.main()
