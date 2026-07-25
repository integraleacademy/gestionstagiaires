"""Invoke the protected convocation reminder endpoint from a Render Cron job."""
import os

import requests


url = os.environ.get("CONVOCATION_REMINDERS_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("CONVOCATION_REMINDERS_URL and CRON_SECRET must be configured")

response = requests.post(
    url,
    headers={"X-Cron-Secret": token, "Accept": "application/json"},
    timeout=900,
)
if not response.ok:
    raise SystemExit(f"Convocation reminders failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)
