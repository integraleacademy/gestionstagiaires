import json
import time
from unittest.mock import Mock

import pytest

import edof_directory as directory
import edof_funding_watch as watch
import edof_server_browser as runner
from integrale_edof_dashboard import category
from test_integrale_edof_dashboard import site


def application(folder="100008", status="inProgress", state="validated"):
    return {"id": folder, "currentState": state,
            "attendee": {"firstName": "Sam", "lastName": "Exemple"},
            "trainingActionInfo": {"title": "Formation test", "sessionStartDate": "2027-01-04",
                "sessionEndDate": "2027-02-18", "solicitations": [{"fundingType": 9, "status": status}]}}


def portal(monkeypatch, items):
    snapshot = {"checked": time.time(), "rows": {item["id"]: directory.project(item) for item in items}}
    scan = Mock(return_value=snapshot)
    monkeypatch.setattr(runner, "read_recent_directory", scan)
    witness = Mock(method="GET", url="https://" + runner.EDOF_HOST + runner.API_PREFIX + "pad")
    witness.all_headers.return_value = {"authorization": "synthetic", "cookie": "not-forwarded"}
    return Mock(), witness, scan


def test_missing_submitted_dossier_updates_ft_counter_without_full_sync(site, monkeypatch):
    context, witness, scan = portal(monkeypatch, [application()])
    before = site.vault.get(directory.record_key(site.owner))
    watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    response = site.client.get("/admin/edof-test?section=state&group=requests&tab=ft")
    assert response.status_code == 200
    assert 'data-edof-folder="100008"' in response.text
    assert site.vault.get(directory.record_key(site.owner)) == before
    assert scan.call_args.args[2] == "validated"
    watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    scan.assert_called_once()
    context.request.get.assert_not_called()


@pytest.mark.parametrize("status, expected", [("inProgress", "ft"), ("refused", "ft_refused"), ("accepted", "waiting")])
def test_funding_decisions_replace_previous_flags(site, monkeypatch, status, expected):
    old = directory.project(application(status="refused"))
    full = {"checked": 100, "rows": {old["folder_id"]: old}}
    site.vault.put(directory.record_key(site.owner), full)
    context, witness, _ = portal(monkeypatch, [application(status=status)])
    watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    result = directory.with_validated(full, site.vault.get(directory.validated_key(site.owner)))
    assert category(result["rows"][old["folder_id"]]) == expected
    assert result["checked"] == 100


def test_fresh_full_or_targeted_evidence_and_identity_are_preserved():
    row = directory.project(application())
    newer = {**row, "state": "accepted", "observed_at": 300}
    old = {"checked": 200, "rows": {row["folder_id"]: row}}
    full = {"checked": 100, "rows": {row["folder_id"]: newer}}
    assert directory.with_validated(full, old)["rows"][row["folder_id"]] == newer
    assert directory.with_validated({**full, "checked": 400}, old)["rows"][row["folder_id"]] == newer
    old["checked"] = 500
    old["rows"][row["folder_id"]] = {**row, "last_name": "Different"}
    assert directory.with_validated(full, old)["rows"][row["folder_id"]] == newer


def test_departed_ft_dossiers_are_rechecked_with_bounded_identity_checked_gets(site, monkeypatch):
    old = {str(i): directory.project(application(str(i))) for i in range(100008, 100011)}
    full = {"checked": 100, "rows": old}
    site.vault.put(directory.record_key(site.owner), full)
    context, witness, scan = portal(monkeypatch, [])
    def reply(url, **kwargs):
        folder = url.rsplit("/", 1)[-1]
        body = application(folder, status="accepted", state="accepted")
        if folder == "100009":
            body["attendee"]["lastName"] = "Wrong identity"
        result = Mock(status=200, url=url)
        result.body.return_value = json.dumps(body).encode()
        assert kwargs["max_redirects"] == 0 and "cookie" not in kwargs["headers"]
        return result
    context.request.get.side_effect = reply
    watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    result = directory.with_validated(full, site.vault.get(directory.validated_key(site.owner)))
    assert context.request.get.call_count == 2
    assert category(result["rows"]["100008"]) == "accepted"
    assert category(result["rows"]["100009"]) == "ft"
    assert category(result["rows"]["100010"]) == "ft"
    # A later empty filtered list must retain the verified acceptance.
    site.vault.delete("validated-attempt:" + site.owner)
    watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    result = directory.with_validated(full, site.vault.get(directory.validated_key(site.owner)))
    assert category(result["rows"]["100008"]) == "accepted"


def test_failed_optional_detail_does_not_discard_new_funding_dossier(site, monkeypatch):
    site.vault.put(directory.record_key(site.owner), {"checked": 100, "rows": {"100009": directory.project(application("100009"))}})
    context, witness, _ = portal(monkeypatch, [application()])
    context.request.get.side_effect = OSError("unavailable")
    with pytest.raises(OSError):
        watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    assert site.vault.get(directory.validated_key(site.owner))["rows"]["100008"]["ft_pending"]


def test_wrong_filtered_scope_does_not_publish(site, monkeypatch):
    context, witness, _ = portal(monkeypatch, [application(state="accepted")])
    with pytest.raises(directory.IncompleteDirectory, match="scope"):
        watch.refresh(context, witness, site.vault, site.owner, lambda: None)
    assert not site.vault.get(directory.validated_key(site.owner))
