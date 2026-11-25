import copy
from pathlib import Path

import pytest
from lxml import html
from docx import Document

import app as gestion
import edof_matching
import integrale_edof_registration
import ssiap_exam
import ssiap_pathways as paths


@pytest.fixture
def group(monkeypatch):
    training = dict(id="S1", name="SSIAP 1 – Puget", training_type="SSIAP",
                    date_start="2026-11-09", date_end="2026-11-20", exam_date="2026-11-23",
                    trainees=[], partner_id=gestion.INTEGRALE_PARTNER_ID)
    training["ssiap_pathways"] = paths.validate(training, {
        "recyclage_dates":["2026-11-19","2026-11-20"],
        "remise_a_niveau_dates":["2026-11-18","2026-11-19","2026-11-20"],
        "ssiap_price":"980",
    })
    data = {"sessions":[training]}
    monkeypatch.setattr(gestion, "load_data", lambda *a, **kw: data)
    monkeypatch.setattr(gestion, "save_data", lambda *a, **kw: None)
    monkeypatch.setattr(gestion, "_atomic_update_data", lambda fn: fn(data))
    monkeypatch.setattr(gestion, "brevo_send_email", lambda *a, **kw: pytest.fail("Unrequested email"))
    client = gestion.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    return training, client


def enrol(group, choice, **values):
    training, client = group
    result = client.post("/api/sessions/S1/trainees/create", json={
        "first_name":"Camille", "last_name":choice.upper(), "email":choice + "@example.test",
        "send_access":False, "ssiap_pathway":choice, **values})
    assert result.status_code == 200, result.get_json()
    return next(t for t in training["trainees"] if t["email"] == choice + "@example.test")


def convocation_text(training, trainee, output):
    template = gestion._ssiap_document_template(training, trainee, "convocation", gestion._aps_template_path)
    context = gestion._build_aps_convocation_context(training, trainee)
    gestion._render_docx_with_python_template(template, str(output), context)
    body = Document(output).element.body
    return " ".join(" ".join(body.xpath(".//w:t/text()")).split())


@pytest.mark.parametrize("choice,venue,expect_map", [
    ("recyclage", "", True),
    ("remise_a_niveau", "54 chemin du Carréou, 83480 Puget-sur-Argens", True),
    ("remise_a_niveau", "Salle A & B, 10 rue des Écoles, 15000 Aurillac", False),
])
def test_maintenance_convocation_uses_initial_design_and_its_own_schedule(group, tmp_path, choice, venue, expect_map):
    training, _ = group
    # The named days can be nonconsecutive within a longer SSIAP 1 session.
    training["ssiap_pathways"][choice + "_dates"][0] = "2026-11-12"
    trainee = enrol(group, choice)
    trainee["lieu_formation"] = venue
    text = convocation_text(training, trainee, tmp_path / "maintien.docx")
    initial = convocation_text(training, {**trainee, "ssiap_pathway": "ssiap"}, tmp_path / "initial.docx")
    for heading in ("CONVOCATION OFFICIELLE EN FORMATION", "DOCUMENTS ADMINISTRATIFS", "RÈGLES DE VIE EN FORMATION"):
        assert heading in text and heading in initial
    assert "CONVOCATION OFFICIELLE À L’EXAMEN" in initial and "23/11/2026" in initial
    assert "examen" not in text.lower() and "enveloppe timbrée" not in text
    assert "23/11/2026" not in text and "09/11/2026" not in text and "70 heures" not in text
    assert "{{" not in text and "{%" not in text
    assert paths.CHOICES[choice] in text
    days = training["ssiap_pathways"][choice + "_dates"]
    for day in days:
        assert gestion.fr_date(day) in text
    assert f"{len(days)} jours {7 * len(days)} heures" in text
    assert "08h30–12h30 / 13h30–16h30" in text
    assert paths.MAINTENANCE[choice]["requirements"] in text
    assert (venue or paths.PUGET_VENUE) in text
    assert ("PLAN D’ACCÈS & PARKINGS" in text) is expect_map
    assert "PLAN D’ACCÈS & PARKINGS" in initial


@pytest.mark.parametrize("month,start,end,first", [
    (2,"15","26",24), (6,None,"04",2), (9,"13","24",22), (11,"08","22",17)])
