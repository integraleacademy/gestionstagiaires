"""Invoke the protected daily recap endpoint from a Render Cron job."""
import os

import requests
from scheduled_job_client import wait_for_job
from run_aps_daily_followup import main as run_aps_daily_followup


url = os.environ.get("DAILY_RECAP_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("DAILY_RECAP_URL and CRON_SECRET must be configured")

# Independent delivery: a failure in either recap must not suppress the other.
aps_failed = False
try:
    run_aps_daily_followup()
except (Exception, SystemExit):
    aps_failed = True

response = requests.post(
    url,
    headers={"X-Cron-Secret": token, "Accept": "application/json"},
    timeout=900,
)
response = wait_for_job(response, url=url, headers={"X-Cron-Secret": token, "Accept": "application/json"})
if not response.ok:
    raise SystemExit(f"Daily recap failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)

if aps_failed:
    raise SystemExit("APS daily follow-up failed; see web service APS_DAILY logs")
