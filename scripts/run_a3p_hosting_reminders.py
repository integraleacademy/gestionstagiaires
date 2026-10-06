import os

import requests
from scheduled_job_client import wait_for_job


url = os.environ.get("A3P_HOSTING_REMINDERS_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("A3P_HOSTING_REMINDERS_URL and CRON_SECRET must be configured")

response = requests.post(url, headers={"X-Cron-Secret": token}, timeout=120)
response = wait_for_job(response, url=url, headers={"X-Cron-Secret": token, "Accept": "application/json"})
response.raise_for_status()
print(response.text)