def test_published_programme_is_applied_to_its_session_only(month, start, end, first):
    date = lambda n: f"2027-{month:02}-{int(n):02}"
    session = {"training_type":"SSIAP", "name":"SSIAP 1", "date_start":date(start) if start else "2027-05-24", "date_end":date(end)}
    assert paths.settings(session)["remise_a_niveau_dates"] == [date(first+i) for i in range(3)]
    assert paths.settings(session)["recyclage_dates"] == [date(first+1),date(first+2)]
    assert paths.resolve(session, {}) is None
    for override in [{"name":"SSIAP 2"}, {"partner_id":"other"}, {"crm_center":"Paris"}]:
        assert not paths.settings({**session, **override})["recyclage_dates"]


@pytest.mark.parametrize("choice,price,hours,first", [("recyclage", "250", "14", "19"), ("remise_a_niveau", "350", "21", "18")])
def test_enrolment_documents_financing_and_completion(group, choice, price, hours, first):
    training, client = group
    t = enrol(group, choice, personal_amount=price)
    assert t["training_price"] == price
    base = f"/api/sessions/S1/stagiaires/{t['id']}"
    days = paths.resolve(training,t)["dates"]
    for build in (gestion._aps_convention_replacements, gestion._build_aps_convocation_context, gestion._build_aps_entry_attestation_context):
        ctx = build(training,t)
        assert (ctx["formation_nom"],ctx["h_total"],ctx["date_debut_formation"],ctx["date_examen"]) == (paths.CHOICES[choice],hours,first+"/11/2026","")
        assert len(ctx["dates_parcours"].split(", ")) == len(days)
    assert gestion._aps_convention_replacements(training,t)["montant_formation"] == price
    req = {d['key'] for d in t['documents']}
    med = next(d for d in t["documents"] if d["key"] == "certificat_medical_ssiap")
    assert not med.get("optional") and med["template_url_endpoint"] == "public_ssiap_medical_certificate_template"
    assert "obligatoire" in med["label"]
    assert "ssiap_original" in req and "attestation_secourisme_ssiap" in req
    assert ("ssiap_activite" in req) == (choice == "recyclage")
    line, = gestion.buildBillingLinesFromSessions([training])
    assert line["amountTTC"] == int(price) and line["dateStart"] == days[0] and line["dateEnd"] == days[-1]
    assert paths.CHOICES[choice] in gestion.qonto_invoice_item_label(line) and not line["examDate"]
    assert sum(gestion._split_amount_installments(line["amountTTC"], 3)) == pytest.approx(int(price))
    assert client.post(base+"/presence-ssiap",json={"day":"2026-11-09","status":"present"}).status_code == 400
    for d in days:
        assert client.post(base+"/presence-ssiap",json={"day":d,"status":"present"}).status_code == 200
    assert client.post(base+"/presence-ssiap",json={"day":days[-1],"status":"partial"}).status_code == 200
    with pytest.raises(ValueError,match="présence"):
        gestion._build_aps_end_attestation_context(training,t)
    client.post(base+"/presence-ssiap",json={"day":days[-1],"status":"present"})
    with pytest.raises(ValueError,match="diplôme"):
        gestion._build_aps_end_attestation_context(training,t)
    draft = gestion._build_aps_end_attestation_context(training, t, preview=True)
    assert draft["entete_attestation"] == "APERÇU" and "diplôme" in draft["mention_delivrance"]
    t.update(ssiap_original_diploma="D-EXEMPLE",birth_date="1990-04-01",birth_city="Lyon")
    assert gestion._build_aps_end_attestation_context(training, t)["entete_attestation"] == "ATTESTATION"
    assert gestion._build_aps_end_attestation_context(training,t)["diplome_origine"] == "D-EXEMPLE"
    assert client.post("/api/sessions/S1/update",json={"ssiap_pathways":{**training["ssiap_pathways"],choice+"_dates":[]}}).status_code == 400
    assert client.get("/admin/sessions/S1/parcours-ssiap").status_code == 200


