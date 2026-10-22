"""Gunicorn settings for Render and local container runs."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 300
graceful_timeout = 30
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE") or "2")

accesslog = "-"
# Expose actual application request time for subsequent performance checks.
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" duration_us=%(D)s'
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
capture_output = True

# Do not periodically recycle the only worker. Keep a single process because
# the application persists state in a shared data.json file, and use threads so
# liveness probes are not starved by a long synchronous job.
max_requests = 0
max_requests_jitter = 0


def post_worker_init(worker):
    # Start after the fork, including after a deploy/restart without any visit.
    import app as legacy_app
    from vtc_elearning_activation import start_worker
    start_worker(legacy_app)
    import parcours_alternance
    parcours_alternance.start_worker(legacy_app)


def worker_exit(server, worker):
    import app as legacy_app
    for name in ("vtc_elearning_worker", "parcours_alternance_worker"):
        state = legacy_app.app.extensions.get(name)
        if state:
            state["stop"].set()
            state["thread"].join(timeout=15)
