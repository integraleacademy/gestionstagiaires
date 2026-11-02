from types import SimpleNamespace as NS

import cpf_production_evidence as evidence

FOLDER = "123456789"
ENTRY = {"actual_date": "2026-01-03"}


def test_production_evidence_never_turns_planned_dates_or_hours_into_attendance(tmp_path):
    t = {"id": "t", "first_name": "Marie", "last_name": "Essai", "training_duration_hours": 12}
    group = {"id": "s", "date_start": "2026-01-01", "date_end": "2026-01-30", "trainees": [t]}
    data = {"sessions": [group], "wedof_links": [{"active": True, "external_id": FOLDER, "session_id": "s", "trainee_id": "t"}],
            "wedof_automation_blocks": []}
    legacy = NS(DATA_FILE=tmp_path/"data.json", load_data=lambda: data)
    def proof(): return evidence.read_evidence(legacy, [FOLDER])[FOLDER]
    assert "entry_training" not in proof() and "service_done" not in proof()
    t.update(actual_training_start_date="2026-01-03", actual_training_end_date="2026-01-29",
             deliverables={"attestation_fin_formation": "verified-file"})
    assert proof()["entry_training"]["actual_date"] == ENTRY["actual_date"] and "service_done" not in proof()
    t["hours_completed"] = 12
    assert proof()["service_done"]["actual_hours"] == "12"
    data["wedof_links"] *= 2
    assert "service_done" not in proof()
