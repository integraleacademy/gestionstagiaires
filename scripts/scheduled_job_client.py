"""Wait for a scheduled job without holding an HTTP connection open.

Accept synchronous responses as well, so web/cron rolling deploys can happen in
either order. Poll only the exact configured endpoint and never repeat a POST.
"""
import time

import requests


def wait_for_job(response, *, url, headers, timeout=900):
    deadline = time.monotonic() + timeout
    while response.status_code == 202:
        payload = response.json()
        job_id = payload.get("job_id")
        if not job_id or payload.get("status") not in {"queued", "running"}:
            raise RuntimeError("Invalid scheduled job acknowledgement")
        if time.monotonic() >= deadline:
            raise TimeoutError("Scheduled job did not finish before the polling deadline")
        time.sleep(3)
        response = requests.get(
            url, params={"job_id": job_id}, headers=headers, timeout=30,
            allow_redirects=False,
        )
    return response
