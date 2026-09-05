"""Automatic, targeted WEDOF refresh for the admin trainee page."""

from functools import wraps
from typing import Any

from flask import session


_SYNC_ERROR = "Synchronisation momentanément indisponible"


def _refresh_associated_cpf(legacy_app: Any, session_id: str, trainee_id: str) -> bool:
    """Refresh the one WEDOF folder linked to the requested trainee.

    The page must remain available when WEDOF or the internal quota governor is
    unavailable. In that case the last snapshot is kept and clearly marked as
    stale by the existing CPF view.
    """
    data = legacy_app.load_data(run_background_tasks=False)
    local_session, trainee = legacy_app._cpf_local_registration(
        data, session_id, trainee_id,
    )
    if not local_session or not trainee:
        return False

    link = legacy_app._cpf_active_link(
        data, session_id=session_id, trainee_id=trainee_id,
    )
    if not link:
        return False

    try:
        # This is one read-only GET for the already-associated folder. It does
        # not list or scan WEDOF folders and remains protected by the governor.
        legacy_app._refresh_cpf_link_from_wedof(data, link)
    except (legacy_app.WedofApiError, legacy_app.WedofConfigurationError) as exc:
        link["cpf_sync_error"] = _SYNC_ERROR
        legacy_app.app.logger.info(
            "[WEDOF] automatic trainee refresh unavailable "
            "session_id=%s trainee_id=%s external_id=%s error_code=%s",
            session_id,
            trainee_id,
            link.get("external_id") or "",
            getattr(exc, "code", exc.__class__.__name__),
        )
    except Exception:
        # A remote-data edge case must never make an administrator lose access
        # to the trainee sheet. Keep the cached snapshot and log the traceback.
        link["cpf_sync_error"] = _SYNC_ERROR
        legacy_app.app.logger.exception(
            "[WEDOF] unexpected automatic trainee refresh failure "
            "session_id=%s trainee_id=%s external_id=%s",
            session_id,
            trainee_id,
            link.get("external_id") or "",
        )

    legacy_app.save_data(data)
    return True


def register_admin_trainee_wedof_refresh(legacy_app: Any) -> None:
    """Wrap the existing admin view so its linked WEDOF folder is fresh first."""
    flask_app = legacy_app.app
    endpoint = "admin_trainee_page"
    current_view = flask_app.view_functions.get(endpoint)
    if current_view is None or getattr(current_view, "_wedof_auto_refresh", False):
        return

    @wraps(current_view)
    def refreshed_view(session_id: str, trainee_id: str, *args: Any, **kwargs: Any):
        # The central before-request guard has already validated the session.
        # Retaining this explicit check also keeps the wrapper safe in tests and
        # in any alternate WSGI setup that omits that guard.
        if session.get("admin_logged_in"):
            try:
                _refresh_associated_cpf(legacy_app, session_id, trainee_id)
            except Exception:
                # Loading or saving the local store can fail independently of
                # WEDOF. Let the original page handle its normal fallback path.
                flask_app.logger.exception(
                    "[WEDOF] automatic trainee refresh could not be persisted "
                    "session_id=%s trainee_id=%s",
                    session_id,
                    trainee_id,
                )
        return current_view(session_id, trainee_id, *args, **kwargs)

    refreshed_view._wedof_auto_refresh = True
    flask_app.view_functions[endpoint] = refreshed_view

