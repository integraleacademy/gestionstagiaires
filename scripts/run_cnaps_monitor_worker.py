"""Run CNAPS monitoring every 15 minutes in an independent Render worker."""
import os
import threading

from run_cnaps_monitor import run_monitor_once


def monitor_forever(stop_event=None) -> None:
    stop_event = stop_event or threading.Event()
    interval = max(60, int(os.environ.get("CNAPS_MONITOR_INTERVAL_SECONDS", "900")))
    while not stop_event.is_set():
        try:
            print(run_monitor_once(), flush=True)
        except Exception as exc:
            # A temporary outage must not terminate the permanent worker. The
            # next pass retries every 15 minutes and Render retains this log.
            print(f"CNAPS monitor failed: {exc}", flush=True)
        stop_event.wait(interval)


if __name__ == "__main__":
    monitor_forever()
