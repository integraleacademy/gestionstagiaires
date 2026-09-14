import io
import re
import unittest
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import pymupdf
from pypdf import PdfReader

from digiforma_attendance import extract_digiforma_attendance, prepare_digiforma_attendance
from digiforma_fixtures import attendance_pdf


class DigiformaAttendanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = Path(__file__).parents[1] / 'templates_word/tableau_suivi_foad_cnaps.docx'
        with ZipFile(template) as archive:
            cls.signature = archive.read('word/media/image3.png')
            cls.stamp = archive.read('word/media/image2.png')

    def test_complete_rebuilt_attendance_keeps_all_courses_and_requested_metrics(self):
        result, metadata = prepare_digiforma_attendance(attendance_pdf(), self.signature, self.stamp)
        reader = PdfReader(io.BytesIO(result))
        text = '\n'.join(page.extract_text() for page in reader.pages)
        self.assertEqual(metadata['processing_version'], 4)
        self.assertEqual(metadata['results_tables_removed'], 8)
        self.assertEqual(len(reader.pages), metadata['page_count'])
        for n in range(1, 9):
            self.assertEqual(text.count(f'P{n}M1'), 1)
            self.assertEqual(text.count(f'Evaluation Parcours {n}'), 1)
        self.assertNotIn('Résultats', text)
        self.assertNotIn('SCORE-', text)
        self.assertNotIn('passage', text)
        self.assertIn('Avancée', text)
        self.assertIn('Première', text)
        self.assertIn('Dernière', text)
        self.assertIn('ALICE MARTIN', text)
        self.assertIn('Clément VAILLANT', reader.pages[-1].extract_text())
        self.assertIn('Tampon Intégrale Academy', reader.pages[-1].extract_text())
        self.assertTrue(metadata['provider_stamped'])
        self.assertNotIn('synthèse Digiforma', text)
        self.assertNotIn('Durée effectivement suivie', text)
        self.assertGreaterEqual(len(list(reader.pages[-1].images)), 3)

    def test_pdf_highlights_the_journal_despite_completed_pedagogical_activities(self):
        result, metadata = prepare_digiforma_attendance(
            attendance_pdf(effective_duration='67 heures et 19 minutes',
                           connection_total='50 heures, 13 minutes et 31 secondes'),
            self.signature, self.stamp,
        )
        with pymupdf.open(stream=result, filetype='pdf') as document:
            text = document[0].get_text()
            self.assertIn('50 h 13 min 31 s', text)
            self.assertIn('Suivi : 81 %', text)
            self.assertIn('Seuil non atteint', text)
            self.assertIn('Durée pédagogique Digiforma : 67 heures et 19 minutes', text)
            self.assertNotIn('100 %\n', text)
            duration_spans = [s for b in document[0].get_text('dict')['blocks'] if 'lines' in b
                              for line in b['lines'] for s in line['spans'] if '50 h 13 min 31 s' in s['text']]
            self.assertGreaterEqual(duration_spans[0]['size'], 24)
        self.assertEqual(metadata['attendance_rate'], 81)

    def test_false_merged_white_rows_preserve_their_own_columns(self):
        with pymupdf.open(stream=attendance_pdf(), filetype='pdf') as source:
            tables = source[1].find_tables().tables
            self.assertTrue(any(any(v is None for v in row) for table in tables for row in table.extract()))
            report = extract_digiforma_attendance(source)
        for course in report['courses']:
            self.assertEqual(len(course['activities']), 2)
            first = course['activities'][0]
            self.assertEqual(first['type'], 'SCORM')
            self.assertEqual(first['duration'], '7 heures')
            self.assertEqual(first['progress'], '100 %')
            self.assertEqual(first['first'].split(), ['07/09/2026', '08h30m01s'])
            self.assertEqual(first['last'].split(), ['08/09/2026', '17h15m02s'])
            self.assertNotIn('SCORE', first['name'])
            self.assertEqual(course['total']['duration'], '7 heures et 45 minutes')

    def test_table_continuation_without_header_keeps_the_same_course(self):
        with pymupdf.open(stream=attendance_pdf(split_course=True), filetype='pdf') as source:
            report = extract_digiforma_attendance(source)
        self.assertEqual(len(report['courses']), 8)
        self.assertEqual([r['name'] for r in report['courses'][0]['activities']],
                         ['P1M1 Prévention des risques', 'Evaluation Parcours 1'])
        self.assertEqual(report['courses'][0]['total']['progress'], '100 %')

    def test_long_module_text_reflows_and_all_glyphs_stay_inside_page_margins(self):
        result, _ = prepare_digiforma_attendance(attendance_pdf(long_label=True), self.signature, self.stamp)
        with pymupdf.open(stream=result, filetype='pdf') as document:
            text = '\n'.join(page.get_text() for page in document)
            self.assertEqual(text.count('FIN-MODULE-LONG'), 1)
            self.assertEqual(re.sub(r'\s+', ' ', text).count('Description détaillée'), 20)
            for page in document:
                for x0, y0, x1, y1, *_ in page.get_text('words'):
                    self.assertGreaterEqual(x0, 39)
                    self.assertLessEqual(x1, page.rect.width - 33)
                    self.assertGreaterEqual(y0, 20)
                    self.assertLessEqual(y1, page.rect.height - 20)
                self.assertIn(f'Page {page.number + 1} / {len(document)}', page.get_text())

    def test_every_connection_survives_pagination_and_headers_repeat(self):
        result, _ = prepare_digiforma_attendance(attendance_pdf(connection_count=70), self.signature, self.stamp)
        reader = PdfReader(io.BytesIO(result))
        texts = [page.extract_text() for page in reader.pages]
        all_text = '\n'.join(texts)
        ips = Counter(re.findall(r'192\.0\.2\.\d+', all_text))
        self.assertEqual(ips, Counter(f'192.0.2.{i+1}' for i in range(70)))
        for text in texts:
            if re.search(r'192\.0\.2\.\d+', text):
                for label in ('Connexion', 'Déconnexion', 'Durée de connexion', 'Adresse IP'):
                    self.assertIn(label, text)
        self.assertIn('DURÉE TOTALE DE CONNEXION - JOURNAL', all_text)
        self.assertIn('Clément VAILLANT', texts[-1])

    def test_missing_module_is_rejected_instead_of_silently_omitted(self):
        with pymupdf.open(stream=attendance_pdf(), filetype='pdf') as source:
            source[0].insert_text((40, 700), 'P99M99 Activité hors du tableau', fontsize=10)
            malformed = source.tobytes()
        with self.assertRaisesRegex(ValueError, 'modules Digiforma'):
            prepare_digiforma_attendance(malformed, self.signature, self.stamp)

    def test_missing_connection_table_is_rejected_instead_of_losing_entries(self):
        with pymupdf.open(stream=attendance_pdf(), filetype='pdf') as source:
            source[-1].insert_text((40, 120), 'Le 09/09/2026 à 01h02m03s Le 09/09/2026 à 02h03m04s', fontsize=8)
            malformed = source.tobytes()
        with self.assertRaisesRegex(ValueError, 'journal de connexions'):
            prepare_digiforma_attendance(malformed, self.signature, self.stamp)

    def test_unknown_results_header_is_rejected(self):
        with pymupdf.open(stream=attendance_pdf(), filetype='pdf') as source:
            source[0].insert_text((40, 680), 'Résultats', fontsize=10)
            malformed = source.tobytes()
        with self.assertRaisesRegex(ValueError, 'tous les tableaux'):
            prepare_digiforma_attendance(malformed, self.signature, self.stamp)


if __name__ == '__main__':
    unittest.main()
