import unittest

import app as gestion_app


class ScotiaAutoLoginTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        self.original_admin_user = gestion_app.ADMIN_USER
        self.original_admin_password = gestion_app.ADMIN_PASSWORD
        self.original_secretary_user = gestion_app.SECRETARY_USER
        self.original_secretary_password = gestion_app.SECRETARY_PASSWORD
        gestion_app.ADMIN_USER = "clement@integraleacademy.com"
        gestion_app.ADMIN_PASSWORD = "admin-secret"
        gestion_app.SECRETARY_USER = "secretariat@example.test"
        gestion_app.SECRETARY_PASSWORD = "viewer-secret"

    def tearDown(self):
        gestion_app.ADMIN_USER = self.original_admin_user
        gestion_app.ADMIN_PASSWORD = self.original_admin_password
        gestion_app.SECRETARY_USER = self.original_secretary_user
        gestion_app.SECRETARY_PASSWORD = self.original_secretary_password

    def test_scotia_login_auto_connects_integrale_admin(self):
        self.client.post(
            "/admin/login",
            data={
                "username": "clement@integraleacademy.com",
                "password": "admin-secret",
                "next": "/admin/sessions",
            },
        )

        response = self.client.get("/scotia/login")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/scotia")
        with self.client.session_transaction() as sess:
            self.assertTrue(sess["admin_logged_in"])
            self.assertTrue(sess["scotia_logged_in"])
            self.assertEqual(sess["scotia_username"], "clement@integraleacademy.com")
            self.assertEqual(sess["admin_username"], "clement@integraleacademy.com")

    def test_scotia_login_auto_connects_legacy_integrale_admin_session(self):
        with self.client.session_transaction() as sess:
            sess["admin_logged_in"] = True
            sess["admin_role"] = "admin"

        response = self.client.get("/scotia/login?next=/scotia?filter=pending")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/scotia?filter=pending")
        with self.client.session_transaction() as sess:
            self.assertTrue(sess["scotia_logged_in"])
            self.assertEqual(sess["scotia_username"], "clement@integraleacademy.com")

    def test_scotia_login_does_not_auto_connect_viewer(self):
        self.client.post(
            "/admin/login",
            data={
                "username": "secretariat@example.test",
                "password": "viewer-secret",
                "next": "/admin/sessions",
            },
        )

        response = self.client.get("/scotia/login")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Connexion SCOTIA", html)
        with self.client.session_transaction() as sess:
            self.assertNotIn("scotia_logged_in", sess)
            self.assertEqual(sess["admin_username"], "secretariat@example.test")
