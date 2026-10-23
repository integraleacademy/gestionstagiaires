from afc_positioning import allocation, matched_result


def cohort():
    return [{"id": f"T{i:02}", "last_name": f"Candidat{i:02}", "first_name": "Émilie",
             "email": f"candidat{i}@example.test", "phone": f"06000000{i:02}"}
            for i in range(12)]


def results(rows):
    points = [44, 39, 38, 39, 37, 42, 38, 41, 48, 49, 49, 45]
    return [{"id": f"TEST{i}", "contact": dict(row), "created_at": "2026-10-14T10:00:00Z",
             "score": points[i], "total": 60} for i, row in enumerate(rows)]


def test_exact_8_2_2_by_score_with_inverted_names_and_same_group_ties():
    rows = cohort()
    tests = results(rows)
    contact = tests[6]["contact"]
    contact["last_name"], contact["first_name"] = contact["first_name"], contact["last_name"]
    result = allocation(rows, tests, {"54": 8, "40": 2, "0": 2})
    assert not result["issue"]
    assert result["profiles"] == {row["id"]: 54 if i < 8 else 40 if i in (8, 11) else 0
                                   for i, row in enumerate(rows)}
    assert result["scores"]["T06"]["score"] == 38


def test_latest_valid_score_is_used_even_zero_and_older_high_score_ignored():
    rows = cohort()
    tests = results(rows)
    tests.append({**tests[0], "id": "LATEST", "created_at": "2026-10-15T00:00:00Z", "score": 0})
    latest = matched_result(rows[0], rows, tests)
    assert latest["id"] == "LATEST" and latest["score"] == 0


def test_missing_result_is_never_treated_as_zero():
    rows = cohort()
    result = allocation(rows, results(rows)[1:], {"54": 8, "40": 2, "0": 2})
    assert result["profiles"] is None
    assert result["scores"]["T00"] is None


def test_boundary_tie_requires_a_choice_instead_of_alphabetical_assignment():
    rows = cohort()
    tests = results(rows)
    tests[11]["score"] = 44
    result = allocation(rows, tests, {"54": 8, "40": 2, "0": 2})
    assert result["profiles"] is None and "ex æquo" in result["issue"]


def test_shared_contact_does_not_match_a_different_name():
    rows = cohort()
    tests = results(rows)
    tests[0]["contact"]["last_name"] = "Autre"
    assert matched_result(rows[0], rows, tests) is None


def test_same_name_requires_contact_and_duplicate_test_cannot_serve_two_people():
    rows = cohort()
    rows[1] = {**rows[0], "id": "T01", "email": "other@example.test", "phone": ""}
    tests = results(rows)
    tests.pop(1)
    assert matched_result(rows[1], rows, tests) is None
    rows[1]["email"] = rows[0]["email"]
    result = allocation(rows, tests, {"54": 8, "40": 2, "0": 2})
    assert result["profiles"] is None and "plusieurs candidats" in result["issue"]


def test_normalized_scores_use_full_precision_and_invalid_scores_block_allocation():
    rows = cohort()
    tests = results(rows)
    tests[0].update(score=88, total=120)
    result = allocation(rows, tests, {"54": 8, "40": 2, "0": 2})
    assert result["profiles"]["T00"] == 54
    for score, total in [(None, 60), (61, 60), (-1, 60), (1, 0), (float('nan'), 60)]:
        tests[0].update(score=score, total=total)
        assert allocation(rows, tests, {"54": 8, "40": 2, "0": 2})["profiles"] is None
