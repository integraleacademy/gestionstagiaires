import datetime
import io
import os
import tempfile
import unittest
from werkzeug.datastructures import FileStorage

import app as gestion_app


class ScotiaAddedDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.original_persist_dir = gestion_app.PERSIST_DIR
        self.original_uploads_dir = gestion_app.UPLOADS_DIR
        self.tmpdir = tempfile.TemporaryDirectory()
        gestion_app.PERSIST_DIR = self.tmpdir.name
        gestion_app.UPLOADS_DIR = os.path.join(self.tmpdir.name, "uploads")
        os.makedirs(gestion_app.UPLOADS_DIR, exist_ok=True)

    def tearDown(self):
        gestion_app.PERSIST_DIR = self.original_persist_dir
        gestion_app.UPLOADS_DIR = self.original_uploads_dir
        self.tmpdir.cleanup()

    def _file(self, filename="document.pdf"):
        return FileStorage(stream=io.BytesIO(b"pdf"), filename=filename)

    def test_append_scotia_added_documents_groups_files_by_current_date(self):
        trainee = {}

        stored_count = gestion_app._append_scotia_added_documents("S1", "T1", trainee, [self._file()])

        today_label = datetime.date.today().strftime("%d/%m/%Y")
        self.assertEqual(stored_count, 1)
        self.assertEqual(len(trainee["scotia_added_documents"]), 1)
        self.assertEqual(trainee["scotia_added_documents"][0]["date"], today_label)
        self.assertEqual(len(trainee["scotia_added_documents"][0]["files"]), 1)
        self.assertTrue(gestion_app._scotia_added_document_token_exists(trainee, trainee["scotia_added_documents"][0]["files"][0]))

    def test_remove_scotia_added_document_deletes_empty_group(self):
        trainee = {}
        gestion_app._append_scotia_added_documents("S1", "T1", trainee, [self._file()])
        token = trainee["scotia_added_documents"][0]["files"][0]

        removed = gestion_app._remove_scotia_added_document_token(trainee, token)

        self.assertTrue(removed)
        self.assertEqual(trainee["scotia_added_documents"], [])


if __name__ == "__main__":
    unittest.main()
