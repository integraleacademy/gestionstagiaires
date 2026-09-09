"""Run WEDOF and optional Qonto reconciliation from the existing Render cron."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess
import sys

import requests


def run_wedof():
    url = os.environ.get("WEDOF_AUTOMATION_URL", "").strip()
    token = os.environ.get("CRON_SECRET", "").strip()
    if not url or not token:
        raise SystemExit("WEDOF_AUTOMATION_URL and CRON_SECRET must be configured")
    response = requests.post(url, headers={"X-Cron-Secret": token, "Accept": "application/json"}, timeout=900)
    if not response.ok:
        raise SystemExit(f"WEDOF automation failed: HTTP {response.status_code}")
    print(response.text, flush=True)


def run_qonto():
    subprocess.run([sys.executable, str(Path(__file__).with_name("run_qonto_sync.py"))], check=True)


def main():
    failed = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = {executor.submit(run_wedof): "WEDOF"}
        if os.environ.get("QONTO_SYNC_URL", "").strip():
            tasks[executor.submit(run_qonto)] = "Qonto"
        # Start both requests independently: a slow or failed WEDOF call must
        # not stop the Qonto update (and a Qonto failure must not stop WEDOF).
        for future in as_completed(tasks):
            try:
                future.result()
            except (Exception, SystemExit):
                failed = True
                print(f"{tasks[future]} scheduled synchronization failed", file=sys.stderr, flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
