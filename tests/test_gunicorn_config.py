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

    def test_single_gthread_worker_ignores_worker_recycling_environment(self):
        config = self._load_config(
            WEB_CONCURRENCY="2",
            GUNICORN_MAX_REQUESTS="2000",
            GUNICORN_MAX_REQUESTS_JITTER="200",
        )

        self.assertEqual(config["workers"], 1)
        self.assertEqual(config["worker_class"], "gthread")
        self.assertEqual(config["threads"], 4)
        self.assertEqual(config["timeout"], 300)
        self.assertEqual(config["graceful_timeout"], 30)
        self.assertEqual(config["max_requests"], 0)
        self.assertEqual(config["max_requests_jitter"], 0)
