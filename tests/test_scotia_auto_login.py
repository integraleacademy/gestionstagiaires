import unittest

import app as gestion_app


class ScotiaLoginTests(unittest.TestCase):
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

    def test_scotia_login_requires_credentials_for_integrale_admin(self):
        self.client.post(
            "/admin/login",
            data={
                "username": "clement@integraleacademy.com",
                "password": "admin-secret",
                "next": "/admin/sessions",
            },
        )

        response = self.client.get("/scotia/login")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Connexion SCOTIA", html)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess["admin_logged_in"])
            self.assertNotIn("scotia_logged_in", sess)
            self.assertEqual(sess["admin_username"], "clement@integraleacademy.com")

    def test_admin_login_cookie_is_not_persistent(self):
        response = self.client.post(
            "/admin/login",
            data={
                "username": "clement@integraleacademy.com",
                "password": "admin-secret",
                "next": "/admin/sessions",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("Expires=", response.headers.get("Set-Cookie", ""))
        self.assertNotIn("Max-Age=", response.headers.get("Set-Cookie", ""))

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
