import os
import runpy
import unittest
from unittest.mock import patch


class GunicornConfigTests(unittest.TestCase):
    def _load_config(self, **environment):
        clean_environment = os.environ.copy()
        clean_environment.pop("WEB_CONCURRENCY", None)
        clean_environment.pop("GUNICORN_MAX_REQUESTS", None)
        clean_environment.pop("GUNICORN_MAX_REQUESTS_JITTER", None)
        clean_environment.update(environment)
        with patch.dict(os.environ, clean_environment, clear=True):
            return runpy.run_path("gunicorn.conf.py")

    def test_single_worker_does_not_recycle_by_default(self):
        config = self._load_config()

        self.assertEqual(config["workers"], 1)
        self.assertEqual(config["max_requests"], 0)
        self.assertEqual(config["max_requests_jitter"], 0)

    def test_recycling_remains_configurable_for_multi_worker_deployments(self):
        config = self._load_config(
            WEB_CONCURRENCY="2",
            GUNICORN_MAX_REQUESTS="2000",
            GUNICORN_MAX_REQUESTS_JITTER="200",
        )

        self.assertEqual(config["workers"], 2)
        self.assertEqual(config["max_requests"], 2000)
        self.assertEqual(config["max_requests_jitter"], 200)
