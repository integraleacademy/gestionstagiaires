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
        self.assertEqual(len(cron_blocks), 4)
        for cron in cron_blocks:
            self.assertIn("fromGroup: gestionstagiaires-cron-secrets", cron)
            self.assertNotIn("key: CRON_SECRET\n        sync: false", cron)


if __name__ == "__main__":
    unittest.main()
