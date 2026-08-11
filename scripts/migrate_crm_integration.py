"""Prepare and validate the JSON store for the Intégrale Connect CRM integration."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def migrate(data):
    changed = False
    if not isinstance(data.get("crm_integration_requests"), list):
        data["crm_integration_requests"] = []
        changed = True
    seen_keys = set()
    seen_contacts = set()
    for item in data["crm_integration_requests"]:
        key = str(item.get("idempotency_key") or "")
        contact = str(item.get("crm_contact_id") or "")
        if not key or key in seen_keys:
            raise RuntimeError(f"Clé d'idempotence absente ou dupliquée: {key!r}")
        if not contact or contact in seen_contacts:
            raise RuntimeError(f"crm_contact_id absent ou dupliqué: {contact!r}")
        seen_keys.add(key)
        seen_contacts.add(contact)
    for session_obj in data.get("sessions", []):
        if not isinstance(session_obj, dict):
            continue
        if "crm_center" not in session_obj:
            # Only copy an existing structured value; never infer a centre from a label.
            session_obj["crm_center"] = str(session_obj.get("center") or session_obj.get("centre") or "")
            changed = True
    return changed


def main() -> None:
    backup = app._force_backup_snapshot(app.DATA_FILE, reason="before-crm-integration-migration")
    data = app.load_data()
    changed = migrate(data)
    app.save_data(data)
    print({"ok": True, "changed": changed, "backup": backup, "data_file": app.DATA_FILE})


if __name__ == "__main__":
    main()
