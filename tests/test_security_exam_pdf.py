import io
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image
from pypdf import PdfReader

import security_exam_pdf as pdf


ROOT = str(Path(__file__).resolve().parents[1])
CONTEXT = {
    'prenom': 'Élodie', 'nom': 'DUPONT-MARTIN', 'nom_complet': 'Élodie DUPONT-MARTIN',
    'code_postal': '83480', 'ville': 'Puget-sur-Argens',
    'date_debut_formation': '03/11/2026', 'date_fin_formation': '08/12/2026',
    'periode_formation': '03/11/2026 au 08/12/2026', 'date_examen': '09/12/2026',
    'date_formation_epi': '18/11/2026', 'date_15_jours_avant_examen': '24/11/2026',
    'date_un_mois_avant_debut_formation': '03/10/2026',
}


class SecurityExamPdfTests(unittest.TestCase):
    def generate(self, training='APS', context=None, photo=''):
        return pdf.dossier(training, {'id': 'TEST'}, context or CONTEXT, ROOT, photo)

    def test_both_dossiers_keep_documents_dates_hours_and_pagination(self):
        for training, pages, hours in [('APS', 7, '175 heures'), ('A3P', 6, '328 heures')]:
            with self.subTest(training=training):
                raw = self.generate(training)
                texts = [p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages]
                self.assertEqual(len(texts), pages)
                self.assertIn(CONTEXT['nom_complet'], texts[1])
                self.assertIn('03/10/2026', texts[1])
                self.assertIn('24/11/2026', texts[2])
                self.assertIn('09/12/2026 à 08h00', texts[2])
                self.assertIn('18/11/2026', texts[3])
                self.assertIn('7 heures', texts[3])
                self.assertIn('08/12/2026', texts[4])
                self.assertIn(hours, texts[1])
                self.assertIn(hours, texts[4])
                self.assertIn('FIN DE FORMATION', texts[4])
                self.assertNotIn('Agrément SSIAP', '\n'.join(texts))
                self.assertTrue(all('{{' not in text for text in texts))

    def test_all_original_assessment_units_and_scenarios_survive(self):
        for training, units, scenarios in [
            ('APS', ['UV02', 'UV03', 'UV04', 'UV05', 'UV06', 'UV07', 'UV08', 'UV09', 'UV11', 'UV10 / 12 / 14'],
             ['Prise en compte du PCS', 'Contrôle d’accès', 'Palpation de sécurité', 'Ronde de surveillance',
              'Levée de doute incendie', 'Levée de doute intrusion', 'Gestion d’un conflit',
              'Gestion d’un conflit dégradé', 'Prise en charge d’une victime']),
            ('A3P', ['UV02', 'UV03', 'UV04', 'UV06', 'UV08'],
             ['Préparation de mission', 'Piétonnage, déplacements', 'Convoi', 'Secourisme tactique d’urgence (STU)']),
        ]:
            reader = PdfReader(io.BytesIO(self.generate(training)))
            text = '\n'.join(page.extract_text() for page in reader.pages[5:])
            for value in units + scenarios + ['Note QCU', 'Acquis', 'acquis', 'Commentaire général du formateur']:
                self.assertIn(value, text)

    def test_long_accented_names_fit_without_losing_characters(self):
        context = {**CONTEXT, 'prenom': 'Éléonore Marie-Alexandrine',
                   'nom': 'DUPONT DE LA ROCHE SAINT-ÉTIENNE'}
        context['nom_complet'] = context['prenom'] + ' ' + context['nom']
        raw = self.generate('A3P', context)
        with fitz.open(stream=raw, filetype='pdf') as document:
            self.assertIn(context['nom'], document[0].get_text())
            for page in document:
                for block in page.get_text('dict')['blocks']:
                    for line in block.get('lines', []):
                        for span in line['spans']:
                            x0, y0, x1, y1 = span['bbox']
                            self.assertGreaterEqual(x0, 0)
                            self.assertGreaterEqual(y0, 0)
                            self.assertLessEqual(x1, page.rect.width)
                            self.assertLessEqual(y1, page.rect.height)
                self.assertNotIn('\ufffd', page.get_text())

    def test_photo_is_used_and_missing_or_invalid_photo_is_graceful(self):
        with tempfile.TemporaryDirectory() as directory:
            photo = Path(directory) / 'portrait.png'
            Image.new('RGB', (100, 140), '#456789').save(photo)
            with fitz.open(stream=self.generate(photo=str(photo)), filetype='pdf') as document:
                self.assertNotIn('à ajouter', document[0].get_text())
            photo.write_text('invalid image')
            with fitz.open(stream=self.generate(photo=str(photo)), filetype='pdf') as document:
                self.assertIn('à ajouter', document[0].get_text())

    def test_validation_rejects_truncated_pdf(self):
        with fitz.open(stream=self.generate('APS'), filetype='pdf') as document:
            document.delete_page(-1)
            with self.assertRaisesRegex(RuntimeError, 'exactement 7 pages'):
                pdf.validate(document.tobytes(), 'APS')


if __name__ == '__main__':
    unittest.main()
