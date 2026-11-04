import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import app as host
import company_signature as signature


class EmployerSigningTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = root / "issued.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((65, 270), "Date et signature")
            pdf.save(self.source)
        self.client = host.app.test_client()
        with self.client.session_transaction() as session:
            session.update(admin_logged_in=True, admin_role="admin")
        self.form = "/admin/sessions/s/stagiaires/t/convention/entreprise"
        self.url = self.form + "/signature"
        self.payload = dict(version=signature.version(self.source), action="send", email="signature@example.org",
                            phone="06 01 02 03 04", first_name="Marie", last_name="Martin")
        trainee = dict(id="t", first_name="Alex", email="student@example.org", phone="0611223344",
                       company_convention={"name":"Entreprise"}, convention_aps_pdf_path=str(self.source))
        self.data = {"sessions":[dict(id="s", training_type="APS", trainees=[trainee])]}
        for name, val in dict(YOUSIGN_CONVENTION_DIR=str(root), YOUSIGN_SIGNED_DIR=str(root / "signed")).items():
            self.enterContext(patch.object(host, name, val))
        self.enterContext(patch.object(host, "load_data", side_effect=lambda **kw:copy.deepcopy(self.data)))
        self.enterContext(patch.object(host, "save_data", side_effect=lambda data:self.data.update(copy.deepcopy(data))))
        self.enterContext(patch.object(host, "_yousign_is_configured", return_value=True))
        self.enterContext(patch.object(host, "_verify_yousign_webhook_signature", return_value=True))
        self.enterContext(patch.object(host.exam_retakes, "notify", return_value=False))
        self.schedule = self.enterContext(patch.object(host, "_schedule_convocation_after_convention_signed"))
        self.status = "draft"
        self.posted = {}
        self.api = self.enterContext(patch.object(host, "_yousign_json", side_effect=self.remote))
        self.download = self.enterContext(patch.object(host, "_download_yousign_signed_pdf",
                                                       return_value=str(self.source)))
        self.student_mail = self.enterContext(patch.object(host, "brevo_send_email", side_effect=AssertionError("unexpected mail")))

    def remote(self, method, path, **kwargs):
        if method == "GET":
            return {"id":"request1", "status":self.status}
        if path.endswith("/activate"):
            self.status = "ongoing"
            return {"status":self.status}
        self.posted[path] = kwargs
        return {"id":"request1" if path == "/signature_requests" else path.split("/")[-1]}

    @property
    def trainee(self):
        return self.data["sessions"][0]["trainees"][0]

    def test_company_only_otp_and_idempotent_webhook(self):
        self.assertEqual(self.client.post(self.url, data=self.payload).status_code, 302)
        settings = self.posted["/signature_requests"]["json"]
        self.assertEqual(settings["delivery_mode"], "email")
        self.assertEqual(settings["reminder_settings"]["max_occurrences"], 3)
        signer = self.posted["/signature_requests/request1/signers"]["json"]
        self.assertEqual(signer["info"]["email"], "signature@example.org")
        self.assertEqual(signer["info"]["phone_number"], "+33601020304")
        self.assertEqual(signer["fields"][0]["page"], 1)
        self.assertEqual(signer["signature_authentication_mode"], "otp_sms")
        self.assertNotIn("signature_link", self.trainee["convention_signature"])
        self.client.post(self.url, data=self.payload)
        self.assertEqual(sum(c.args[0] == "POST" and c.args[1].endswith("/activate") for c in self.api.call_args_list), 1)

        self.status = "done"
        for _ in range(2):
            response = self.client.post("/webhooks/yousign", json={"event_name":"signature_request.done",
                                        "data":{"signature_request":{"id":"request1", "status":"done"}}})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.trainee["convention_status"], "signed")
        self.download.assert_called_once()
        self.schedule.assert_called_once()
        self.student_mail.assert_not_called()

    def test_vae_invites_both_parties_and_waits_for_complete_request(self):
        self.data['sessions'][0]['training_type'] = 'DIRIGEANT VAE'
        self.trainee['last_name'] = 'Dupont'
        self.trainee['company_convention'].update(kind='vae',receivability_date='2026-11-01')
        with patch.object(signature, 'signature_field', return_value=dict(page=1,x=60,y=350,width=180,height=55)):
            self.assertEqual(self.client.post(self.url,data=self.payload).status_code,302)
        signers = [c.kwargs['json'] for c in self.api.call_args_list if c.args[0] == 'POST' and c.args[1].endswith('/signers')]
        self.assertEqual({s['info']['email'] for s in signers}, {'signature@example.org','student@example.org'})
        self.assertEqual(len(signers),2)
        self.assertNotEqual(self.trainee.get('convention_status'), 'signed')
        self.schedule.assert_not_called()

    def test_vae_without_receivability_does_not_send(self):
        self.data['sessions'][0]['training_type'] = 'DIRIGEANT VAE'
        self.trainee['company_convention']['kind'] = 'vae'
        self.client.post(self.url,data=self.payload)
        self.api.assert_not_called()

    def test_send_uses_contact_saved_with_the_pdf(self):
        person = dict(first_name="Anne", last_name="Martin", email="anne@example.org", phone="+33612345678")
        self.trainee["company_convention"]["signer"] = person
        self.client.post(self.url, data={"version": self.payload["version"], "action": "send"})
        signer = self.posted["/signature_requests/request1/signers"]["json"]["info"]
        self.assertEqual(signer["email"], person["email"])
        self.assertEqual(signer["phone_number"], person["phone"])

    def test_existing_signed_contract_keeps_its_signature(self):
        personal = {"status":"done", "signed_pdf_path":"/original.pdf"}
        self.trainee.update(company_convention=None, company_convention_copy={"name":"Entreprise"},
                            company_convention_copy_path=str(self.source), convention_signature=personal)
        self.client.post(self.url, data=self.payload)
        self.status = "done"
        self.client.post(self.url, data=dict(self.payload, action="refresh"))
        self.assertEqual(self.trainee["convention_signature"], personal)
        self.assertEqual(self.trainee["company_signature_requests"][self.payload["version"]]["status"], "done")
        self.schedule.assert_not_called()
        self.assertIn("PDF signé", self.client.get(self.form).get_data(as_text=True))

    def test_stale_pdf_and_missing_contact_never_dispatch(self):
        for data in [dict(self.payload, phone=""), dict(self.payload, version="stale"), dict(self.payload, email="invalid")]:
            self.client.post(self.url, data=data)
        self.api.assert_not_called()
