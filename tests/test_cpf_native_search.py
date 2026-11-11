"""Native lookup keeps decisions and associations in the trainee sheet."""
import json

import edof_directory
from test_integrale_edof_dashboard import site

HEADERS = {"Accept": "application/json"}
SEARCH = "/admin/edof-test/inscriptions/s1/t1/recherche-cpf"
MATCH = "/admin/edof-test/inscriptions/s1/t1/rapprocher-cpf"


def records(site, rows):
    site.vault.put(edof_directory.record_key(site.owner), {"checked": 10000, "rows": rows})


def exact_row(site, folder="100000", **changes):
    row = site.vault.get(edof_directory.record_key(site.owner))["rows"]["100000"]
    return {**row, "folder_id":folder, "email":"anne@example.invalid", **changes}


def test_json_search_is_read_only_and_supports_partial_names(site):
    site.gate.switch("integrale", 0, "admin")
    before = site.local.read_text()
    reply = site.client.get(SEARCH + "?q=exem", headers=HEADERS)
    assert reply.status_code == 200
    assert reply.json["total"] == 2
    assert reply.json["csrf"] == site.csrf
    assert all(item["can_associate"] for item in reply.json["candidates"])
    assert site.local.read_text() == before
    assert site.client.get(SEARCH + "?q=introuvable", headers=HEADERS).json["total"] == 0


def test_inline_match_only_links_target_and_repeated_click_is_idempotent(site):
    site.gate.switch("integrale", 0, "admin")
    data = json.loads(site.local.read_text())
    data["sessions"][0]["trainees"].append({"id":"t2", "first_name":"Paul", "last_name":"Exemple", "email":"paul@example.invalid"})
    site.local.write_text(json.dumps(data))
    records(site, {"100000":exact_row(site), "100004":exact_row(site, "100004", first_name="Paul", email="paul@example.invalid")})
    for _ in range(2):
        reply = site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS)
        assert reply.status_code == 200 and reply.json["status"] == "associated"
        assert reply.json["external_id"] == "100000"
    links = json.loads(site.local.read_text())["wedof_links"]
    assert [(link["external_id"], link["trainee_id"]) for link in links] == [("100000", "t1")]


def test_inline_match_keeps_ambiguity_and_dates_for_manual_choice(site):
    site.gate.switch("integrale", 0, "admin")
    row = exact_row(site)
    records(site, {"100000":row, "100004":{**row, "folder_id":"100004"}})
    reply = site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS)
    assert reply.json["status"] == "unlinked"
    assert not json.loads(site.local.read_text()).get("wedof_links")
    records(site, {"100000":{**row, "session_end_date":"2026-03-01"}})
    assert site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS).json["status"] == "unlinked"
    candidate = site.client.get(SEARCH, headers=HEADERS).json["candidates"][0]
    assert candidate["confirm_dates"] and candidate["can_associate"]
    form = {"csrf":site.csrf, "session_id":"s1", "trainee_id":"t1", "verified":"yes"}
    assert site.client.post(candidate["associate_url"], data=form, headers=HEADERS).status_code == 409
    form["confirm_date_mismatch"] = "1"
    assert site.client.post(candidate["associate_url"], data=form, headers=HEADERS).json["ok"]


def test_inline_match_respects_csrf_provider_and_missing_registration(site):
    records(site, {"100000":exact_row(site)})
    assert site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS).status_code == 409
    site.gate.switch("integrale", 0, "admin")
    assert site.client.post(MATCH, headers=HEADERS).status_code == 403
    assert site.client.post(MATCH.replace("t1/", "missing/"), data={"csrf":site.csrf}, headers=HEADERS).status_code == 404
    with site.client.session_transaction() as session:
        session["admin_role"] = "viewer"
    assert site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS).status_code == 403
    assert not json.loads(site.local.read_text()).get("wedof_links")


def test_json_search_bounds_results_and_reports_occupied_registration(site):
    site.gate.switch("integrale", 0, "admin")
    row = exact_row(site)
    records(site, {str(200000+i):{**row, "folder_id":str(200000+i)} for i in range(30)})
    page = site.client.get(SEARCH, headers=HEADERS).json
    second = site.client.get(SEARCH + "?page=2", headers=HEADERS).json
    assert page["total"] == 30 and len(page["candidates"]) == 25 and len(second["candidates"]) == 5
    assert not {i["folder_id"] for i in page["candidates"]} & {i["folder_id"] for i in second["candidates"]}
    data = json.loads(site.local.read_text())
    data["wedof_links"] = [{"external_id":"999999", "session_id":"s1", "trainee_id":"t1", "active":True}]
    site.local.write_text(json.dumps(data))
    occupied = site.client.get(SEARCH, headers=HEADERS).json
    assert all(not item["can_associate"] and item["issues"] for item in occupied["candidates"])


def test_vtc_uses_each_trainees_real_period_without_changing_the_group(site):
    site.gate.switch("integrale", 0, "admin")
    row = exact_row(site, session_start_date="2026-11-26", session_end_date="2026-12-26")
    records(site, {"100000":row})
    data = json.loads(site.local.read_text())
    group = data["sessions"][0]
    group.update(training_type="VTC", date_start="2026-09-12", date_end="2026-11-20")
    group["trainees"][0]["vtc_real_training_dates"] = "26/11/2026 au 26/12/2026"
    group["trainees"].append({"id":"other", "first_name":"Anne", "last_name":"Exemple", "email":"anne@example.invalid",
                              "vtc_real_training_dates":"01/12/2026 au 31/12/2026"})
    site.local.write_text(json.dumps(data))
    candidate = site.client.get(SEARCH, headers=HEADERS).json["candidates"][0]
    assert not candidate["confirm_dates"]
    assert next(c["matches"] for c in candidate["checks"] if c["key"] == "dates") is True
    reply = site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS)
    assert reply.json["status"] == "associated"
    after = json.loads(site.local.read_text())
    assert after["sessions"] == data["sessions"]
    assert after["wedof_links"][0]["trainee_id"] == "t1"


def test_invalid_vtc_period_or_missing_contact_never_becomes_automatic_match(site):
    site.gate.switch("integrale", 0, "admin")
    row = exact_row(site)
    data = json.loads(site.local.read_text())
    data["sessions"][0]["training_type"] = "VTC"
    for period, email in [("06/02/2026 au 02/02/2026", row["email"]), ("à définir", row["email"]),
                          ("02/02/2026 au 06/02/2026", "")]:
        data["sessions"][0]["trainees"][0]["vtc_real_training_dates"] = period
        site.local.write_text(json.dumps(data))
        records(site, {"100000":{**row, "email":email}})
        reply = site.client.post(MATCH, data={"csrf":site.csrf}, headers=HEADERS)
        assert reply.json["status"] == "unlinked"
        assert not json.loads(site.local.read_text()).get("wedof_links")
