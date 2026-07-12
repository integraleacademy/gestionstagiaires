"""One-shot JSON migration for the progressive multi-partner rollout.

It creates a durable backup through the application's existing backup system,
ensures the historical Intégrale Academy partner exists, attaches legacy records
to that partner, validates that no existing session/trainee remains unscoped,
and writes the migrated payload back to the same JSON storage file.
"""
import app


def main() -> None:
    backup = app._force_backup_snapshot(app.DATA_FILE, reason="before-multi-partner-migration")
    data = app.load_data()
    changed = app._ensure_multi_partner_payload(data)
    missing_sessions = [s.get("id") for s in data.get("sessions", []) if isinstance(s, dict) and not s.get("partner_id")]
    missing_trainees = []
    for session_obj in data.get("sessions", []):
        if not isinstance(session_obj, dict):
            continue
        for trainee in app._session_trainees_list(session_obj):
            if isinstance(trainee, dict) and not trainee.get("partner_id"):
                missing_trainees.append({"session_id": session_obj.get("id"), "trainee_id": trainee.get("id")})
    if missing_sessions or missing_trainees:
        raise RuntimeError(f"Migration incomplète: sessions={missing_sessions} trainees={missing_trainees}")
    app.save_data(data)
    print({"ok": True, "changed": changed, "backup": backup, "data_file": app.DATA_FILE})


if __name__ == "__main__":
    main()