def test_mixed_roster_only_lists_expected_trainees_and_initial_exam(group):
    training, client = group
    initial, rec, ran = [enrol(group,key) for key in ("ssiap","recyclage","remise_a_niveau")]
    for day, expected in [("2026-11-09",[initial]),("2026-11-18",[initial,ran]),("2026-11-19",[initial,rec,ran])]:
        response = client.get("/admin/sessions/S1/presences-ssiap?jour="+day)
        assert response.status_code == 200
        for t in (initial,rec,ran):
            assert (t["id"] in response.text) == (t in expected)
    assert [t["id"] for t in ssiap_exam.active_candidates(gestion,training)] == [initial["id"]]
    assert not ssiap_exam.candidate_settings(training, {**rec,"ssiap_exam_status":"certified"})["included"]
    assert not paths.expected_on(training, rec, "2026-11-23")
    training["ssiap_pathways"]["sst_dates"] = ["2026-11-24"]
    enrol(group, "ssiap_sst")
    initial.pop("ssiap_pathway")  # Legacy registration with no explicit selection.
    training["trainees"].append({**rec, "id":"cancelled", "registration_cancelled":True})
    roster = client.get("/admin/sessions/S1/trainees")
    header, = html.fromstring(roster.text).find_class('session-stats')
    assert {card.find_class('stat-title')[0].text: card.find_class('stat-value')[0].text
            for card in header.find_class('stat')} == {
        "Total inscrits": "4", "SSIAP seul": "1", "SSIAP + SST": "1",
        "Remise à niveau (RAN)": "1", "Recyclage": "1",
    }
    assert roster.status_code == 200 and "250 € TTC" in roster.text and "350 € TTC" in roster.text


def test_existing_dossier_personal_price_and_historical_documents(group):
    training, client = group
    t = enrol(group,"ssiap")
    t.update(convention_aps_pdf_path="/test/signed.pdf",cpf_amount="180")
    med = next(d for d in t["documents"] if d["key"] == "certificat_medical_ssiap")
    med["file"] = "existing.pdf"
    change = f"/api/sessions/S1/stagiaires/{t['id']}/parcours-ssiap"
    assert client.post(change,json={"ssiap_pathway":"recyclage","training_price":"225"}).status_code == 200
    assert (t["training_price"],t["cpf_amount"],t["convention_aps_pdf_path"]) == ("225","180","/test/signed.pdf")
    assert client.post(change,json={"ssiap_pathway":"remise_a_niveau"}).status_code == 200
    assert t["training_price"] == "350"
    assert next(d["file"] for d in t["documents"] if d["key"] == "certificat_medical_ssiap") == "existing.pdf"
    assert client.post(change,json={"ssiap_pathway":"ssiap"}).status_code == 200
    assert not next(d for d in t["documents"] if d["key"] == "certificat_medical_ssiap").get("optional")


@pytest.mark.parametrize("choice", ["recyclage", "remise_a_niveau"])
def test_existing_short_dossiers_refresh_medical_requirement_without_losing_files(group, choice):
    training, _ = group
    t = enrol(group, choice)
    med = next(d for d in t["documents"] if d["key"] == "certificat_medical_ssiap")
    med.update(optional=True, label="Si vous n’exercez pas", file="deja-depose.pdf", status="CONFORME")
    gestion.ensure_documents_schema_for_trainee(t, training["training_type"])
    assert not med.get("optional") and "obligatoire" in med["label"]
    assert (med["file"], med["status"]) == ("deja-depose.pdf", "CONFORME")
    t["documents"].remove(med)
    gestion.ensure_documents_schema_for_trainee(t, training["training_type"])
    missing = next(d for d in t["documents"] if d["key"] == "certificat_medical_ssiap")
    assert not missing.get("optional") and missing["status"] == "NON DÉPOSÉ"


def test_edof_matching_uses_the_registered_path_dates(group):
    training, _ = group
    t=enrol(group,"recyclage")
    assert edof_matching.registration_dates(training,t) == ("2026-11-19","2026-11-20")
    row={"title":"Recyclage SSIAP 1","session_start_date":"2026-11-19","session_end_date":"2026-11-20"}
    options=integrale_edof_registration.matching_sessions({"sessions":[training]},gestion.INTEGRALE_PARTNER_ID,row,today="2026-12-01")
    assert len(options)==1 and options[0]["dates_match"]
    assert not integrale_edof_registration.matching_sessions({"sessions":[training]},gestion.INTEGRALE_PARTNER_ID,
            {**row,"title":"Remise à niveau SSIAP 1"},today="2026-12-01")
    before=copy.deepcopy(training)
    with pytest.raises(ValueError):
        paths.validate(training, {**training["ssiap_pathways"],"recyclage_dates":["2026-11-19","2026-11-19"]})
    assert before==training


