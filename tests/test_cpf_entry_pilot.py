from copy import deepcopy
from types import SimpleNamespace
import pytest
from cpf_entry_pilot import ACTION, automation_lock, change, snapshot
from cpf_provider import ProviderUnavailable

FOLDER = "123456789"
SECOND = "987654321"

def test_entry_ownership_is_scoped_and_never_releases_a_claimed_write(tmp_path):
    data = {"wedof_automation_status": [{"external_id": f, "wedof_state": "accepted", "wedof_type": "cpf"}
                                        for f in (FOLDER, SECOND)]}
    untouched = snapshot(data, SECOND)
    change(data, FOLDER, "reserve", "admin")
    assert snapshot(data, FOLDER)["reserved"] and snapshot(data, SECOND) == untouched
    change(data, FOLDER, "reserve", "admin")
    assert len(data["wedof_automation_blocks"]) == 1
    copy = deepcopy(data)
    change(copy, FOLDER, "release", "admin")
    assert not snapshot(copy, FOLDER)["reserved"]
    ticket = snapshot(data, FOLDER)["ticket"]
    change(data, FOLDER, "claim", "admin", ticket)
    change(data, FOLDER, "claim", "admin", ticket)
    for mode, token in [("claim", "b"*32), ("release", "")]:
        with pytest.raises(ValueError):
            change(data, FOLDER, mode, "admin", token)
    data["wedof_automation_blocks"].append({"action":"both","external_id":SECOND,"active":True})
    with pytest.raises(ValueError):
        change(data, SECOND, "reserve", "admin")
    legacy = SimpleNamespace(WEDOF_AUTOMATION_LOCK_FILE=tmp_path / "wedof.lock")
    with automation_lock(legacy), pytest.raises(ProviderUnavailable), automation_lock(legacy):
        pass

def test_uncertain_or_completed_wedof_actions_are_never_claimed():
    data = {"wedof_automation_status": [{"external_id":FOLDER,"wedof_state":"accepted","wedof_type":"cpf"}]}
    for status in ("processing","uncertain_after_timeout","already_done","success"):
        data["wedof_automation_actions"] = [{"external_id":FOLDER,"action":ACTION,"status":status}]
        with pytest.raises(ValueError):
            change(data,FOLDER,"reserve","admin")
