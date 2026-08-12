"""Appelle le endpoint interne WEDOF dans le mode configuré sur le Web Service."""
import os
import requests

url = os.environ.get("WEDOF_AUTOMATION_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("WEDOF_AUTOMATION_URL and CRON_SECRET must be configured")
response = requests.post(url, headers={"X-Cron-Secret": token, "Accept": "application/json"}, timeout=900)
if not response.ok:
    raise SystemExit(f"WEDOF automation dry-run failed: HTTP {response.status_code}: {response.text[:300]}")
print(response.text)
