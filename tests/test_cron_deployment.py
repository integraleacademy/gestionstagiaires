"""Deployment checks for server-side scheduled jobs."""
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CronDeploymentTests(unittest.TestCase):
    def test_render_shares_one_generated_secret_with_web_and_crons(self):
        blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
        secret_group = blueprint.split("envVarGroups:", 1)[1].split(
            "  - name: gestionstagiaires-cnaps-monitor-secrets", 1
        )[0]
        services = blueprint.split("services:", 1)[1]
        web = services.split("  - type: web", 1)[1].split("  - type: cron", 1)[0]
        cron_blocks = services.split("  - type: cron")[1:]

        self.assertIn("name: gestionstagiaires-cron-secrets", secret_group)
        self.assertIn("key: CRON_SECRET", secret_group)
        self.assertIn("generateValue: true", secret_group)
        self.assertIn("fromGroup: gestionstagiaires-cron-secrets", web)
        self.assertEqual(len(cron_blocks), 7)
        for cron in cron_blocks:
            self.assertIn("fromGroup: gestionstagiaires-cron-secrets", cron)
            self.assertNotIn("key: CRON_SECRET\n        sync: false", cron)

    def test_wedof_mutations_use_one_explicit_kill_switch(self):
        blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
        web = blueprint.split("  - type: web", 1)[1].split("  - type: cron", 1)[0]
        self.assertIn('key: WEDOF_AUTOMATION_KILL_SWITCH\n        value: "false"', web)
        self.assertNotIn("key: WEDOF_AUTOMATION_ENABLED", web)
        self.assertNotIn("key: WEDOF_DRY_RUN", web)
        self.assertNotIn("key: WEDOF_CRON_ENABLED", web)
        self.assertIn('key: WEDOF_RECONCILIATION_ENABLED\n        value: "true"', web)
        self.assertIn('key: WEDOF_PAGE_LIMIT\n        value: "100"', web)
        self.assertIn("key: WEDOF_WEBHOOK_SECRET\n        sync: false", web)
        self.assertIn('key: WEDOF_GOVERNOR_ENABLED\n        value: "true"', web)
        self.assertIn('key: WEDOF_REQUEST_LIMIT_PER_MONTH\n        value: "15000"', web)

    def test_global_reconciliation_runs_at_most_four_times_a_day(self):
        blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
        block = blueprint.split(
            "name: gestionstagiaires-wedof-reconciliation", 1,
        )[1].split("  - type:", 1)[0]
        self.assertIn('schedule: "17 6,10,14,18 * * *"', block)
        self.assertIn("scripts/run_wedof_reconciliation.py", block)


if __name__ == "__main__":
    unittest.main()
