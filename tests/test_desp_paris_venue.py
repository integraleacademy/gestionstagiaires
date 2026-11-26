"""The receiving DESP session selects the in-person venue across all delivery paths."""
import copy
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

import app as host
import company_convention
import desp_paris_venue as venue
import training_convocations


PERSON = {"id": "T1", "first_name": "Camille", "last_name": "Exemple",
          "email": "camille@example.invalid", "public_token": "test-paris"}
JANUARY = {"id": "S1", "training_type": "DIRIGEANT initial", "name": "DESP Paris",
           "date_start": "2027-01-01", "date_end": "2027-02-18", "exam_date": "2027-02-19"}


@pytest.mark.parametrize("changes,applies", [
    ({}, True),
    ({"date_start": "2026-12-31"}, False),
    ({"date_start": "", "date_debut": "01/01/2027"}, True),
    ({"date_start": "", "dirigeant_remote_start": "2027-01-01"}, True),
    ({"date_start": "", "dirigeant_in_person_start": "2027-01-15"}, False),
    ({"dirigeant_remote_start": "2026-12-28", "dirigeant_in_person_start": "2027-02-08"}, False),
    ({"name": "Session de janvier", "crm_center": "Paris"}, True),
    ({"name": "DESP Puget-sur-Argens"}, False),
    ({"centre": "Côte d’Azur"}, False),
    ({"training_type": "DIRIGEANT VAE"}, False),
    ({"training_type": "MAC DESP"}, False),
    ({"training_type": "", "type_formation": "DIRIGEANT", "nom": "DESP Paris", "name": ""}, True),
    ({"partner_id": "autre-centre"}, False),
])
def test_cutover_uses_the_session_start_and_centre(changes, applies):
    training = {**JANUARY, **changes}
    config = host._automation_document_config(training)
    assert venue.applies(training) is applies
    assert (config.get("convocation_template") == "convocationdespparis_2027.docx") is applies


@pytest.mark.parametrize("start,expected", [("2026-12-31", venue.LEGACY), ("2027-01-01", venue.FULL_ADDRESS)])
def test_contract_company_and_attestations_use_the_same_venue(tmp_path, start, expected):
    training = {**JANUARY, "date_start": start}
    with host.app.test_request_context("/"):
        values = host._aps_convention_replacements(training, PERSON)
        models = [(host._aps_convention_template_path(training), values),
                  (host._aps_entry_attestation_template_path(training), host._build_aps_entry_attestation_context(training, PERSON)),
                  (host._aps_end_attestation_template_path(training), host._build_aps_end_attestation_context(training, PERSON))]
    company = dict(name="Entreprise", address="Paris", representative="Camille Exemple", remote_rate="71,43", payment="Virement.")
    company_path = tmp_path / "company-template.docx"
    company_convention.build_document(models[0][0], company, values).save(company_path)
    for index, (template, context) in enumerate(models + [(company_path, values)]):
        output = tmp_path / f"generated-{index}.docx"
        output.write_bytes(Path(template).read_bytes())
        host._replace_docx_xml_placeholders(str(output), context, training_header=index in (1, 2))
        with ZipFile(output) as package:
            body = "".join(etree.fromstring(package.read("word/document.xml")).itertext())
            assert expected in body and "{{ lieu_presentiel_paris }}" not in body
            if start.startswith("2027"):
                assert "Vinaigriers" not in body
            if index in (0, 3):
                assert "Effectif minimal" in body and "présentiel à Paris" in body
        if start.startswith("2027") and index in (1, 2):
            assert venue.STREET in "".join(Document(output).sections[0].header._element.itertext())


def test_old_issued_convocation_gets_a_new_revision_and_exam_reads_the_new_venue():
    person = {**PERSON, "lieu_formation": venue.LEGACY}
    with host.app.test_request_context("/"):
        context = host._build_aps_convocation_context(JANUARY, person)
        assert context["lieu_formation"] == context["lieu_examen"] == venue.FULL_ADDRESS
        assert context["acces_metro"] == venue.PRIMARY_METRO
        old_hash = training_convocations.source_hash(context, Path(host.app.root_path) / "templates_word/convocationdespparis.docx")
        assert training_convocations.current_source_hash(host, JANUARY, person) != old_hash
    training = {**JANUARY, "security_exam": {"config": {"location": "Atelier Modulable", "address": "53 rue des Vinaigriers"}}}
    assert host.ssiap_exam.settings(training)["address"] == venue.ADDRESS


@pytest.mark.parametrize("start,visible", [("2026-12-31", False), ("2027-01-01", True)])
def test_student_can_find_the_venue_before_documents_are_issued(monkeypatch, tmp_path, start, visible):
    training = {**JANUARY, "date_start": start, "trainees": [copy.deepcopy(PERSON)]}
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"sessions": [training]}))
    monkeypatch.setattr(host, "DATA_FILE", str(data_file))
    monkeypatch.setattr(host, "load_data", lambda **kwargs: json.loads(data_file.read_text()))
    monkeypatch.setattr(host, "_partner_postgres_active", lambda: False)
    monkeypatch.setattr(host, "_atomic_update_data", lambda update: update(json.loads(data_file.read_text())))
    client = host.app.test_client()
    with client.session_transaction() as auth:
        auth["public_auth_test-paris"] = True
    response = client.get("/espace/test-paris")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    for value in (venue.STREET, venue.LANDMARK, "Ouvrir l’itinéraire", venue.MAP_FILE):
        assert (value in body) is visible
