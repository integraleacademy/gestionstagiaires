import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import app as gestion_app
from wedof_matching import find_trainee_cpf_candidates


def local_data():
    return {
        "sessions": [{
            "id": "S1",
            "name": "APS septembre",
            "training_type": "APS",
            "date_start": "2026-09-07",
            "date_end": "2026-10-09",
            "trainees": [{
                "id": "T1",
                "first_name": "Élodie",
                "last_name": "D'Arc",
                "email": "elodie@example.fr",
                "phone": "06 12 34 56 78",
                "cpf_amount": 1650,
            }],
        }],
        "wedof_links": [],
    }


def remote_folder(external_id="CPF-1", **changes):
    value = {
        "externalId": external_id,
        "state": "accepted",
        "type": "cpf",
        "attendee": {
            "firstName": "Elodie",
            "lastName": "D-Arc",
            "email": "ELODIE@example.fr",
            "phoneNumber": "+33 6 12 34 56 78",
        },
        "trainingActionInfo": {
            "startDate": "2026-09-07",
            "endDate": "2026-10-09",
            "title": "Agent de prévention et de sécurité",
        },
    }
    value.update(changes)
    return value


class CandidateMatchingTests(unittest.TestCase):
    def test_all_fields_are_required_for_automatic_match(self):
        data = local_data()
        session = data["sessions"][0]
        trainee = session["trainees"][0]
        exact = find_trainee_cpf_candidates(
            [remote_folder()], session, trainee,
            allowed_states=gestion_app.CPF_ASSOCIATION_STATES,
        )
        self.assertEqual(len(exact), 1)
        self.assertTrue(exact[0]["all_fields_match"])
        self.assertEqual(exact[0]["match_reasons"], [
            "Même e-mail", "Même téléphone", "Même identité", "Mêmes dates de formation",
        ])

        different_dates = remote_folder(trainingActionInfo={
            "startDate": "2026-09-08", "endDate": "2026-10-10",
        })
        suggestion = find_trainee_cpf_candidates(
            [different_dates], session, trainee,
            allowed_states=gestion_app.CPF_ASSOCIATION_STATES,
        )[0]
        self.assertFalse(suggestion["all_fields_match"])
        self.assertIn("Dates de formation différentes", suggestion["mismatches"])

    def test_both_email_and_phone_are_required_for_a_suggestion(self):
        data = local_data()
        session = data["sessions"][0]
        trainee = session["trainees"][0]
        email_only = remote_folder(attendee={
            "firstName": "Elodie", "lastName": "D-Arc",
            "email": "elodie@example.fr", "phoneNumber": "0700000000",
        })
        phone_only = remote_folder("CPF-2", attendee={
            "firstName": "Elodie", "lastName": "D-Arc",
            "email": "other@example.fr", "phoneNumber": "0612345678",
        })
        self.assertEqual(find_trainee_cpf_candidates(
            [email_only, phone_only], session, trainee,
            allowed_states=gestion_app.CPF_ASSOCIATION_STATES,
        ), [])

    def test_output_is_whitelisted(self):
        data = local_data()
        folder = remote_folder(secret={"api_key": "NEVER"})
        result = find_trainee_cpf_candidates(
            [folder], data["sessions"][0], data["sessions"][0]["trainees"][0],
        )
        self.assertNotIn("NEVER", json.dumps(result))


class CpfAutoMatchRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

    def _store(self, payload=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = os.path.join(temp.name, "data.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload or local_data(), stream)
        return temp.name, path

    @staticmethod
    def _listing_client(*folders):
        remote = Mock()
        remote.list_registration_folders.side_effect = [list(folders), [], [], []]
        return remote

    def test_authentication_is_required(self):
        anonymous = gestion_app.app.test_client()
        with patch.object(gestion_app, "WedofClient") as client:
            response = anonymous.post("/admin/sessions/S1/stagiaires/T1/cpf/auto-match")
        self.assertEqual(response.status_code, 302)
        client.assert_not_called()

    def test_unique_complete_match_is_associated_automatically(self):
        temp, path = self._store()
        remote = self._listing_client(remote_folder())
        with patch.object(gestion_app, "DATA_FILE", path), \
             patch.object(gestion_app, "BACKUP_DIR", temp), \
             patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post("/admin/sessions/S1/stagiaires/T1/cpf/auto-match")
        with open(path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "associated")
        link = saved["wedof_links"][0]
        self.assertEqual((link["source"], link["matching_rule"]),
                         ("automatic_exact_match", "email_phone_identity_dates"))
        self.assertEqual(link["cpf_snapshot"]["external_id"], "CPF-1")
        automation = saved["wedof_automation_status"][0]
        self.assertEqual(automation["external_id"], "CPF-1")
        self.assertIn(automation["entry_training"]["status"], {
            "planned", "dry_run_due", "dry_run_due_late",
        })
        self.assertEqual(automation["service_done"]["status"], "waiting_for_in_training")
        self.assertEqual(
            [call.args[0] for call in remote.list_registration_folders.call_args_list],
            list(gestion_app.CPF_ASSOCIATION_STATES),
        )
        remote.get_registration_folder_interactive.assert_not_called()

    def test_contact_match_with_different_dates_is_proposed_without_write(self):
        temp, path = self._store()
        folder = remote_folder(trainingActionInfo={
            "startDate": "2026-09-08", "endDate": "2026-10-10", "title": "APS",
        })
        remote = self._listing_client(folder)
        with patch.object(gestion_app, "DATA_FILE", path), \
             patch.object(gestion_app, "BACKUP_DIR", temp), \
             patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post("/admin/sessions/S1/stagiaires/T1/cpf/auto-match")
        with open(path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "suggestions")
        self.assertEqual(response.json["candidates"][0]["external_id"], "CPF-1")
        self.assertIn("Dates de formation différentes", response.json["candidates"][0]["mismatches"])
        self.assertEqual(saved["wedof_links"], [])

    def test_two_complete_matches_are_never_auto_associated(self):
        temp, path = self._store()
        remote = self._listing_client(remote_folder("CPF-1"), remote_folder("CPF-2"))
        with patch.object(gestion_app, "DATA_FILE", path), \
             patch.object(gestion_app, "BACKUP_DIR", temp), \
             patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post("/admin/sessions/S1/stagiaires/T1/cpf/auto-match")
        with open(path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(response.json["status"], "suggestions")
        self.assertEqual(len(response.json["candidates"]), 2)
        self.assertEqual(saved["wedof_links"], [])

    def test_suggested_folder_is_associated_in_one_verified_click(self):
        temp, path = self._store()
        folder = remote_folder(trainingActionInfo={
            "startDate": "2026-09-08", "endDate": "2026-10-10", "title": "APS",
        })
        remote = Mock()
        remote.get_registration_folder_interactive.return_value = folder
        with patch.object(gestion_app, "DATA_FILE", path), \
             patch.object(gestion_app, "BACKUP_DIR", temp), \
             patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post(
                "/admin/sessions/S1/stagiaires/T1/cpf/associate-match",
                data={"external_id": "CPF-1"},
            )
        with open(path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "associated")
        self.assertEqual(saved["wedof_links"][0]["source"], "manual_admin")
        self.assertEqual(saved["wedof_links"][0]["wedof_date_start"], "2026-09-08")
        remote.get_registration_folder_interactive.assert_called_once_with("CPF-1")

    def test_one_click_refuses_a_folder_whose_contacts_changed(self):
        temp, path = self._store()
        remote = Mock()
        remote.get_registration_folder_interactive.return_value = remote_folder(attendee={
            "firstName": "Elodie", "lastName": "D-Arc",
            "email": "other@example.fr", "phoneNumber": "0612345678",
        })
        with patch.object(gestion_app, "DATA_FILE", path), \
             patch.object(gestion_app, "BACKUP_DIR", temp), \
             patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post(
                "/admin/sessions/S1/stagiaires/T1/cpf/associate-match",
                data={"external_id": "CPF-1"},
            )
        with open(path, encoding="utf-8") as stream:
            saved = json.load(stream)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(saved["wedof_links"], [])


if __name__ == "__main__":
    unittest.main()
