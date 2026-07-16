import os
import unittest
from unittest.mock import patch

import requests
import app as gestion_app


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", content_type="application/json"):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.text = "<html>nope</html>" if content_type == "text/html" else "{}"
        self.ok = 200 <= status_code < 400

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def qonto_invoice(attachment_id="att_1"):
    return {"client_invoice": {"id": "inv_123", "attachment_id": attachment_id}}


def attachment(url="https://storage.test/signed", ctype="application/pdf"):
    return {"attachment": {"id": "att_1", "url": url, "file_name": "Facture 123.pdf", "file_content_type": ctype}}


class QontoPdfFetchTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"QONTO_LOGIN": "login", "QONTO_SECRET_KEY": "secret", "QONTO_API_BASE_URL": "https://qonto.test"}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_attachment_id_immediately_available_and_pdf_downloaded(self):
        calls = [FakeResponse(payload=qonto_invoice()), FakeResponse(payload=attachment()), FakeResponse(content=b"%PDF ok", content_type="binary/octet-stream")]
        with patch.object(gestion_app.requests, "get", side_effect=calls) as get:
            content, filename = gestion_app.fetch_qonto_client_invoice_pdf("inv_123")
        self.assertEqual(content, b"%PDF ok")
        self.assertEqual(filename, "Facture_123.pdf")
        self.assertEqual(get.call_args_list[0].kwargs["headers"], {"Authorization": "login:secret", "Accept": "application/json"})

    def test_attachment_id_available_after_retry(self):
        calls = [FakeResponse(payload=qonto_invoice("")), FakeResponse(payload=qonto_invoice()), FakeResponse(payload=attachment()), FakeResponse(content=b"%PDF ok")]
        with patch.object(gestion_app.time, "sleep") as sleep, patch.object(gestion_app.requests, "get", side_effect=calls):
            content, _ = gestion_app.fetch_qonto_client_invoice_pdf("inv_123")
        self.assertEqual(content, b"%PDF ok")
        sleep.assert_called_once()

    def test_no_attachment_id_after_retries(self):
        with patch.object(gestion_app.time, "sleep"), patch.object(gestion_app.requests, "get", side_effect=[FakeResponse(payload=qonto_invoice(""))]*3):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "en cours de génération"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_qonto_401(self):
        with patch.object(gestion_app.requests, "get", return_value=FakeResponse(status_code=401, payload={})):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "Impossible"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_qonto_404(self):
        with patch.object(gestion_app.requests, "get", return_value=FakeResponse(status_code=404, payload={})):
            with self.assertRaises(gestion_app.QontoNotFoundError):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_qonto_timeout(self):
        with patch.object(gestion_app.requests, "get", side_effect=requests.Timeout()):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "Impossible"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_non_json_response(self):
        with patch.object(gestion_app.requests, "get", return_value=FakeResponse(payload={}, content_type="text/html")):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "Impossible"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_attachment_without_url(self):
        calls = [FakeResponse(payload=qonto_invoice()), FakeResponse(payload=attachment(url=""))]
        with patch.object(gestion_app.requests, "get", side_effect=calls):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "Impossible"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_download_not_pdf(self):
        calls = [FakeResponse(payload=qonto_invoice()), FakeResponse(payload=attachment()), FakeResponse(content=b"not pdf")]
        with patch.object(gestion_app.requests, "get", side_effect=calls):
            with self.assertRaisesRegex(gestion_app.QontoPdfUnavailableError, "PDF valide"):
                gestion_app.fetch_qonto_client_invoice_pdf("inv_123")

    def test_route_requires_authentication(self):
        response = gestion_app.app.test_client().get("/admin/qonto/invoices/inv_123/pdf")
        self.assertNotEqual(response.status_code, 200)

    def test_interface_uses_internal_invoice_route_not_legacy_pdf_url(self):
        for path in ["templates/admin_sessions_billing.html", "templates/admin_trainee.html", "templates/admin_direct_debits.html"]:
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            self.assertIn("/admin/qonto/invoices/", source)
            self.assertNotIn("invoicePdfUrl", source)
