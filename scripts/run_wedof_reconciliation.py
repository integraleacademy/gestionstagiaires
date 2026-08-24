"""Appelle le endpoint GET-only de réconciliation globale WEDOF."""
import os

import requests


url = os.environ.get("WEDOF_RECONCILIATION_URL", "").strip()
token = os.environ.get("CRON_SECRET", "").strip()
if not url or not token:
    raise SystemExit("WEDOF_RECONCILIATION_URL and CRON_SECRET must be configured")
response = requests.post(
    url,
    headers={"X-Cron-Secret": token, "Accept": "application/json"},
    timeout=900,
)
if not response.ok:
    raise SystemExit(
        f"WEDOF reconciliation failed: HTTP {response.status_code}: "
        f"{response.text[:300]}"
    )
print(response.text)
