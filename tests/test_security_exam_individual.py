import copy
import io
import unittest
from unittest.mock import patch

from pypdf import PdfReader
import app as gestion_app


class SecurityExamIndividualTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        self.training = {
            'id': 'S1', 'name': 'APS novembre', 'training_type': 'APS',
            'date_start': '2026-11-03', 'date_end': '2026-12-08', 'exam_date': '2026-12-09',
            'trainees': [{'id': 'T1', 'first_name': 'élodie', 'last_name': 'martin'},
                         {'id': 'T2', 'first_name': 'Alice', 'last_name': 'Durand', 'registration_cancelled': True}],
        }
        self.data = {'sessions': [self.training]}
        self.base = '/api/admin/sessions/S1/aps-exam-dossiers'
        self.pdf = '/admin/sessions/S1/aps-exam-dossiers/candidates/T1/dossier.pdf'
        self.read = patch.object(gestion_app, 'load_data', return_value=self.data)
        self.read.start()
        self.addCleanup(self.read.stop)

    def test_list_links_only_active_candidates_to_their_own_dossier(self):
        result = self.client.get(self.base).get_json()
        self.assertEqual([row['id'] for row in result['candidates']], ['T1'])
        self.assertEqual(result['candidates'][0]['dossier_url'], self.pdf)
        self.assertEqual(result['candidates'][0]['first_name'], 'Élodie')
        self.assertEqual(result['pages'], 7)
        self.assertTrue(result['csrf'])

    def test_pdf_opens_inline_without_bulk_generation_and_downloads_on_request(self):
        before = copy.deepcopy(self.data)
        with patch.object(gestion_app, 'save_data') as save:
            for suffix, disposition in [('', 'inline'), ('?download=1', 'attachment')]:
                response = self.client.get(self.pdf + suffix)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'application/pdf')
                self.assertTrue(response.headers['Content-Disposition'].startswith(disposition))
                self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
                reader = PdfReader(io.BytesIO(response.data))
                self.assertEqual(len(reader.pages), 7)
                self.assertTrue(all('BROUILLON' in page.extract_text() for page in reader.pages))
                self.assertIn('À renseigner', reader.pages[3].extract_text())
                self.assertIn('Élodie', reader.pages[0].extract_text())
                response.close()
            save.assert_not_called()
        self.assertEqual(self.data, before)

    def test_complete_a3p_calendar_uses_current_dates_without_draft(self):
        self.training['training_type'] = self.training['name'] = 'A3P'
        self.training['a3p_exam_dossier'] = {'epi_training_date': '2026-11-18'}
        response = self.client.get(self.pdf.replace('/aps-', '/a3p-'))
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.data))
        self.assertEqual(len(reader.pages), 6)
        self.assertIn('18/11/2026', reader.pages[3].extract_text())
        self.assertFalse(any('BROUILLON' in page.extract_text() for page in reader.pages))
        response.close()

    def test_unknown_cancelled_wrong_session_or_training_cannot_open_pdf(self):
        for url in [self.pdf.replace('/T1/', '/T2/'), self.pdf.replace('/T1/', '/T9/'),
                    self.pdf.replace('/S1/', '/S2/'), self.pdf.replace('/aps-', '/a3p-'),
                    self.pdf.replace('/aps-', '/other-')]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertIn(self.client.get(self.pdf).status_code, (302, 401))

    def test_save_calendar_preserves_archive_and_checks_csrf_dates_and_revision(self):
        archive = {'archive_path': '/previous.zip'}
        self.training['aps_exam_dossier'] = {'generation': archive, 'selected_trainee_ids': ['T1']}
        config = self.client.get(self.base).get_json()
        payload = {key: config[key] for key in ['training_start_date', 'training_end_date', 'exam_date', 'epi_training_date']}
        payload.update(csrf=config['csrf'], revision=config['revision'], epi_training_date='2026-11-18')
        with patch.object(gestion_app, '_atomic_update_data', side_effect=lambda update: update(self.data)):
            self.assertEqual(self.client.post(self.base, json={**payload, 'csrf': 'wrong'}).status_code, 403)
            self.assertEqual(self.client.post(self.base, json={**payload, 'epi_training_date': '2026-02-30'}).status_code, 400)
            self.assertEqual(self.client.post(self.base, json={**payload, 'training_end_date': '2026-01-01'}).status_code, 400)
            self.assertEqual(self.client.post(self.base, json=payload).status_code, 200)
            self.assertEqual(self.client.post(self.base, json=payload).status_code, 409)
        saved = self.training['aps_exam_dossier']
        self.assertEqual(saved['epi_training_date'], '2026-11-18')
        self.assertEqual(saved['generation'], archive)
        self.assertEqual(saved['selected_trainee_ids'], ['T1'])


if __name__ == '__main__':
    unittest.main()
