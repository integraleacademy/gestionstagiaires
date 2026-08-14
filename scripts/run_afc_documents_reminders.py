"""Invoke the protected AFC document-reminder endpoint from Render Cron."""

import os

import requests


url = os.environ.get("AFC_DOCUMENTS_REMINDERS_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("AFC_DOCUMENTS_REMINDERS_URL and CRON_SECRET must be configured")

response = requests.post(
    url,
    headers={"X-Cron-Secret": token, "Accept": "application/json"},
    timeout=900,
)
if not response.ok:
    raise SystemExit(f"AFC document reminders failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)
