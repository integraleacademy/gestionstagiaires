"""Invoke the protected CNAPS monitor endpoint once."""
import os

import requests


def run_monitor_once() -> str:
    url = os.environ.get("CNAPS_MONITOR_URL", "").strip()
    token = os.environ.get("CNAPS_MONITOR_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError("CNAPS_MONITOR_URL and CNAPS_MONITOR_TOKEN must be configured")

    response = requests.post(
        url,
        headers={"X-CNAPS-Monitor-Token": token, "Accept": "application/json"},
        timeout=900,
    )
    if not response.ok:
        raise RuntimeError(f"CNAPS monitor failed: HTTP {response.status_code}: {response.text[:300]}")
    return response.text


if __name__ == "__main__":
    try:
        print(run_monitor_once(), flush=True)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
