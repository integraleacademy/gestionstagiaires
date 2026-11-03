"""Refresh stale internal CPF links outside the HTTP request that displays them."""
import datetime
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from cpf_provider import ProviderUnavailable, provider_operation

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cpf-snapshot")
_lock = threading.Lock()
_pending = set()
_recent_attempts = OrderedDict()
MAX_PENDING = 16
DAY = 86400


class LinkChanged(Exception):
    """Another operation superseded this snapshot while the provider was replying."""


def refresh_link(host, session_id, trainee_id, link):
    external_id = str(link["external_id"])
    previous = (link.get("last_seen_at"), link.get("cpf_snapshot"), link.get("wedof_state"))
    # Keep the selected provider stable through the targeted commit.
    def commit(folder=None, remote=None):
        def merge(current):
            active = host._cpf_active_link(current, session_id=session_id, trainee_id=trainee_id)
            training = host.find_session(current, session_id)
            if (not training or (training.get("partner_id") or host.INTEGRALE_PARTNER_ID) != host.INTEGRALE_PARTNER_ID
                    or not active or str(active.get("external_id")) != external_id
                    or previous != (active.get("last_seen_at"), active.get("cpf_snapshot"), active.get("wedof_state"))):
                raise LinkChanged()
            if folder is None:
                message = "Synchronisation momentanément indisponible"
                if active.get("cpf_sync_error") == message:
                    raise LinkChanged()
                active["cpf_sync_error"] = message
            else:
                active["cpf_snapshot"] = host._cpf_public_snapshot(remote)
                active["wedof_state"] = remote.get("state") or active.get("wedof_state")
                active["last_seen_at"] = host._now_iso()
                active.pop("cpf_sync_error", None)
                host._upsert_wedof_folder_cache(current, folder)
                host.sync_folder_automation_status(current, folder)
            return {}
        try:
            host._atomic_update_data(merge)
        except LinkChanged:
            return False
        return True

    with provider_operation("wedof"):
        try:
            folder = host.WedofClient().get_registration_folder_interactive(
                external_id, operation="cpf_invoice_manual_refresh",
            )
            remote = host.extract_folder(folder)
            if str(remote.get("external_id") or "") != external_id or str(remote.get("type") or "").casefold() != "cpf":
                raise host.WedofApiError("Le dossier retourné ne correspond pas au lien CPF.")
        except (host.WedofApiError, host.WedofConfigurationError):
            commit()
            raise
        return commit(folder, remote)


def schedule_refresh(host, session_id, trainee_id, link):
    if not link or not link.get("external_id"):
        return
    stamp = host._parse_iso_datetime(link.get("last_seen_at") or (link.get("cpf_snapshot") or {}).get("synced_at"))
    if stamp and datetime.datetime.utcnow() - stamp < datetime.timedelta(days=1):
        return
    key = (session_id, trainee_id, str(link["external_id"]))
    now = time.monotonic()
    with _lock:
        if key in _pending or len(_pending) >= MAX_PENDING or now - _recent_attempts.get(key, -DAY) < DAY:
            return
        _pending.add(key)
        _recent_attempts[key] = now
        _recent_attempts.move_to_end(key)
        if len(_recent_attempts) > 1024:
            _recent_attempts.popitem(last=False)

    def run():
        try:
            refresh_link(host, session_id, trainee_id, link)
        except ProviderUnavailable:
            pass
        except (host.WedofApiError, host.WedofConfigurationError) as exc:
            host.app.logger.info("CPF background refresh unavailable code=%s", getattr(exc, "code", type(exc).__name__))
        except Exception:
            host.app.logger.exception("CPF background refresh failed")
        finally:
            with _lock:
                _pending.discard(key)
    try:
        _pool.submit(run)
    except RuntimeError:  # Worker shutting down. The next process may retry.
        with _lock:
            _pending.discard(key)
            _recent_attempts.pop(key, None)
