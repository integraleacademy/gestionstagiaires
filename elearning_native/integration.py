from __future__ import annotations

from types import ModuleType

from .web import create_native_elearning_blueprint
from elearning_orders import learner_context


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
            mutate_data=lambda mutator: legacy_app._atomic_update_data(mutator),
            find_session=legacy_app.find_session,
            find_session_and_trainee_by_token=lambda data, token: learner_context(data, token, host=legacy_app) if token.startswith("el_") else legacy_app.find_session_and_trainee_by_token(data, token),
            session_trainees=legacy_app._session_trainees_list,
            public_is_authed=legacy_app._public_is_authed,
            is_aps_elearning_session=lambda s: legacy_app._is_aps_elearning_session(s) or (
                any(label in str(s.get('training_type') or '').upper() for label in ('VTC', 'A3P')) and bool(s.get('aps_elearning_enabled'))),
            session_start_date=legacy_app._session_start_date,
        )
    )
    flask_app.config["NATIVE_ELEARNING_ENABLED"] = True


