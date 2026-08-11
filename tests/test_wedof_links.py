import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import app as gestion_app
from wedof_links import local_association_status, sync_exact_wedof_links


def data():
    return {"sessions": [{"id": "S1", "name": "Session", "date_start": "2026-09-01", "date_end": "2026-09-02", "trainees": [{"id": "T1", "first_name": "Alice", "last_name": "Test", "email": "a@test.fr", "phone": "0612345678"}]}]}


def exact(**changes):
    item = {"status": "exact_match", "external_id": "W1", "session_id": "S1", "trainee_id": "T1", "type": "cpf", "state": "accepted", "rule": "email_phone_dates", "start_date": "2026-09-01", "end_date": "2026-09-02"}
    item.update(changes)
    return item


class WedofLinksServiceTests(unittest.TestCase):
    def test_absent_collection_is_added_and_exact_is_whitelisted(self):
        payload = data()
        summary = sync_exact_wedof_links(payload, [exact(raw_payload={"secret": 1}, email="private@test.fr")], now="2026-08-08T00:00:00+00:00")
        self.assertEqual(summary["created"], 1)
        self.assertEqual(len(payload["wedof_links"]), 1)
        self.assertEqual(set(payload["wedof_links"][0]), {"id", "external_id", "session_id", "trainee_id", "source", "matching_rule", "wedof_state", "wedof_type", "wedof_date_start", "wedof_date_end", "active", "created_at", "updated_at", "last_seen_at"})
        self.assertNotIn("private@test.fr", json.dumps(payload["wedof_links"]))
        self.assertNotIn("secret", json.dumps(payload["wedof_links"]))

    def test_all_non_exact_categories_are_ignored(self):
        payload = data()
        statuses = ["ambiguous_match", "no_session_match", "no_trainee_match", "missing_wedof_data", "excluded_non_cpf"]
        result = sync_exact_wedof_links(payload, [exact(status=value) for value in statuses])
        self.assertEqual(result["skipped"], 5); self.assertEqual(payload["wedof_links"], [])

    def test_required_fields_type_states_and_local_registration(self):
        for changes in ({"external_id": ""}, {"type": "other"}, {"state": "completed"}, {"session_id": "missing"}, {"trainee_id": "missing"}):
            payload = data(); self.assertEqual(sync_exact_wedof_links(payload, [exact(**changes)])["created"], 0)
        for state in ("accepted", "inTraining"):
            payload = data(); self.assertEqual(sync_exact_wedof_links(payload, [exact(state=state)])["created"], 1)

    def test_idempotence_state_update_and_no_deletion(self):
        payload = data()
        sync_exact_wedof_links(payload, [exact()], now="one")
        first_id = payload["wedof_links"][0]["id"]
        summary = sync_exact_wedof_links(payload, [exact(state="inTraining")], now="two")
        self.assertEqual((summary["already_linked"], summary["updated"]), (1, 1))
        self.assertEqual(len(payload["wedof_links"]), 1); self.assertEqual(payload["wedof_links"][0]["id"], first_id)
        sync_exact_wedof_links(payload, [])
        self.assertEqual(len(payload["wedof_links"]), 1)

    def test_both_uniqueness_conflicts(self):
        payload = data(); sync_exact_wedof_links(payload, [exact()])
        payload["sessions"][0]["trainees"].append({"id": "T2"})
        self.assertEqual(sync_exact_wedof_links(payload, [exact(trainee_id="T2")])["conflicts"], 1)
        self.assertEqual(sync_exact_wedof_links(payload, [exact(external_id="W2")])["conflicts"], 1)
        self.assertEqual(len(payload["wedof_links"]), 1)

    def test_preview_labels(self):
        payload = data(); sync_exact_wedof_links(payload, [exact()])
        self.assertEqual(local_association_status(exact(), payload["wedof_links"]), "Déjà enregistrée automatiquement")
        self.assertEqual(local_association_status(exact(external_id="W2"), payload["wedof_links"]), "Conflit avec une association existante")
        self.assertEqual(local_association_status(exact(status="ambiguous_match"), []), "Non associable automatiquement")

    def test_atomic_concurrent_writes_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            with open(path, "w", encoding="utf-8") as stream: json.dump(data(), stream)
            def synchronize():
                def transform(_):
                    canonical = gestion_app._load_valid_json_payload(path) or data()
                    sync_exact_wedof_links(canonical, [exact()])
                    return canonical
                gestion_app._write_json_with_backups(path, {}, gestion_app._data_lock, payload_transform=transform)
            with patch.object(gestion_app, "BACKUP_DIR", tmp):
                with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _: synchronize(), range(2)))
            with open(path, encoding="utf-8") as stream: saved = json.load(stream)
            self.assertEqual(len(saved["wedof_links"]), 1)


class WedofLinksRouteTests(unittest.TestCase):
    def setUp(self): self.client = gestion_app.app.test_client()

    def test_authentication_required(self):
        with patch.object(gestion_app, "WedofClient") as client:
            response = self.client.post("/admin/wedof/matching/sync-exact")
        self.assertEqual(response.status_code, 302); client.assert_not_called()

    def test_route_recalculates_ignores_browser_ids_and_only_gets(self):
        with self.client.session_transaction() as session: session["admin_logged_in"] = True
        folder = {"externalId": "W1", "state": "accepted", "type": "cpf", "attendee": {"firstName": "Alice", "lastName": "Test", "email": "a@test.fr", "phoneNumber": "0612345678"}, "trainingActionInfo": {"startDate": "2026-09-01", "endDate": "2026-09-02"}}
        remote = Mock(); remote.list_registration_folders.side_effect = [[folder], []]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.json")
            with open(path, "w", encoding="utf-8") as stream: json.dump(data(), stream)
            with patch.object(gestion_app, "DATA_FILE", path), patch.object(gestion_app, "BACKUP_DIR", tmp), patch.object(gestion_app, "WedofClient", return_value=remote):
                response = self.client.post("/admin/wedof/matching/sync-exact", data={"external_id": "EVIL", "session_id": "EVIL", "trainee_id": "EVIL"})
                with open(path, encoding="utf-8") as stream: saved = json.load(stream)
            self.assertEqual(response.status_code, 302); self.assertEqual(saved["wedof_links"][0]["external_id"], "W1")
        self.assertEqual([call.args[0] for call in remote.list_registration_folders.call_args_list], ["accepted", "inTraining"])

    def test_preview_does_not_write(self):
        with self.client.session_transaction() as session: session["admin_logged_in"] = True
        remote = Mock(); remote.list_registration_folders.side_effect = [[], []]
        with patch.object(gestion_app, "WedofClient", return_value=remote), patch.object(gestion_app, "load_data", return_value=data()), patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), patch.object(gestion_app, "_write_json_with_backups") as write:
            response = self.client.post("/admin/wedof/matching/preview")
        write.assert_not_called()
        html = response.get_data(as_text=True)
        self.assertIn('class="app-shell"', html)
        self.assertIn('class="partner-sidebar admin-sidebar"', html)
        self.assertIn("wedof-preview-table-wrap", html)
        self.assertIn('aria-label="Prévisualisation des correspondances WEDOF"', html)
        self.assertIn("Faites défiler le tableau horizontalement", html)
        self.assertIn("max-height:calc(100vh - 340px)", html)
        self.assertIn("position:sticky;top:0", html)
        self.assertIn("Association locale", html)


if __name__ == "__main__": unittest.main()
