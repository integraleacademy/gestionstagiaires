import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from pypdf import PdfReader
import app as gestion_app


class SecurityExamDossierRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        self.payload = {
            'training_start_date': '2026-11-03', 'training_end_date': '2026-12-08',
            'exam_date': '2026-12-09', 'epi_training_date': '2026-11-18',
            'selected_trainee_ids': ['T1', 'T2'],
        }

    def test_generation_keeps_namesakes_separate_and_archives_all_pages(self):
        for training, pages in [('APS', 7), ('A3P', 6)]:
            with self.subTest(training=training), tempfile.TemporaryDirectory() as directory:
                session = {'id': 'S1', 'training_type': training, 'name': training,
                           'trainees': [{'id': tid, 'first_name': 'élodie', 'last_name': 'martin'}
                                        for tid in ['T1', 'T2']]}
                endpoint = f'/api/admin/sessions/S1/{training.lower()}-exam-dossiers'
                with patch.object(gestion_app, 'load_data', return_value={'sessions': [session]}), \
                     patch.object(gestion_app, 'save_data'), \
                     patch.object(gestion_app, training + '_EXAM_DOSSIER_DIR', directory):
                    response = self.client.post(endpoint + '/generate', json=self.payload)
                    self.assertEqual(response.status_code, 200, response.get_json())
                    self.assertEqual(response.json['candidate_count'], 2)
                    download = self.client.get(response.json['download_url'])
                    with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
                        self.assertEqual(len(archive.namelist()), 3)
                        self.assertEqual(len(set(archive.namelist())), 3)
                        for name in archive.namelist():
                            reader = PdfReader(io.BytesIO(archive.read(name)))
                            self.assertEqual(len(reader.pages), pages * (2 if name.startswith('Tous') else 1))
                            self.assertIn('Élodie', reader.pages[0].extract_text())
                    download.close()
                    config = self.client.get(endpoint).json
                    self.assertTrue(config['generation']['current_style'])
                    session[training.lower() + '_exam_dossier']['generation'].pop('style_version')
                    config = self.client.get(endpoint).json
                    self.assertTrue(config['generation']['available'])
                    self.assertFalse(config['generation']['current_style'])

    def test_failed_generation_preserves_previous_archive_and_cleans_partial_files(self):
        with tempfile.TemporaryDirectory() as directory:
            old_archive = Path(directory) / 'old.zip'
            old_archive.write_bytes(b'previous generation')
            session = {'id': 'S1', 'name': 'APS', 'training_type': 'APS',
                       'trainees': [{'id': 'T1', 'first_name': 'Alice', 'last_name': 'Martin'}],
                       'aps_exam_dossier': {'generation': {'archive_path': str(old_archive)}}}
            with patch.object(gestion_app, 'load_data', return_value={'sessions': [session]}), \
                 patch.object(gestion_app, 'save_data') as save, \
                 patch.object(gestion_app, 'APS_EXAM_DOSSIER_DIR', directory), \
                 patch.object(gestion_app.security_exam_pdf, 'dossier', side_effect=RuntimeError('test failure')):
                result = self.client.post('/api/admin/sessions/S1/aps-exam-dossiers/generate', json=self.payload)
            self.assertEqual(result.status_code, 500)
            save.assert_not_called()
            self.assertEqual(old_archive.read_bytes(), b'previous generation')
            self.assertEqual(list((Path(directory) / 'S1').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
