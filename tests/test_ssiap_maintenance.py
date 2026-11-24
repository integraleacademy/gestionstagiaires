import copy

import pytest

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
    t.update(ssiap_original_diploma="D-EXEMPLE",birth_date="1990-04-01",birth_city="Lyon")
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
    roster = client.get("/admin/sessions/S1/trainees")
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
