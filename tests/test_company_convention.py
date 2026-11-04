import copy
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import app as gestion
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
FIELDS = dict(name="Société Exemple", address="1 rue du Centre, 83480 Puget-sur-Argens",
              first_name="Anne", last_name="Martin", role="gérante", email="anne@example.org", phone="0611223344",
              representative="Anne Martin, gérante", payment="Virement à réception.", price="1700", remote_rate="35,43")


class EmployerAgreementTests(unittest.TestCase):
    def test_vae_keeps_its_programme_and_adds_company_and_beneficiary(self):
        path = ROOT / 'templates_word/conventionvae.docx'
        original = path.read_bytes()
        doc = gestion.company_convention.build_document(path, dict(FIELDS, receivability_date='2026-11-01'), {
            'nom_complet':'MEDDAHI Tarik', 'date_jour':'04/11/2026', 'lieu_formation':'Puget'})
        content = '\n'.join(p.text for p in gestion._iter_docx_paragraphs(doc))
        for text in ('Société Exemple', 'MEDDAHI Tarik', 'Phase 5', 'Article 9',
                     'Signature du bénéficiaire', 'Signature de l’entreprise', '2026-11-01'):
            self.assertIn(text, content)
        for text in ('{{s1|', 'rétractation', 'Reste à charge personnel', 'Engagement du stagiaire'):
            self.assertNotIn(text, content)
        self.assertEqual(path.read_bytes(), original)

    def test_vae_company_route_and_preparation_accept_specific_model(self):
        self.data['sessions'][0]['training_type'] = 'DIRIGEANT VAE'
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertIn('bénéficiaire', self.client.get(self.url).text)
        self.assertEqual(self.client.post(self.url, data=dict(FIELDS, action='preview',receivability_date='bad')).status_code, 400)
        response = self.client.post(self.url, data=dict(FIELDS, action='prepare',receivability_date='2026-11-01'))
        self.assertEqual(response.status_code, 302)
        company = self.data['sessions'][0]['trainees'][0]['company_convention']
        self.assertEqual(company['kind'], 'vae')
        self.assertEqual(company['receivability_date'], '2026-11-01')
        args = gestion.company_convention.render.call_args.args
        self.assertEqual(Path(args[0]).name, 'conventionvae.docx')

    def test_business_clauses_replace_personal_ones_in_each_model(self):
        for path in (ROOT / "templates_word").glob("convention*.docx"):
            if path.stem in {"conventionvae", "conventionafc"}:
                continue
            with self.subTest(model=path.name):
                doc = gestion.company_convention.build_document(path, FIELDS, {
                    "nom_complet": "TEST Alex", "date_jour": "03/11/2026", "lieu_formation": "Puget"})
                content = "\n".join(p.text for p in gestion._iter_docx_paragraphs(doc))
                for word in ("Société Exemple", "TEST Alex", "Anne Martin", "L. 6354-1", "35,43 %"):
                    self.assertIn(word, content)
                for word in ("{{s1|", "rétractation", "Pour le stagiaire", "restent dues par le stagiaire"):
                    self.assertNotIn(word, content)
                self.assertEqual(doc.sections[0].header._element.xml, Document(path).sections[0].header._element.xml)

    def setUp(self):
        self.client = gestion.app.test_client()
        with self.client.session_transaction() as session:
            session.update(admin_logged_in=True, admin_role="admin")
        self.trainee = dict(id="T1", first_name="Alex", last_name="Test", training_price="1700")
        self.data = {"sessions": [dict(id="S1", training_type="APS", trainees=[self.trainee])]}
        self.url = "/admin/sessions/S1/stagiaires/T1/convention/entreprise"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(gestion, "YOUSIGN_CONVENTION_DIR", directory.name))
        self.enterContext(patch.object(gestion, "_find_libreoffice_binary", return_value="soffice"))
        self.enterContext(patch.object(gestion.company_convention, "render",
                                       side_effect=lambda *args, **kwargs: args[-1].write(b"%PDF-preview")))
        self.enterContext(patch.object(gestion, "load_data", side_effect=lambda **kw: copy.deepcopy(self.data)))
        self.save = self.enterContext(patch.object(gestion, "save_data", side_effect=self.data.update))

    def test_choice_preview_generate_import_and_individual_guard(self):
        preview = self.client.post(self.url, data=dict(FIELDS, action="preview"))
        self.assertEqual(preview.data, b"%PDF-preview")
        self.save.assert_not_called()
        response = self.client.post(self.url, data=FIELDS)
        self.assertEqual(self.client.get(response.location).data, b"%PDF-preview")
        self.assertEqual(self.client.post("/api/sessions/S1/stagiaires/T1/convention/signature/create",
                                          json={}).status_code, 409)
        with patch.object(gestion, "_schedule_convocation_after_convention_signed") as schedule, \
                patch.object(gestion, "_store_signed_convention_pdf_bytes", return_value="/tmp/signed.pdf"):
            result = self.client.post(self.url.replace("/entreprise", "/signed-pdf/upload"),
                                      data={"signed_pdf": (BytesIO(b"%PDF-copy"), "signed.pdf")})
            self.assertEqual(result.status_code, 302)
            self.assertEqual(self.data["sessions"][0]["trainees"][0]["convention_status"], "signed")
            schedule.assert_called_once()

    def test_single_form_collects_the_signer_before_creating_the_pdf(self):
        html = self.client.get(self.url).get_data(as_text=True)
        self.assertEqual(html.count('<form method="post"'), 1)
        for key in ("first_name", "last_name", "role", "email", "phone"):
            self.assertLess(html.index(f'name="{key}"'), html.index('>Générer le PDF'))
        for bad in ({"email": "invalid"}, {"phone": ""}, {"first_name": ""}):
            response = self.client.post(self.url, data=dict(FIELDS, action="prepare") | bad)
            self.assertEqual(response.status_code, 400)
            self.assertIn("Société Exemple", response.get_data(as_text=True))
        gestion.company_convention.render.assert_not_called()
        self.save.assert_not_called()
        response = self.client.post(self.url, data=dict(FIELDS, action="prepare"))
        receipt = self.client.get(response.location).get_data(as_text=True)
        self.assertIn("Envoyer à l’entreprise pour signature", receipt)
        self.assertNotIn('name="email"', receipt)
        self.assertIn(FIELDS["email"], receipt)
        company = self.data["sessions"][0]["trainees"][0]["company_convention"]
        self.assertEqual(company["representative"], "Anne Martin, gérante")
        self.assertEqual(company["signer"]["phone"], "+33611223344")
        edit = self.client.get(self.url + "?modifier=1").get_data(as_text=True)
        self.assertIn('value="anne@example.org"', edit)

    def test_signed_record_keeps_original_and_stores_separate_pdf(self):
        self.trainee["convention_legacy_signed"] = True
        response = self.client.post(self.url, data=FIELDS)
        self.assertIn("company_copy=1", response.location)
        self.assertEqual(self.client.get(response.location).data, b"%PDF-preview")
        current = self.data["sessions"][0]["trainees"][0]
        self.assertTrue(current["convention_legacy_signed"])
        self.assertNotIn("company_convention", current)

    def test_pending_individual_signature_requires_explicit_replacement(self):
        self.trainee["convention_signature"] = dict(status="ongoing", signature_request_id="req")
        with patch.object(gestion, "_yousign_is_configured", return_value=True), \
                patch.object(gestion, "_yousign_json", return_value={}) as yousign:
            self.assertEqual(self.client.post(self.url, data=FIELDS).status_code, 409)
            yousign.assert_not_called()
            self.assertEqual(self.client.post(self.url, data=dict(FIELDS, replace_pending="1")).status_code, 302)
            yousign.assert_called_once()
            self.assertEqual(self.client.post(self.url, data=dict(action="individual")).status_code, 302)
            self.assertNotIn("company_convention", self.data["sessions"][0]["trainees"][0])
