"""Invoke the protected Qonto synchronization endpoint from Render Cron."""
import os

import requests


url = os.environ.get("QONTO_SYNC_URL", "").strip()
secret = os.environ.get("CRON_SECRET", "").strip()
if not url or not secret:
    raise SystemExit("QONTO_SYNC_URL and CRON_SECRET must be configured")

response = requests.post(
    url,
    headers={"X-Cron-Secret": secret, "Accept": "application/json"},
    timeout=900,
)
if not response.ok:
    raise SystemExit(f"Qonto sync failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)
