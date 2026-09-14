"""Invoke only the document-reminder scheduler using the existing cron secret."""
import json
import os
from urllib.parse import urlsplit, urlunsplit

import requests


def reminder_url():
    explicit = os.environ.get("DOCUMENT_REMINDERS_URL", "").strip()
    if explicit:
        return explicit
    # Existing deployed Render crons already have this URL and shared secret.
    # Reuse its exact origin, so deployment needs no new service or credentials.
    base = urlsplit(os.environ.get("WEDOF_AUTOMATION_URL", "").strip())
    if base.scheme in {"http", "https"} and base.netloc and base.path == "/internal/cron/wedof-automation":
        return urlunsplit((base.scheme, base.netloc, "/internal/cron/document-reminders", "", ""))
    return ""


def main():
    url = reminder_url()
    token = os.environ.get("CRON_SECRET", "").strip()
    if not url or not token:
        raise SystemExit("Document reminder URL and CRON_SECRET must be configured")
    response = requests.post(url, headers={"X-Cron-Secret": token, "Accept": "application/json"}, timeout=240)
    if not response.ok:
        raise SystemExit(f"Document reminders failed: HTTP {response.status_code}")
    result = response.json()
    keys = ("ok", "status", "checked", "due", "processed", "emails_accepted", "sms_accepted", "failed", "activated_on")
    print("Document reminders: " + json.dumps({k: result[k] for k in keys if k in result}, ensure_ascii=False), flush=True)
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
