"""Deployment checks for the browser-independent CNAPS monitor."""
import importlib.util
import os
import pathlib
import sys
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_script(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class _StopAfterFirstWait:
    def __init__(self):
        self.stopped = False
        self.waited = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waited.append(seconds)
        self.stopped = True


class CnapsMonitorDeploymentTests(unittest.TestCase):
    def test_render_blueprint_runs_cnaps_monitor_in_permanent_worker(self):
        blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
        monitor = blueprint.rsplit("  - type: worker", 1)[1]
        web = blueprint.split("  - type: web", 1)[1].split("  - type: cron", 1)[0]

        self.assertIn("name: gestionstagiaires-cnaps-monitor-secrets", blueprint)
        self.assertIn("name: gestionstagiaires-cnaps-monitor", monitor)
        self.assertNotIn("schedule:", monitor)
        self.assertIn("dockerCommand: python scripts/run_cnaps_monitor_worker.py", monitor)
        self.assertIn("key: CNAPS_MONITOR_URL", monitor)
        self.assertIn("fromGroup: gestionstagiaires-cnaps-monitor-secrets", monitor)
        self.assertIn("fromGroup: gestionstagiaires-cnaps-monitor-secrets", web)
        self.assertIn("key: CNAPSV3_API_TOKEN", web)
        self.assertIn("key: BREVO_API_KEY", web)
        self.assertIn("key: CNAPS_MONITOR_INTERVAL_SECONDS", monitor)
        self.assertIn("value: 900", monitor)

    def test_worker_runs_immediately_then_waits_fifteen_minutes(self):
        worker = _load_script("run_cnaps_monitor_worker")
        stop = _StopAfterFirstWait()
        with patch.object(worker, "run_monitor_once", return_value='{"ok": true}') as monitor:
            with patch.dict(os.environ, {"CNAPS_MONITOR_INTERVAL_SECONDS": "900"}):
                worker.monitor_forever(stop)

        monitor.assert_called_once_with()
        self.assertEqual(stop.waited, [900])

    def test_monitor_targets_protected_server_job(self):
        source = (ROOT / "scripts" / "run_cnaps_monitor.py").read_text(encoding="utf-8")
        self.assertIn('headers={"X-CNAPS-Monitor-Token": token', source)
        self.assertIn("response = requests.post(", source)


if __name__ == "__main__":
    unittest.main()
