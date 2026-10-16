"""Platform-wide sales switch, independent of JSON/PostgreSQL tenant storage."""
from contextlib import contextmanager
from functools import wraps
import fcntl
import json
from pathlib import Path
import threading


TITLE = "Ventes momentanément indisponibles"
MESSAGE = "Une mise à jour des parcours e-learning est en cours. Les ventes reprendront dès la fin de cette mise à jour."
_write_lock = threading.RLock()


class SalesUnavailable(Exception):
    pass


def settings_path(host):
    # Same persistent disk as the application data; never part of a tenant bundle.
    return Path(host.DATA_FILE).with_name("elearning-sales.json")


def enabled(host):
    try:
        settings = json.loads(settings_path(host).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True  # Existing shops remain open until an administrator pauses sales.
    except (OSError, ValueError):
        host.app.logger.error("Unable to read e-learning sales settings; sales paused")
        return False
    return isinstance(settings, dict) and settings.get("enabled") is True


def save(host, value, actor):
    host._write_json_with_backups(
        str(settings_path(host)),
        {"enabled": bool(value), "updated_at": host._now_iso(), "updated_by": str(actor or "")},
        _write_lock,
    )


@contextmanager
def purchase_guard(host):
    """Serialize a sale with the switch, including across Gunicorn workers.

    A successful pause waits for already accepted purchases to finish. Future
    requests read the persisted value, even from an old browser form.
    """
    path = settings_path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            if not enabled(host):
                raise SalesUnavailable()
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def required(host):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            with purchase_guard(host):
                return view(*args, **kwargs)
        return wrapped
    return decorate
