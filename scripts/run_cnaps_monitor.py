"""Invoke the protected CNAPS monitor endpoint from a Render Cron job."""
import os

import requests


url = os.environ.get("CNAPS_MONITOR_URL", "").strip()
token = os.environ.get("CNAPS_MONITOR_TOKEN", "").strip()
if not url or not token:
    raise SystemExit("CNAPS_MONITOR_URL and CNAPS_MONITOR_TOKEN must be configured")

response = requests.post(
    url,
    headers={"X-CNAPS-Monitor-Token": token, "Accept": "application/json"},
    timeout=900,
)
if not response.ok:
    raise SystemExit(f"CNAPS monitor failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)
