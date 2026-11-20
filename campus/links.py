"""Public learning origin, enabled only after the management cutover."""
import os
from urllib.parse import urlsplit


def origin(fallback=""):
    if os.environ.get("CAMPUS_MANAGEMENT_MODE") != "active":
        return fallback.rstrip("/")
    value = os.environ.get("CAMPUS_PUBLIC_URL", "").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError("Origine HTTPS du Campus invalide.")
    return value
