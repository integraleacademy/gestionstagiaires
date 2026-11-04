"""Invoke APS 09:00 follow-up; the server enforces Paris time and deduplication."""
import json
import os
from urllib.parse import urlsplit, urlunsplit

import requests
from scheduled_job_client import wait_for_job


def main():
    base = (os.environ.get('DAILY_RECAP_URL') or os.environ.get('WEDOF_AUTOMATION_URL') or '').strip()
    token = os.environ.get('CRON_SECRET', '').strip()
    if not base or not token:
        raise SystemExit('A cron endpoint and CRON_SECRET are required')
    parsed = urlsplit(base)
    url = urlunsplit((parsed.scheme, parsed.netloc, '/internal/cron/aps-daily-followup', '', ''))
    headers = {'X-Cron-Secret': token, 'Accept': 'application/json'}
    response = requests.post(url, headers=headers, timeout=900)
    response = wait_for_job(response, url=url, headers=headers)
    if not response.ok:
        raise SystemExit(f'APS daily follow-up failed: HTTP {response.status_code}')
    result = response.json()
    print('APS_DAILY cron ' + json.dumps({k: result[k] for k in ('ok','reason','eligible','sent','skipped','failed','uncertain') if k in result}), flush=True)
    if not result.get('ok'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
