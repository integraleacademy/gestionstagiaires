import unittest
from pathlib import Path
from unittest.mock import patch

import app as gestion_app


class CpuLoadGuardTests(unittest.TestCase):
    def test_admin_context_loads_business_data_only_once(self):
        data = {"partners": [], "notifications_admin": [], "sessions": [], "users": []}
        with gestion_app.app.test_request_context("/admin/sessions"):
            gestion_app.session["admin_logged_in"] = True
            gestion_app.session["admin_role"] = "admin"
            with patch.object(gestion_app, "load_data", return_value=data) as load_data, \
                 patch.object(gestion_app, "_load_wedof_webhooks", return_value=[]), \
                 patch.object(
                     gestion_app,
                     "_build_sales_tracking_metrics",
                     return_value={"today_inscriptions": 2},
                 ) as build_sales_metrics, \
                 patch.object(
                     gestion_app,
                     "_admin_notifications_payload",
                     return_value={"notifications": [], "unresolved_total": 0},
                 ) as build_notifications:
                context = gestion_app.inject_read_only()

        load_data.assert_called_once_with()
        build_sales_metrics.assert_called_once_with(data, gestion_app.datetime.date.today().year)
        build_notifications.assert_called_once_with(data)
        self.assertEqual(context["sales_today_notification_count"], 2)

    def test_memory_stage_is_noop_when_diagnostics_are_disabled(self):
        with patch.object(gestion_app, "MEMORY_DIAGNOSTICS_ENABLED", False), \
             patch.object(
                 gestion_app,
                 "_current_rss_mb",
                 side_effect=AssertionError("RSS should not be read when diagnostics are disabled"),
             ):
            baseline = gestion_app._log_memory_stage("TEST", baseline_mb=42.0)

        self.assertEqual(baseline, 42.0)

    def test_billing_list_builds_lines_only_once_per_poll(self):
        data = {"sessions": [], "billing_lines": []}
        lines = [{"id": "line-1"}]
        client = gestion_app.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["admin_logged_in"] = True
            flask_session["admin_role"] = "admin"

        with patch.object(gestion_app, "load_data", return_value=data), \
             patch.object(gestion_app, "_billing_lines", return_value=lines) as build_lines, \
             patch.object(gestion_app, "_repair_logged_qonto_rejection_retries") as repair_lines:
            response = client.get("/api/admin/billing-lines")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["lines"], lines)
        build_lines.assert_called_once_with(data)
        repair_lines.assert_called_once_with(data, lines)

    def test_browser_polling_uses_the_reduced_frequencies(self):
        project_root = Path(__file__).resolve().parents[1]
        trainee_page = (project_root / "templates" / "admin_trainee.html").read_text(encoding="utf-8")
        billing_page = (project_root / "templates" / "admin_sessions_billing.html").read_text(encoding="utf-8")
        trainees_page = (project_root / "templates" / "admin_trainees.html").read_text(encoding="utf-8")

        self.assertIn("document.hidden?120000:30000", trainee_page)
        self.assertIn("document.hidden?120000:30000", billing_page)
        self.assertIn("if (document.hidden) return;", trainees_page)
        self.assertIn("setInterval(autoRefreshExternalStatuses, 15 * 60 * 1000)", trainees_page)
        self.assertIn("}, 60 * 1000);", trainees_page)


if __name__ == "__main__":
    unittest.main()
