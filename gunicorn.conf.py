"""Gunicorn settings for Render and local container runs."""

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

# Do not periodically recycle the only worker by default.  With one worker,
# Gunicorn cannot serve requests while its replacement imports this large app;
# Render exposes that restart window as an intermittent 502.  Operators running
# at least two workers can still opt in to recycling through the environment.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS") or "0")
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER") or "0")
