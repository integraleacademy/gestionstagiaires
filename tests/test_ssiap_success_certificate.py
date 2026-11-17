import io
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

import app
import ssiap_success_certificate as success


def cohort():
    return {"id":"s", "name":"SSIAP 1 automne", "training_type":"SSIAP",
            "date_start":"2026-10-05", "date_end":"2026-10-16", "exam_date":"2026-10-19",
            "trainees":[{"id":"t", "public_token":"un-exemple", "first_name":"Camille", "last_name":"Exemple",
                         "ssiap_exam_status":"certified", "public_has_logged_in":True, "documents":[]}]}


def test_only_the_authenticated_certified_ssiap1_candidate_can_get_an_up_to_date_attestation(monkeypatch):
    training = cohort()
    trainee = training["trainees"][0]
    monkeypatch.setattr(app, "load_data", lambda **kwargs:{"sessions":[training]})
    monkeypatch.setattr(app, "_atomic_update_data", lambda update: update({"sessions": [training]}))
    client = app.app.test_client()
    url = "/espace/un-exemple/attestation-reussite-ssiap-1.pdf"
    assert client.get(url).status_code == 302
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
    assert url in client.get("/espace/un-exemple").text
    response = client.get(url)
    assert response.status_code == 200 and "no-store" in response.headers["Cache-Control"]
    pdf = PdfReader(io.BytesIO(response.data))
    assert len(pdf.pages) == 1 and len(pdf.pages[0].images) >= 3
    text = pdf.pages[0].extract_text()
    for term in ("Camille EXEMPLE", "05/10/2026", "16/10/2026", "19/10/2026", "faire valoir ce que de droit",
                 "83-23", "93 83 06002 83", "840 899 884 00026"):
        assert term in text
    trainee["ssiap_diploma_exam_date"] = "2026-10-21"
    assert "21/10/2026" in PdfReader(io.BytesIO(client.get(url).data)).pages[0].extract_text()
    trainee["ssiap_exam_status"] = "failed"
    assert client.get(url).status_code == 404 and url not in client.get("/espace/un-exemple").text


@pytest.mark.parametrize("change", [
    {"training_type":"SSIAP 2"}, {"name":"SSIAP 3"}, {"training_type":"VTC"},
    {"training_type":"AFC APS + SSIAP 1"}, {"name":"Remise à niveau SSIAP 1"}, {"name":"Recyclage SSIAP 1"},
    {"exam_date":""}, {"date_start":""}, {"partner_id":"autre-centre"},
])
def test_excludes_other_courses_and_unconfirmed_dates(change):
    group = cohort()
    group.update(change)
    assert success.document_fields(app, group, group["trainees"][0]) is None


def test_combined_ssiap_sst_uses_the_trainees_own_dates():
    group = cohort()
    group["ssiap_pathways"] = {"sst_dates":["2026-10-01","2026-10-02"]}
    trainee = group["trainees"][0]
    assert success.document_fields(app, group, trainee)["start"] == "05/10/2026"
    trainee["ssiap_pathway"] = "ssiap_sst"
    assert success.document_fields(app, group, trainee)["start"] == "01/10/2026"


def test_successful_retake_is_available_in_original_space_only(tmp_path, monkeypatch):
    import exam_retakes
    monkeypatch.setattr(app, "PERSIST_DIR", str(tmp_path))
    original = cohort()
    trainee = original["trainees"][0]
    trainee["ssiap_exam_status"] = "failed"
    target = {**cohort(), "id": "november", "exam_date": "2026-11-13", "trainees": [],
              "ssiap_exam": {"retake_results": {"retake-r1": {"ssiap_exam_status": "certified"}}}}
    data = {"sessions": [original, target]}
    record = {"id": "r1", "source_session": "s", "trainee_id": "t", "target_session": "november",
              "status": "confirmed", "kind": "SSIAP 1", "exam_date": "2026-11-13", "signed_at": "2026-11-01",
              "total_cents": 0, "payment_status": "not_required"}
    store = exam_retakes.Store(app)
    store.save(record)
    fields = success.document_fields(app, original, trainee, data=data)
    assert fields["exam"] == "13/11/2026" and fields["start"] == "05/10/2026"
    assert trainee["ssiap_exam_status"] == "failed"
    other = {**trainee, "id": "other"}
    assert success.document_fields(app, original, other, data=data) is None
    target["ssiap_exam"]["retake_results"]["retake-r1"]["ssiap_exam_status"] = "failed"
    assert success.document_fields(app, original, trainee, data=data) is None
    target["ssiap_exam"]["retake_results"]["retake-r1"]["ssiap_exam_status"] = "certified"
    record["status"] = "cancelled"
    store.save(record)
    assert success.document_fields(app, original, trainee, data=data) is None
