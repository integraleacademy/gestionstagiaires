"""Gunicorn settings for Render and local container runs."""

import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = int(os.environ.get("WEB_CONCURRENCY") or "1")
threads = int(os.environ.get("GUNICORN_THREADS") or "2")
timeout = int(os.environ.get("GUNICORN_TIMEOUT") or "300")
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT") or "30")
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE") or "2")

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True

# Avoid unbounded growth on long-lived Render instances while keeping the
# default single-worker footprint conservative for this large Flask app.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS") or "1000")
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER") or "100")

# Document a safe upper bound for manual tuning without changing the default.
_suggested_workers = max(1, min(multiprocessing.cpu_count() * 2 + 1, 4))
