from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from pypdf import PdfReader

import app as gestion_app


class CertificateRealizationTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_role"] = "admin"

    @staticmethod
    def _session(training_type="APS", name="Session APS septembre"):
        return {
            "id": "SESSION-1",
            "name": name,
            "training_type": training_type,
            "date_start": "2026-09-07",
            "date_end": "2026-10-09",
            "trainees": [{
                "id": "TRAINEE-1",
                "first_name": "Arthur",
                "last_name": "Sanseverino",
                "company_name": "Entreprise Exemple",
            }],
        }

    def test_context_uses_training_data_and_known_aps_duration(self):
        session = self._session()
        context = gestion_app._build_certificate_realization_context(session, session["trainees"][0])

        self.assertEqual(context["signatory"], "Clément VAILLANT")
        self.assertEqual(context["provider"], "Intégrale Sécurité Formations")
        self.assertEqual(context["beneficiary"], "Arthur SANSEVERINO")
        self.assertEqual(context["employer"], "Entreprise Exemple")
        self.assertEqual(context["training_title"], "Agent de Prévention et de Sécurité (APS)")
        self.assertEqual(context["nature"], "training")
        self.assertEqual(context["start_date"], "07/09/2026")
        self.assertEqual(context["end_date"], "09/10/2026")
        self.assertEqual(context["duration"], "175 heures")

    def test_vae_is_checked_and_uses_vae_duration(self):
        session = self._session("DIRIGEANT VAE", "VAE DESP")
        context = gestion_app._build_certificate_realization_context(session, session["trainees"][0])

        self.assertEqual(context["nature"], "vae")
        self.assertEqual(context["duration"], "35 heures")
        self.assertIn("VAE", context["training_title"])

    def test_context_requires_an_employer_name(self):
        for company_name in ("", "Non renseignée"):
            with self.subTest(company_name=company_name):
                session = self._session()
                session["trainees"][0]["company_name"] = company_name

                with self.assertRaisesRegex(ValueError, "nom de l’entreprise manquant"):
                    gestion_app._build_certificate_realization_context(session, session["trainees"][0])

    def test_pdf_keeps_template_and_adds_all_values(self):
        session = self._session()
        context = gestion_app._build_certificate_realization_context(session, session["trainees"][0])

        certificate = gestion_app._build_certificate_realization_pdf(context)
        reader = PdfReader(certificate)

        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        for expected in (
            "Clément VAILLANT",
            "Intégrale Sécurité Formations",
            "Arthur SANSEVERINO",
            "Entreprise Exemple",
            "Agent de Prévention et de Sécurité (APS)",
            "07/09/2026",
            "09/10/2026",
            "175 heures",
            "Puget-sur-Argens",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_admin_button_opens_filled_pdf_route(self):
        session = self._session()
        data = {"sessions": [session]}
        with patch.object(gestion_app, "load_data", return_value=data):
            response = self.client.get(
                "/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/certificat-realisation"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn(
            "certificat-realisation-sanseverino-arthur.pdf",
            response.headers["Content-Disposition"],
        )
        text = PdfReader(BytesIO(response.data)).pages[0].extract_text()
        self.assertIn("Arthur SANSEVERINO", text)

        template = Path("templates/admin_trainee.html").read_text(encoding="utf-8")
        self.assertIn("Certificat de réalisation", template)
        self.assertIn("admin_trainee_certificate_realization", template)

    def test_admin_route_asks_for_company_before_generating(self):
        session = self._session("DIRIGEANT INITIAL", "DESP été 2026")
        session["trainees"][0].pop("company_name")
        data = {"sessions": [session]}

        with patch.object(gestion_app, "load_data", return_value=data):
            prompt_response = self.client.get(
                "/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/certificat-realisation"
            )
            pdf_response = self.client.post(
                "/admin/sessions/SESSION-1/stagiaires/TRAINEE-1/certificat-realisation",
                data={"company_name": "Société Sécurité Méditerranée"},
            )

        self.assertEqual(prompt_response.status_code, 200)
        self.assertEqual(prompt_response.mimetype, "text/html")
        self.assertIn("Nom de l’entreprise manquant", prompt_response.get_data(as_text=True))
        self.assertNotIn("Non renseignée", prompt_response.get_data(as_text=True))

        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        text = PdfReader(BytesIO(pdf_response.data)).pages[0].extract_text()
        self.assertIn("Société Sécurité Méditerranée", text)
        self.assertNotIn("Non renseignée", text)


if __name__ == "__main__":
    unittest.main()
