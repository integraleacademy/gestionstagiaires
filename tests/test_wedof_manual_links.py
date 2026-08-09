import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import app as gestion_app
from wedof_service import WedofClient


def local_data():
    return {"sessions": [
        {"id": "S1", "name": "APS SEPTEMBRE 2026", "training_type": "APS",
         "date_start": "2026-09-07", "date_end": "2026-10-09", "trainees": [
             {"id": "T1", "first_name": "Stéphane", "last_name": "BERTIN",
              "email": "sbertin@example.fr", "phone": "0612345678"}]},
        {"id": "S2", "name": "Ancienne session", "training_type": "DIRIGEANT",
         "date_start": "2025-01-01", "date_end": "2025-01-02", "archived": True,
         "trainees": [{"id": "T2", "first_name": "Autre", "last_name": "Personne"}]},
    ], "wedof_links": []}


def remote_folder(**changes):
    value = {"externalId": "W1", "state": "accepted", "type": "cpf",
             "attendee": {"firstName": "Stéphane", "lastName": "BERTIN"},
             "trainingActionInfo": {"startDate": "2026-09-07", "endDate": "2026-10-09"}}
    value.update(changes)
    return value


class ManualLinkTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True

    def test_searches_are_minimal_archived_and_scoped(self):
        with patch.object(gestion_app, "load_data", return_value=local_data()):
            response = self.client.get("/admin/wedof/matching/manual/sessions?q=2026-09-07")
            self.assertEqual(set(response.json["items"][0]), {"id", "name", "training_type", "date_start", "date_end", "archived"})
            archived = self.client.get("/admin/wedof/matching/manual/sessions?q=ancienne").json["items"][0]
            self.assertTrue(archived["archived"])
            trainees = self.client.get("/admin/wedof/matching/manual/trainees?session_id=S1&q=bertin").json["items"]
            self.assertEqual([item["id"] for item in trainees], ["T1"])
            self.assertEqual(self.client.get("/admin/wedof/matching/manual/trainees?session_id=missing").status_code, 404)

    def test_authentication_is_required(self):
        anonymous = gestion_app.app.test_client()
        self.assertEqual(anonymous.get("/admin/wedof/matching/manual/sessions").status_code, 302)
        self.assertEqual(anonymous.post("/admin/wedof/matching/manual-link").status_code, 302)

    def test_preview_buttons_only_for_eligible_unlinked_rows(self):
        folders = [
            remote_folder(externalId="NOSESSION", trainingActionInfo={"startDate":"2027-01-01", "endDate":"2027-01-02"}),
            remote_folder(externalId="NOTRAINEE", attendee={"firstName":"Sans", "lastName":"Match", "email":"none@example.fr"}),
            remote_folder(externalId="AMBIG", attendee={"firstName":"Stéphane", "lastName":"BERTIN", "email":"sbertin@example.fr"}),
            remote_folder(externalId="MISSING", attendee={}),
            remote_folder(externalId="NONCPF", type="other"),
            remote_folder(externalId="", attendee={}),
        ]
        data = local_data()
        data["sessions"][0]["trainees"].append(dict(data["sessions"][0]["trainees"][0], id="T3"))
        remote = Mock(); remote.list_registration_folders.side_effect = [folders, []]
        with patch.object(gestion_app, "WedofClient", return_value=remote), patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]):
            html = self.client.post("/admin/wedof/matching/preview").get_data(as_text=True)
        self.assertEqual(html.count("Associer manuellement</button>"), 4)
        self.assertNotIn('data-external-id="NONCPF"', html)

    def test_client_detail_is_get_only_with_api_key(self):
        response = Mock(status_code=200, headers={}); response.json.return_value = remote_folder()
        http = Mock(); http.get.return_value = response
        self.assertEqual(WedofClient(api_key="test-key", session=http).get_registration_folder("W1")["externalId"], "W1")
        call = http.get.call_args
        self.assertEqual(call.args[0], "https://www.wedof.fr/api/registrationFolders/W1")
        self.assertEqual(call.kwargs["headers"], {"Accept": "application/json", "X-Api-Key": "test-key"})
        for method in ("post", "put", "patch", "delete"):
            getattr(http, method).assert_not_called()

    def _post(self, payload, folder=None):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "data.json")
        with open(path, "w", encoding="utf-8") as stream: json.dump(local_data(), stream)
        remote = Mock(); remote.get_registration_folder.return_value = folder or remote_folder()
        patches = [patch.object(gestion_app, "DATA_FILE", path), patch.object(gestion_app, "BACKUP_DIR", tmp.name),
                   patch.object(gestion_app, "WedofClient", return_value=remote)]
        for item in patches: item.start(); self.addCleanup(item.stop)
        response = self.client.post("/admin/wedof/matching/manual-link", data=payload,
                                    headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        with open(path, encoding="utf-8") as stream: saved = json.load(stream)
        return response, saved

    def test_validation_membership_confirmations_type_and_state(self):
        base = {"external_id": "W1", "session_id": "S1", "trainee_id": "T1"}
        self.assertEqual(self._post(base)[0].status_code, 400)
        self.assertEqual(self._post({**base, "confirm_manual_link": "1", "trainee_id": "T2"})[0].status_code, 400)
        self.assertEqual(self._post({**base, "confirm_manual_link": "1"}, remote_folder(type="other"))[0].status_code, 400)
        self.assertIn("completed", self._post({**base, "confirm_manual_link": "1"}, remote_folder(state="completed"))[0].json["message"])
        mismatch = {**base, "session_id": "S2", "trainee_id": "T2", "confirm_manual_link": "1"}
        self.assertEqual(self._post(mismatch)[0].status_code, 400)

    def test_creation_is_private_idempotent_and_conflict_safe(self):
        payload = {"external_id": "W1", "session_id": "S1", "trainee_id": "T1", "confirm_manual_link": "1"}
        response, saved = self._post(payload)
        self.assertEqual(response.status_code, 200)
        link = saved["wedof_links"][0]
        self.assertEqual((link["source"], link["matching_rule"]), ("manual_admin", "manual_selection"))
        self.assertFalse(set(link) & {"first_name", "last_name", "email", "phone", "raw_payload", "headers"})

    def test_manual_link_allows_different_local_dates_and_keeps_wedof_dates(self):
        payload = {"external_id": "W1", "session_id": "S2", "trainee_id": "T2",
                   "confirm_manual_link": "1", "confirm_date_mismatch": "1"}
        response, saved = self._post(payload)
        self.assertEqual(response.status_code, 200)
        link = saved["wedof_links"][0]
        self.assertEqual((link["session_id"], link["trainee_id"]), ("S2", "T2"))
        self.assertEqual((link["wedof_date_start"], link["wedof_date_end"]),
                         ("2026-09-07", "2026-10-09"))

    def test_non_javascript_fallback_redirects_with_flash(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "data.json")
        with open(path, "w", encoding="utf-8") as stream: json.dump(local_data(), stream)
        remote = Mock(); remote.get_registration_folder.return_value = remote_folder()
        with patch.object(gestion_app, "DATA_FILE", path), patch.object(gestion_app, "BACKUP_DIR", tmp.name), patch.object(gestion_app, "WedofClient", return_value=remote):
            response = self.client.post("/admin/wedof/matching/manual-link", data={"external_id":"W1", "session_id":"S1", "trainee_id":"T1", "confirm_manual_link":"1"})
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
