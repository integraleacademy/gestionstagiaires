"""Call the application's Qonto reconciliation job without a browser session."""
import json
import os
import requests
from scheduled_job_client import wait_for_job


def main():
    url = os.environ.get('QONTO_SYNC_URL', '').strip()
    token = (os.environ.get('QONTO_SYNC_CRON_SECRET') or os.environ.get('CRON_SECRET') or '').strip()
    if not url or not token:
        raise SystemExit('QONTO_SYNC_URL and a cron secret must be configured')
    headers = {'X-Cron-Secret': token, 'Accept': 'application/json'}
    try:
        response = requests.post(url, json={}, headers=headers, timeout=240)
        response = wait_for_job(response, url=url, headers=headers)
        if not response.ok:
            raise SystemExit(f'Qonto background sync failed: HTTP {response.status_code}')
        result = response.json()
    except (requests.RequestException, TimeoutError, ValueError, RuntimeError):
        raise SystemExit('Qonto background sync unavailable; the next scheduled run will retry') from None
    # Print only operational counters, never banking records or credentials.
    fields = ('ok', 'status', 'started_at', 'finished_at', 'attempted_count',
              'synced_count', 'failed_count', 'conflict_count', 'remaining_count')
    print(json.dumps({key: result[key] for key in fields if key in result}, ensure_ascii=False))
    if not result.get('ok'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