@pytest.mark.parametrize("choice,override,expected", [
    ("remise_a_niveau", "", "350"), ("remise_a_niveau", "325", "325"), ("recyclage", "", "250"),
])
def test_edof_course_price_and_reviewed_convention_split(group, monkeypatch, choice, override, expected):
    training, client = group
    days = training["ssiap_pathways"][choice + "_dates"]
    fields = {"folder_id":"100000", "state":"accepted", "first_name":"Camille", "last_name":"Exemple",
              "title":paths.CHOICES[choice], "session_start_date":days[0], "session_end_date":days[-1],
              "total_incl":"220.00"}
    monkeypatch.setitem(gestion.app.extensions, "edof_registration_prefill", lambda folder, sid: fields)
    response = client.post("/api/sessions/S1/trainees/create", json={"first_name":"Camille", "last_name":"Exemple",
        "edof_folder":"100000", "training_price":override, "send_access":False})
    assert response.status_code == 200, response.json
    trainee = training["trainees"][0]
    assert response.json["training_price"] == trainee["training_price"] == expected
    assert trainee["ssiap_pathway"] == choice and trainee["edof_registration"]["total_incl"] == "220.00"
    assert not trainee["cpf_amount"] and not trainee["personal_amount"]
    personal = str(int(expected) - 220)
    result = client.post(response.json["convention_financing_url"], json={
        "training_price":expected, "cpf_amount":"220", "personal_amount":personal, "other_amount":""})
    assert result.status_code == 200, result.json
    assert (trainee["training_price"], trainee["cpf_amount"], trainee["personal_amount"]) == (expected, "220", personal)
    assert gestion._aps_convention_replacements(training, trainee)["montant_formation"] == expected


def test_unbilled_personal_share_follows_price_and_an_issued_invoice_keeps_its_amount(group):
    training, client = group
    t = enrol(group, "ssiap", personal_amount="980")
    change = f"/api/sessions/S1/stagiaires/{t['id']}/parcours-ssiap"
    assert client.post(change, json={"ssiap_pathway":"recyclage"}).status_code == 200
    assert t["personal_amount"] == "250"
    with gestion.app.test_request_context():
        data = gestion.load_data()
    data["billing_lines"] = [{"id":"invoice","sessionId":"S1","traineeId":t["id"],"qontoInvoiceId":"issued"}]
    assert client.post(change, json={"ssiap_pathway":"remise_a_niveau"}).status_code == 200
    assert t["training_price"] == "350" and t["personal_amount"] == "250"


@pytest.mark.parametrize("choice", ["recyclage", "remise_a_niveau"])
def test_short_attestations_reuse_initial_branding_and_render_individual_fields(group, choice, tmp_path):
    from zipfile import ZipFile

    training, client = group
    trainee = enrol(group, choice)
    dates = training["ssiap_pathways"][choice + "_dates"]
    trainee.update(ssiap_original_diploma="NUM-ORIGINE", birth_date="1990-04-01", birth_city="Lyon",
                   ssiap_attendance={day: "present" for day in dates}, lieu_formation="Salle du centre")
    for kind, fallback, build in [("entry", gestion._aps_entry_attestation_template_path, gestion._build_aps_entry_attestation_context),
                                  ("end", gestion._aps_end_attestation_template_path, gestion._build_aps_end_attestation_context)]:
        template = gestion._ssiap_document_template(training, trainee, kind, fallback)
        with ZipFile(fallback(training)) as initial, ZipFile(template) as adapted:
            for asset in initial.namelist():
                if asset.startswith(("word/media/", "word/header", "word/footer")) or asset == "word/styles.xml":
                    assert adapted.read(asset) == initial.read(asset)
        document = tmp_path / (kind + ".docx")
        document.write_bytes(Path(template).read_bytes())
        gestion._replace_docx_xml_placeholders(str(document), build(training, trainee))
        text = " ".join(Document(document).element.body.xpath(".//w:t/text()"))
        for target in [paths.CHOICES[choice], "Salle du centre", "08h30–12h30 / 13h30–16h30", *map(gestion.fr_date, dates)]:
            assert target in text
        assert "{{" not in text and "70 heures" not in text
        if kind == "end":
            assert "NUM-ORIGINE" in text and "Lyon" in text

    page = client.get(f"/admin/sessions/S1/stagiaires/{trainee['id']}")
    assert page.status_code == 200
    links = html.fromstring(page.text).xpath('//a[contains(@href, "/preview")]')
    for endpoint in ("convention", "convocation-aps", "attestation-entree-aps", "attestation-fin-aps"):
        matching = [a for a in links if a.get("href", "").endswith("/" + endpoint + "/preview")]
        assert matching and all(a.get("target") == "_blank" and "noopener" in a.get("rel", "").split() for a in matching)
        assert all("data-open-document-preview-modal" not in a.attrib for a in matching)
