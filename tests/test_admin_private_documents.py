import io
import os
import tempfile
import unittest
from unittest.mock import patch

import app as gestion_app


class AdminPrivateDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    @staticmethod
    def _data():
        return {
            "sessions": [{
                "id": "SESSION-1",
                "training_type": "APS",
                "trainees": [{"id": "TRAINEE-1", "documents": []}],
            }]
        }

    def test_upload_uses_chosen_name_and_remains_admin_only(self):
        data = self._data()
        with tempfile.TemporaryDirectory() as directory, patch.object(gestion_app, "PERSIST_DIR", directory), patch.object(
            gestion_app, "UPLOADS_DIR", os.path.join(directory, "uploads")
        ), patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data"):
            response = self.client.post(
                "/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/private-documents/upload",
                data={
                    "display_name": "  Courrier confidentiel  ",
                    "file": (io.BytesIO(b"private contents"), "courrier.pdf"),
                },
                content_type="multipart/form-data",
            )

            self.assertEqual(response.status_code, 302)
            private_document = data["sessions"][0]["trainees"][0]["private_documents"][0]
            self.assertEqual(private_document["name"], "Courrier confidentiel")
            self.assertTrue(os.path.isfile(gestion_app._detokenize_path(private_document["file"])))
            self.assertFalse(
                gestion_app._token_belongs_to_trainee(
                    data["sessions"][0]["trainees"][0], private_document["file"]
                )
            )
            view_response = self.client.get(
                f"/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/private-documents/{private_document['id']}"
            )
            self.assertEqual(view_response.status_code, 200)
            self.assertEqual(view_response.data, b"private contents")

    def test_upload_requires_a_display_name(self):
        data = self._data()
        with patch.object(gestion_app, "load_data", return_value=data), patch.object(gestion_app, "save_data") as save_data:
            response = self.client.post(
                "/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/private-documents/upload",
                data={"display_name": "", "file": (io.BytesIO(b"contents"), "file.pdf")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        save_data.assert_not_called()
        self.assertNotIn("private_documents", data["sessions"][0]["trainees"][0])


if __name__ == "__main__":
    unittest.main()
