"""Call the application's Qonto reconciliation job without a browser session."""
import json
import os
import urllib.error
import urllib.request


def main():
    url = os.environ.get('QONTO_SYNC_URL', '').strip()
    token = (os.environ.get('QONTO_SYNC_CRON_SECRET') or os.environ.get('CRON_SECRET') or '').strip()
    if not url or not token:
        raise SystemExit('QONTO_SYNC_URL and a cron secret must be configured')
    request = urllib.request.Request(
        url, data=b'{}', method='POST',
        headers={'X-Cron-Secret': token, 'Content-Type': 'application/json', 'Accept': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f'Qonto background sync failed: HTTP {exc.code}') from None
    except (urllib.error.URLError, TimeoutError, ValueError):
        raise SystemExit('Qonto background sync unavailable; the next scheduled run will retry') from None
    # Print only operational counters, never banking records or credentials.
    fields = ('ok', 'status', 'started_at', 'finished_at', 'attempted_count',
              'synced_count', 'failed_count', 'conflict_count', 'remaining_count')
    print(json.dumps({key: result[key] for key in fields if key in result}, ensure_ascii=False))
    if not result.get('ok'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
