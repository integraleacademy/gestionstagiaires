import unittest

import app as gestion_app


class AfcArchiveAllCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_load_data = gestion_app.load_data
        self.original_save_data = gestion_app.save_data
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    def tearDown(self):
        gestion_app.load_data = self.original_load_data
        gestion_app.save_data = self.original_save_data

    def test_archive_all_preserves_candidates_and_marks_active_ones(self):
        data = {"afc": {"candidates": [
            {"id": "AFC-1", "nom": "DUPONT", "prenom": "Jean"},
            {"id": "AFC-2", "nom": "MARTIN", "prenom": "Léa", "archived": True},
        ]}}
        gestion_app.load_data = lambda: data
        saved = []
        gestion_app.save_data = lambda updated: saved.append(updated)

        response = self.client.post("/api/admin/afc/candidates/archive-all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "archived": 1})
        self.assertEqual(len(data["afc"]["candidates"]), 2)
        self.assertTrue(data["afc"]["candidates"][0]["archived"])
        self.assertTrue(data["afc"]["candidates"][0]["archived_at"])
        self.assertGreaterEqual(len(saved), 1)

    def test_admin_page_hides_archived_candidates_and_has_archive_button(self):
        gestion_app.load_data = lambda: {"afc": {"candidates": [
            {"id": "AFC-ACTIVE", "nom": "ACTIF", "prenom": "Anne"},
            {"id": "AFC-ARCHIVED", "nom": "ARCHIVE", "prenom": "Alain", "archived": True},
        ]}}

        response = self.client.get("/admin/afc")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Archiver tous les candidats", html)
        self.assertIn("/api/admin/afc/candidates/archive-all", html)
        self.assertIn("AFC-ACTIVE", html)
        self.assertNotIn("AFC-ARCHIVED", html)
        self.assertIn("Archives (1)", html)

    def test_archives_page_lists_archived_candidates_only(self):
        gestion_app.load_data = lambda: {"afc": {"candidates": [
            {"id": "AFC-ACTIVE", "nom": "ACTIF", "prenom": "Anne"},
            {"id": "AFC-ARCHIVED", "nom": "ARCHIVE", "prenom": "Alain", "archived": True},
        ]}}

        response = self.client.get("/admin/afc?archives=1")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Candidats AFC archivés", html)
        self.assertIn("AFC-ARCHIVED", html)
        self.assertNotIn("AFC-ACTIVE", html)
        self.assertIn("Restaurer", html)
        self.assertIn("/api/admin/afc/candidates/${tr.dataset.id}/unarchive", html)

    def test_unarchive_candidate_restores_it_to_active_list(self):
        data = {"afc": {"candidates": [
            {"id": "AFC-ARCHIVED", "nom": "ARCHIVE", "prenom": "Alain", "archived": True, "archived_at": "2026-08-04T10:00:00Z"},
        ]}}
        gestion_app.load_data = lambda: data
        saved = []
        gestion_app.save_data = lambda updated: saved.append(updated)

        response = self.client.post("/api/admin/afc/candidates/AFC-ARCHIVED/unarchive")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "restored": True})
        self.assertFalse(data["afc"]["candidates"][0]["archived"])
        self.assertNotIn("archived_at", data["afc"]["candidates"][0])
        self.assertGreaterEqual(len(saved), 1)

    def test_mail_template_replaces_date_icop_with_french_date(self):
        rendered = gestion_app._afc_render_mail_template(
            "Rendez-vous ICOP le {{date_icop}} pour {{prenom}}.",
            {"prenom": "Léa", "date_icop": "2026-08-04"},
        )

        self.assertEqual(rendered, "Rendez-vous ICOP le 04/08/2026 pour Léa.")


if __name__ == "__main__":
    unittest.main()
