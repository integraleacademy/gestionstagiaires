from __future__ import annotations

from types import ModuleType

from .web import create_native_elearning_blueprint


def register_native_elearning(legacy_app: ModuleType) -> None:
    """Attach the native APS e-learning routes to the legacy Flask app."""

    flask_app = legacy_app.app
    if "native_elearning" in flask_app.blueprints:
        return
    flask_app.register_blueprint(
        create_native_elearning_blueprint(
            get_persist_dir=lambda: legacy_app.PERSIST_DIR,
            load_data=lambda: legacy_app.load_data(run_background_tasks=False),
            save_data=lambda data: legacy_app.save_data(data),
            find_session=legacy_app.find_session,
            find_session_and_trainee_by_token=legacy_app.find_session_and_trainee_by_token,
            session_trainees=legacy_app._session_trainees_list,
            public_is_authed=legacy_app._public_is_authed,
            is_aps_elearning_session=legacy_app._is_aps_elearning_session,
            session_start_date=legacy_app._session_start_date,
        )
    )
