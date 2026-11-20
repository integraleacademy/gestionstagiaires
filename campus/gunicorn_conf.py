"""Dedicated learner process. Administrative periodic jobs run on the manager."""
import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
worker_class = "gthread"
workers = 1
threads = 8
keepalive = 90
timeout = 90
graceful_timeout = 30
# Individual enrolment URLs are credentials. Keep only timing, status and method.
accesslog = "-"
access_log_format = '%(t)s "%(m)s" %(s)s duration_us=%(D)s'
errorlog = "-"
