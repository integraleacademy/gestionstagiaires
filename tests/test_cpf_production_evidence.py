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

def test_explicit_start_date_takes_precedence_over_tracking(tmp_path):
    import sqlite3
    path = tmp_path/"native_elearning"
    path.mkdir()
    with sqlite3.connect(path/"tracking.sqlite3") as db:
        db.execute("CREATE TABLE tracking_events(id,session_id,trainee_id,event_type,activity_id,event_at)")
        db.execute("INSERT INTO tracking_events VALUES (1,'s','t','answer_submitted','lesson','2026-01-01T08:30:00Z')")
    person = {"id":"t","first_name":"Marie","last_name":"Essai","actual_training_start_date":"2026-01-03"}
    data = {"sessions":[{"id":"s","date_start":"2026-01-01","date_end":"2026-01-30","trainees":[person]}],
            "wedof_links":[{"active":True,"external_id":FOLDER,"session_id":"s","trainee_id":"t"}]}
    legacy = NS(DATA_FILE=tmp_path/"data.json",load_data=lambda:data)
    assert evidence.read_evidence(legacy,[FOLDER])[FOLDER]["entry_training"]["actual_date"] == "2026-01-03"

def test_session_end_is_used_for_completed_training_without_duplicate_date_entry(tmp_path):
    t = {"id":"t","first_name":"Marie","last_name":"Essai"}
    group = {"id":"s","date_start":"2026-01-01","date_end":"2026-01-30","trainees":[t]}
    data = {"sessions":[group],"wedof_links":[{"active":True,"external_id":FOLDER,"session_id":"s","trainee_id":"t"}]}
    legacy = NS(DATA_FILE=tmp_path/"data.json",load_data=lambda:data)
    proof = lambda:evidence.read_evidence(legacy,[FOLDER])[FOLDER]
    assert "service_done" not in proof()
    t["deliverables"] = {"attestation_fin_formation":"signed-file"}
    assert "service_done" not in proof()
    t["realized_training_hours"] = "12"
    assert proof()["service_done"]["actual_date"] == group["date_end"]
    t["vtc_real_training_dates"] = "02/01/2026 au 24/01/2026"
    assert proof()["entry_training"]["actual_date"] == "2026-01-02"
    assert proof()["service_done"]["actual_date"] == "2026-01-24"
    t["actual_training_end_date"] = "non renseignée"
    assert "service_done" not in proof()
