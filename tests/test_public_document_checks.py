import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter
from werkzeug.datastructures import FileStorage

import app as gestion
import public_document_checks as checks
import document_visual_checks as visual


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def photo_bytes(color='gray'):
    stream = io.BytesIO()
    Image.new('RGB', (600, 800), color).save(stream, format='PNG')
    return stream.getvalue()


def observations(**changes):
    fields = {
        'document_type': 'portrait', 'confidence': 'high', 'document_date': None,
        'date_kind': 'uncertain', 'date_confidence': 'low', 'readability': 'clear',
        'all_fields_legible': True, 'problems': [],
        'photo_criteria': {key: 'pass' for key in visual.PHOTO_CRITERIA},
        'photo_portrait_count': 'one', 'photo_layout': 'single_photo',
        'signature': 'not_applicable', 'signature_confidence': 'low',
        'address_kind': 'uncertain', 'address_kind_confidence': 'low',
        'identity_document': 'not_applicable', 'identity_sides': [], 'side_confidence': 'low',
        'identity_checks': {key: 'not_applicable' for key in visual.IDENTITY_CHECKS},
    }
    fields.update(changes)
    return fields


def side(kind='identity_card', sides=None):
    return {'status': 'success', 'title': 'Fichier lisible', 'message': '',
            'identity_evidence': [{'type': kind, 'sides': sides or ['front'], 'confidence': 'high'}]}


class DocumentRulesTests(unittest.TestCase):
    def test_spoofed_extensions_corrupted_and_empty_files_are_rejected(self):
        for data, name, accept in [(b'', 'x.pdf', 'application/pdf'),
                                   (b'%PDF-invalid', 'x.pdf', 'application/pdf'),
                                   (photo_bytes(), 'x.pdf', 'application/pdf'),
                                   (b'<svg></svg>', 'x.png', 'image/png'),
                                   (photo_bytes(), 'x.jpg', 'image/jpeg'),
                                   (pdf_bytes(), 'x.exe', 'application/pdf')]:
            self.assertEqual(checks.validate_file(data, name, accept, 25*1024*1024)['status'], 'invalid')

    def test_valid_bytes_are_accepted_even_without_browser_mime(self):
        self.assertIsNone(checks.validate_file(pdf_bytes(), 'X.PDF', 'application/pdf', 25*1024*1024))
        self.assertIsNone(checks.validate_file(photo_bytes(), 'X.PNG', 'image/jpeg,image/png', 25*1024*1024))

    def test_photo_sheet_multiple_portraits_and_uncertainty_never_turn_green(self):
        for changes in [{'photo_portrait_count': 'multiple'}, {'photo_layout': 'photo_sheet'},
                        {'photo_layout': 'collage'}, {'photo_layout': 'identity_document'},
                        {'photo_portrait_count': 'uncertain'}, {'confidence': 'medium'}]:
            self.assertNotEqual(visual.advisory(observations(**changes), 'identity_photo', date.today())['status'], 'success')
        for criterion in visual.PHOTO_CRITERIA:
            fields = observations()
            fields['photo_criteria'][criterion] = 'fail'
            self.assertEqual(visual.advisory(fields, 'identity_photo', date.today())['status'], 'warning')
        self.assertEqual(visual.advisory(observations(), 'identity_photo', date.today())['status'], 'success')

    def test_identity_missing_duplicated_and_mixed_sides(self):
        for results in [[side()], [side(), side()], [side(), side('residence_permit', ['back'])]]:
            self.assertEqual(checks.summarize(results, 'id')['status'], 'warning')
        for results in [[side(sides=['front', 'back'])], [side(), side(sides=['back'])],
                        [side('passport', ['passport_biodata'])]]:
            self.assertEqual(checks.summarize(results, 'id')['status'], 'success')

    def test_glare_unreadable_and_cut_identity_stay_advisory(self):
        fields = observations(document_type='identity', identity_document='identity_card', identity_sides=['front'],
                              side_confidence='high', identity_checks={key: 'pass' for key in visual.IDENTITY_CHECKS})
        self.assertEqual(visual.advisory(fields, 'identity', date.today())['status'], 'success')
        for defect in ('glare', 'cropped', 'unreadable_fields'):
            self.assertNotEqual(visual.advisory({**fields, 'problems': [defect]}, 'identity', date.today())['status'], 'success')

    def test_identity_pages_are_individually_examined(self):
        fields = observations(document_type='identity', identity_document='identity_card', identity_sides=['front'],
                              side_confidence='high', identity_checks={key: 'pass' for key in visual.IDENTITY_CHECKS})
        with patch.object(visual, 'call_openai', side_effect=[fields, {**fields, 'identity_sides': ['back']}]) as provider:
            result = visual.analyze_images(['front-image', 'back-image'], 'identity', 'test-key', date.today())
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(checks.summarize([result], 'id')['status'], 'success')

    def test_other_document_types_use_structured_advisory_results(self):
        for changes, expected in [({}, 'success'), ({'expected_type': 'no'}, 'warning'),
                                  ({'readability': 'poor'}, 'warning'), ({'whole_document': 'no'}, 'warning'),
                                  ({'expected_type': 'uncertain'}, 'unknown')]:
            fields = {'expected_type': 'yes', 'readability': 'clear', 'whole_document': 'yes', 'signature': 'not_applicable', **changes}
            body = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(fields)}]}]}
            with patch.object(checks, 'urlopen', return_value=io.BytesIO(json.dumps(body).encode())) as provider:
                result = checks.generic_analysis(['image-bytes'], 'Permis de conduire', 'synthetic-key')
            self.assertEqual(result['status'], expected)
            sent = json.loads(provider.call_args.args[0].data)
            self.assertFalse(sent['store'])
            self.assertNotIn('image-bytes', json.dumps(result))


class UploadWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = gestion.app.test_client()
        self.trainee = {'id': 'SYNTHETIC-T1', 'public_token': 'synthetic-token', 'first_name': 'Essai', 'last_name': 'Fictif', 'documents': []}
        self.training = {'id': 'SYNTHETIC-S1', 'training_type': 'APS', 'trainees': [self.trainee]}
        self.data = {'sessions': [self.training]}
        gestion.ensure_documents_schema_for_trainee(self.trainee, 'APS')
        self.patches = [patch.object(gestion, 'load_data', return_value=self.data),
                        patch.object(gestion, 'save_data'), patch.object(gestion, 'PERSIST_DIR', self.tmp.name),
                        patch.object(gestion, 'UPLOADS_DIR', self.tmp.name), patch.object(gestion, 'brevo_send_email'),
                        patch.object(gestion, 'get_partner_storage_path',
                                     side_effect=lambda partner_id, *parts: os.path.join(self.tmp.name, 'partners', partner_id, *parts))]
        self.started = [p.start() for p in self.patches]
        self.save = self.started[1]
        self.mail = self.started[4]
        with self.client.session_transaction() as session:
            session['public_auth_synthetic-token'] = True
            session['trainee_document_check_token'] = 'synthetic-csrf'
        self.good = {'status': 'success', 'title': 'Photo : c’est bon !', 'message': '', 'photo_check_version': 2}

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
        with visual._cache_lock:
            visual._cache.clear()

    def post(self, operation='check', key='photo', data=None, receipt='', name='photo.png', csrf=True):
        payload = {'files': (io.BytesIO(data if data is not None else photo_bytes()), name),
                   'document_check_receipt': receipt}
        if csrf:
            payload['document_check_token'] = 'synthetic-csrf'
        return self.client.post(f'/espace/synthetic-token/documents/{key}/{operation}', data=payload,
                                content_type='multipart/form-data')

    def test_preview_is_authenticated_csrf_protected_and_read_only(self):
        with patch.object(checks, 'analyze_file', return_value=self.good) as analyze:
            self.assertEqual(self.post(csrf=False).status_code, 403)
            response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['summary']['status'], 'success')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.save.assert_not_called()
            self.mail.assert_not_called()
            self.assertEqual(analyze.call_count, 1)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.post().status_code, 401)

    def test_public_page_renders_modal_and_csrf_for_each_upload(self):
        self.trainee['public_has_logged_in'] = True
        response = self.client.get('/espace/synthetic-token')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="traineeDocumentCheck"', body)
        self.assertIn('/espace/synthetic-token/documents/photo/check', body)
        self.assertIn('value="synthetic-csrf"', body)
        self.assertNotIn('function confirmPhotoUpload', body)

    def test_cross_origin_cannot_use_the_analysis_service(self):
        response = self.client.post('/espace/synthetic-token/documents/photo/check',
                                    headers={'Origin': 'https://attacker.invalid', 'X-Document-Check-Token': 'synthetic-csrf'})
        self.assertEqual(response.status_code, 403)

    def test_unsigned_client_success_is_never_trusted_and_upload_remains_to_review(self):
        with patch.object(checks, 'analyze_file', return_value=checks.unknown('not_configured')) as analyze:
            response = self.post('upload', receipt='forged-success')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(analyze.call_count, 1)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'photo')
        self.assertEqual(target['status'], 'A CONTRÔLER')
        self.assertEqual(target['auto_check_summary']['status'], 'unknown')
        self.mail.assert_not_called()

    def test_signed_preview_is_stored_with_exact_file_without_second_ai_call(self):
        with patch.object(checks, 'analyze_file', return_value=self.good) as analyze:
            preview = self.post().json
            response = self.post('upload', receipt=preview['receipt'])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(analyze.call_count, 1)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'photo')
        self.assertEqual(target['status'], 'A CONTRÔLER')
        self.assertEqual(target['auto_checks'][target['file']]['status'], 'success')
        self.assertEqual(target['auto_check_summary']['files'], target['files'])

    def test_changed_file_invalidates_receipt(self):
        with patch.object(checks, 'analyze_file', return_value=self.good) as analyze:
            receipt = self.post().json['receipt']
            self.post('upload', data=photo_bytes('red'), receipt=receipt)
        self.assertEqual(analyze.call_count, 2)

    def test_receipt_cannot_cross_trainee_or_session(self):
        with gestion.app.test_request_context('/'):
            files = [photo_bytes()]
            receipt = checks.make_receipt(files, 'photo', 'one-trainee', [], {'results': []})
            self.assertIsNone(checks.read_receipt(receipt, files, 'photo', 'another-trainee', []))
            from flask import session
            session['trainee_document_check_token'] = 'different-session'
            self.assertIsNone(checks.read_receipt(receipt, files, 'photo', 'one-trainee', []))

    def test_invalid_file_does_not_replace_an_existing_document(self):
        target = next(d for d in self.trainee['documents'] if d['key'] == 'photo')
        target.update(file='old-file', files=['old-file'], status='NON CONFORME')
        before = copy.deepcopy(target)
        response = self.post('upload', data=b'<svg></svg>')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(target, before)
        self.save.assert_not_called()
        with self.client.session_transaction() as session:
            self.assertEqual(session['document_upload_error']['status'], 'invalid')

    def test_replacement_preserves_administrative_review_and_discards_old_analysis(self):
        target = next(d for d in self.trainee['documents'] if d['key'] == 'photo')
        target.update(file='old-file', files=['old-file'], status='NON CONFORME', auto_checks={'old-file': self.good})
        with patch.object(checks, 'analyze_file', return_value=self.good):
            self.post('upload')
        self.assertNotIn('old-file', target['files'])
        self.assertNotIn('old-file', target['auto_checks'])
        self.assertEqual(target['status'], 'A CONTRÔLER')

    def test_two_identity_files_are_saved_with_the_combined_warning(self):
        with patch.object(checks, 'analyze_file', return_value=side()):
            response = self.client.post('/espace/synthetic-token/documents/id/upload', data={
                'files': [(io.BytesIO(pdf_bytes()), 'recto.pdf'), (io.BytesIO(pdf_bytes()), 'recto-copie.pdf')],
                'document_check_token': 'synthetic-csrf'}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        self.assertEqual(len(target['files']), 2)
        self.assertEqual(target['auto_check_summary']['status'], 'warning')
        self.assertEqual(target['status'], 'A CONTRÔLER')

    def test_unavailable_analysis_never_labels_a_photo_as_valid(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            response = self.post()
        self.assertEqual(response.json['summary']['status'], 'unknown')
        self.assertEqual(response.json['summary']['reason_code'], 'not_configured')
        self.assertTrue(response.json['receipt'])

    def test_non_required_document_and_three_identity_files_are_rejected(self):
        self.assertEqual(self.post(key='arbitrary').status_code, 404)
        response = self.client.post('/espace/synthetic-token/documents/id/check', data={
            'files': [(io.BytesIO(pdf_bytes()), f'{i}.pdf') for i in range(3)],
            'document_check_token': 'synthetic-csrf'}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 422)
        self.save.assert_not_called()

    def test_photo_of_document_is_checked_and_stored_as_the_same_pdf(self):
        with patch.object(checks, 'analyze_file', return_value=side(sides=['front', 'back'])) as analyze:
            preview = self.post(key='id', name='carte.png').json
            analyzed_pdf = analyze.call_args.args[0]
            self.assertTrue(analyzed_pdf.startswith(b'%PDF-'))
            response = self.post('upload', key='id', name='carte.png', receipt=preview['receipt'])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(analyze.call_count, 1)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        self.assertTrue(target['file'].endswith('.pdf'))
        with open(gestion._detokenize_path(target['file']), 'rb') as saved:
            self.assertEqual(saved.read(), analyzed_pdf)
        self.assertEqual(target['status'], 'A CONTRÔLER')

    def test_upload_without_preview_converts_before_analysis(self):
        with patch.object(checks, 'analyze_file', return_value=side()) as analyze:
            response = self.post('upload', key='id', name='scan.png')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(analyze.call_args.args[0].startswith(b'%PDF-'))
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        self.assertTrue(target['file'].endswith('.pdf'))

    def test_identity_photo_remains_an_image(self):
        original = photo_bytes()
        with patch.object(checks, 'analyze_file', return_value=self.good):
            self.post('upload', data=original, name='portrait.png')
        target = next(d for d in self.trainee['documents'] if d['key'] == 'photo')
        self.assertTrue(target['file'].endswith('.png'))
        with open(gestion._detokenize_path(target['file']), 'rb') as saved:
            self.assertEqual(saved.read(), original)

    def test_failed_office_conversion_does_not_replace_previous_document(self):
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        target.update(file='old.pdf', files=['old.pdf'], status='NON CONFORME')
        before = copy.deepcopy(target)
        with patch.object(checks, 'convert_upload', side_effect=checks.ConversionError('Conversion impossible.')):
            response = self.post('upload', key='id', data=b'office', name='document.docx')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(target, before)
        self.save.assert_not_called()
        self.mail.assert_not_called()

    def test_changed_conversion_invalidates_precheck_receipt(self):
        first = pdf_bytes()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        output = io.BytesIO()
        writer.write(output)
        with patch.object(checks, 'convert_upload', side_effect=[(first, 'scan.pdf'), (output.getvalue(), 'scan.pdf')]), \
             patch.object(checks, 'analyze_file', return_value=side()) as analyze:
            receipt = self.post(key='id', name='scan.docx').json['receipt']
            self.post('upload', key='id', name='scan.docx', receipt=receipt)
        self.assertEqual(analyze.call_count, 2)

    def test_two_image_sides_become_two_pdfs_without_losing_a_side(self):
        with patch.object(checks, 'analyze_file', side_effect=[side(), side(sides=['back'])]):
            response = self.client.post('/espace/synthetic-token/documents/id/upload', data={
                'files': [(io.BytesIO(photo_bytes('red')), 'recto.png'), (io.BytesIO(photo_bytes('blue')), 'verso.png')],
                'document_check_token': 'synthetic-csrf'}, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        self.assertEqual(len(target['files']), 2)
        self.assertTrue(all(name.endswith('.pdf') for name in target['files']))
        self.assertEqual(target['auto_check_summary']['status'], 'success')

    def test_admin_upload_also_stores_a_converted_pdf(self):
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        response = self.client.post('/admin/sessions/SYNTHETIC-S1/stagiaires/SYNTHETIC-T1/documents/id/upload',
                                    data={'file': (io.BytesIO(photo_bytes()), 'scan.png')},
                                    content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        self.assertTrue(target['file'].endswith('.pdf'))
        with open(gestion._detokenize_path(target['file']), 'rb') as saved:
            self.assertTrue(saved.read().startswith(b'%PDF-'))

    def test_admin_conversion_error_is_visible_and_preserves_existing_file(self):
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'
        target = next(d for d in self.trainee['documents'] if d['key'] == 'id')
        target.update(file='old.pdf', files=['old.pdf'], status='CONFORME')
        response = self.client.post('/admin/sessions/SYNTHETIC-S1/stagiaires/SYNTHETIC-T1/documents/id/upload',
                                    data={'file': (io.BytesIO(b'not a document'), 'file.exe')},
                                    content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(target['files'], ['old.pdf'])
        self.save.assert_not_called()
        with self.client.session_transaction() as session:
            self.assertEqual(session['_flashes'][0][0], 'document_conversion_error')


if __name__ == '__main__':
    unittest.main()
