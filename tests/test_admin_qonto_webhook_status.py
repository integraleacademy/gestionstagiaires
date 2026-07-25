import os
import unittest
from unittest.mock import patch

import app as gestion_app


class AdminQontoWebhookStatusTests(unittest.TestCase):
    def setUp(self):
        self.client = gestion_app.app.test_client()

    def _login_admin(self):
        with self.client.session_transaction() as session:
            session['admin_logged_in'] = True
            session['admin_role'] = 'admin'

    def test_status_requires_admin_authentication(self):
        response = self.client.get('/api/admin/qonto/webhook-status')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['ok'], False)

    def test_status_is_local_and_never_returns_qonto_secrets(self):
        self._login_admin()
        data = {
            'qonto_oauth': {'access_token': 'access-secret', 'refresh_token': 'refresh-secret', 'scopes': ['webhook']},
            'qonto_webhook_subscription': {'id': 'sub_123', 'event_types': ['v1/client-invoices'], 'callback_url': 'https://example.test/webhook'},
            'qonto_webhook_history': [{'received_at': '2026-07-24T15:24:00Z', 'event': 'v1/client-invoices', 'result': 'updated', 'error': 'none'}],
        }
        with patch.dict(os.environ, {'QONTO_LOGIN': 'api-login-secret', 'QONTO_SECRET_KEY': 'api-key-secret', 'QONTO_WEBHOOK_SECRET': 'webhook-secret'}, clear=False), \
             patch.object(gestion_app, 'load_data', return_value=data), \
             patch.object(gestion_app, '_qonto_request') as qonto_request, \
             patch.object(gestion_app, 'test_qonto_connection') as connection_test:
            response = self.client.get('/api/admin/qonto/webhook-status')

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['connection_api_key_ok'])
        self.assertEqual(body['subscription_id'], 'sub_123')
        self.assertEqual(body['last_event_type'], 'v1/client-invoices')
        self.assertEqual(body['last_processing_result'], 'updated')
        qonto_request.assert_not_called()
        connection_test.assert_not_called()
        serialized = response.get_data(as_text=True)
        for secret in ('access-secret', 'refresh-secret', 'api-login-secret', 'api-key-secret', 'webhook-secret'):
            self.assertNotIn(secret, serialized)


if __name__ == '__main__':
    unittest.main()
