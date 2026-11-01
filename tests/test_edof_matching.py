import copy

import pytest

from edof_matching import MAX_CANDIDATES, build_comparison


@pytest.fixture
def observed():
    return {"folder_id": "123456789012", "first_name": "Élodie", "last_name": "D’EXEMPLE",
            "email": " demo@example.invalid ", "session_start_date": "2026-11-03",
            "session_end_date": "2026-12-08", "start_date": None, "end_date": None}


@pytest.fixture
def local():
    return {"sessions": [{"id": "S1", "name": "APS démonstration", "training_type": "APS",
            "date_start": "2026-11-03", "date_end": "2026-12-08", "trainees": [
                {"id": "T1", "first_name": "Elodie", "last_name": "D-Exemple",
                 "email": "DEMO@example.invalid", "phone": "PRIVATE", "address": "PRIVATE"}]}],
            "wedof_links": []}


def test_unique_concordant_suggestion_works_without_wedof_link_and_never_writes(observed, local):
    before = copy.deepcopy(local)
    remote_before = copy.deepcopy(observed)
    result = build_comparison(local, observed)
    assert result["status"] == "suggested"
    assert result["candidate_count"] == result["matching_session_count"] == 1
    assert result["candidates"][0]["concordant"] is True
    assert all(check["matches"] is True for check in result["candidates"][0]["checks"])
    assert local == before and observed == remote_before
    assert "PRIVATE" not in str(result)
    assert "phone" not in str(result) and "address" not in str(result)


@pytest.mark.parametrize("change", [
    {"email": "other@example.invalid"}, {"email": ""},
    {"first_name": "Autre"}, {"last_name": ""},
])
def test_shared_email_or_full_name_alone_always_requires_review(observed, local, change):
    local["sessions"][0]["trainees"][0].update(change)
    result = build_comparison(local, observed)
    assert result["status"] == "review"
    assert result["candidates"][0]["concordant"] is False


def test_empty_identity_and_contacts_never_match(observed, local):
    observed.update(first_name=None, last_name=None, email=None)
    assert build_comparison(local, observed)["status"] == "absent"
    assert build_comparison({"sessions": [{"trainees": [{}]}]}, observed)["candidate_count"] == 0


def test_one_name_and_matching_dates_do_not_suggest_a_person(observed, local):
    local["sessions"][0]["trainees"][0].update(first_name="Autre", email="other@example.invalid")
    result = build_comparison(local, observed)
    assert result["candidate_count"] == 0
    assert result["matching_session_count"] == 1


@pytest.mark.parametrize("changes", [
    {"date_start": "2026-11-04"}, {"date_end": "2026-12-09"},
    {"date_start": None}, {"date_end": "31/02/2026"},
])
def test_date_difference_or_missing_boundary_requires_review(observed, local, changes):
    local["sessions"][0].update(changes)
    result = build_comparison(local, observed)
    assert result["status"] == "review"
    assert result["matching_session_count"] == 0


def test_session_dates_have_priority_and_boundaries_are_never_mixed(observed, local):
    observed.update(start_date="2026-10-01", end_date="2026-10-31")
    assert build_comparison(local, observed)["status"] == "suggested"
    observed.update(session_end_date=None, start_date=None, end_date="2026-12-08")
    assert build_comparison(local, observed)["status"] == "review"
    observed.update(start_date="2026-11-03")
    assert build_comparison(local, observed)["status"] == "suggested"


def test_legacy_fields_and_french_dates(observed, local):
    group = local["sessions"][0]
    group["date_debut"] = group.pop("date_start")
    group["date_fin"] = "08/12/2026"
    del group["date_end"]
    group["stagiaires"] = group.pop("trainees")
    trainee = group["stagiaires"][0]
    trainee.update(prenom=trainee.pop("first_name"), nom=trainee.pop("last_name"), mail=trainee.pop("email"))
    assert build_comparison(local, observed)["status"] == "suggested"


def test_duplicate_registrations_remain_ambiguous(observed, local):
    group = copy.deepcopy(local["sessions"][0])
    group["id"] = "S2"
    local["sessions"].append(group)
    result = build_comparison(local, observed)
    assert result["status"] == "ambiguous"
    assert result["candidate_count"] == 2


@pytest.mark.parametrize("archive", [{"archived": True}, {"is_archived": True}, {"status": "archivée"}])
def test_archived_sessions_are_visible_but_require_review(observed, local, archive):
    local["sessions"][0].update(archive)
    result = build_comparison(local, observed)
    assert result["status"] == "review"
    assert result["candidates"][0]["issues"] == ["Cette session est archivée."]


def test_other_cpf_link_is_a_conflict_and_inactive_links_do_not_block(observed, local):
    local["wedof_links"] = [{"active": True, "external_id": "999999999999", "session_id": "S1", "trainee_id": "T1"}]
    result = build_comparison(local, observed)
    assert result["status"] == "review"
    assert "autre lien CPF" in result["candidates"][0]["issues"][0]
    local["wedof_links"][0]["active"] = False
    assert build_comparison(local, observed)["status"] == "suggested"


def test_exact_link_precedes_identity_and_exposes_differences(observed, local):
    local["wedof_links"] = [{"active": True, "external_id": observed["folder_id"], "session_id": "S1", "trainee_id": "T1"}]
    observed.update(email="changed@example.invalid")
    result = build_comparison(local, observed)
    assert result["status"] == "found"
    assert result["candidates"][0]["email_match"] is False
    local["wedof_links"].append(copy.deepcopy(local["wedof_links"][0]))
    assert build_comparison(local, observed)["status"] == "ambiguous_link"
    local["wedof_links"].pop()
    local["wedof_links"][0]["trainee_id"] = "missing"
    assert build_comparison(local, observed)["status"] == "stale"


def test_results_are_bounded_counts_are_complete_and_concordant_candidate_is_first(observed, local):
    groups = []
    for index in range(12):
        group = copy.deepcopy(local["sessions"][0])
        group["id"] = f"S{index}"
        group["trainees"][0]["email"] = "different@example.invalid"
        groups.append(group)
    groups[-1]["trainees"][0]["email"] = observed["email"]
    local["sessions"] = groups
    result = build_comparison(local, observed)
    assert result["candidate_count"] == result["matching_session_count"] == 12
    assert len(result["candidates"]) == len(result["matching_sessions"]) == MAX_CANDIDATES
    assert result["candidates"][0]["session_id"] == "S11"
    assert result["status"] == "ambiguous"


def test_missing_ids_never_produce_a_concordant_proposal(observed, local):
    del local["sessions"][0]["trainees"][0]["id"]
    result = build_comparison(local, observed)
    assert result["status"] == "review"
    assert "identifiant local" in result["candidates"][0]["issues"][0]


def test_absent_data_and_malformed_data_are_distinct(observed):
    result = build_comparison({}, observed)
    assert result["status"] == "absent" and result["registration_count"] == 0
    for bad in ([], {"sessions": {}}, {"sessions": None}, {"wedof_links": None}):
        with pytest.raises(ValueError):
            build_comparison(bad, observed)
