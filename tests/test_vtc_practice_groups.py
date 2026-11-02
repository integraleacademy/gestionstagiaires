from collections import Counter
from copy import deepcopy
from unittest.mock import Mock
from zipfile import ZipFile

from lxml import etree, html
import pytest

import app
import training_convocations
import vtc_practice


DAY = "2026-10-21"
SLOTS = [{"start": "08:30", "end": "12:00"}, {"start": "13:30", "end": "17:00"}]


def training(size):
    trainees = [{"id": f"T{i:02}", "first_name": f"Camille{i}", "last_name": "EXEMPLE",
                 "email": f"camille{i}@example.test", "phone": "0600000000", "public_token": f"public{i}"}
                for i in range(size)]
    return {"id": "S1", "partner_id": app.INTEGRALE_PARTNER_ID, "training_type": "VTC", "name": "Chauffeur VTC",
            "date_start": "2026-09-01", "date_end": "2026-09-30", "trainees": trainees,
            "exam_theory_date": "2026-10-02", "practice_training_date": DAY, "exam_practice_date": "2026-11-12"}


@pytest.fixture
def case(monkeypatch):
    data = {"sessions": [training(9)]}
    monkeypatch.setattr(app, "load_data", lambda **kw: deepcopy(data))
    monkeypatch.setattr(app, "save_data", Mock())
    monkeypatch.setattr(app, "_atomic_update_data", lambda mutate: mutate(data))
    client = app.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role="admin")
    return data["sessions"][0], client


def post(client, slots=SLOTS, **extra):
    return client.post("/api/sessions/S1/update", json={"vtc_practice_slots": slots, **extra})


@pytest.mark.parametrize("kind,size,cancelled,allowed", [
    ("VTC", 8, 0, False), ("VTC", 9, 1, False), ("APS", 12, 0, False),
    ("VTC", 9, 0, True), ("CHAUFFEUR VTC", 12, 0, True)])
def test_threshold_in_session_editor_and_api(case, kind, size, cancelled, allowed):
    session, client = case
    session.update(training(size), training_type=kind)
    if cancelled:
        session["trainees"][-1]["registration_canceled"] = "oui"
    page = html.fromstring(client.get("/admin/sessions").data)
    button = page.xpath('//*[@data-edit-session="S1"]')[0]
    assert ("data-vtc-slots" in button.attrib) == allowed
    response = post(client)
    if allowed:
        assert response.status_code == 200
        groups = session[vtc_practice.KEY]["members"]
        assert Counter(groups.values()) == {1: (size + 1) // 2, 2: size // 2}
    else:
        assert response.status_code == 400
        assert vtc_practice.KEY not in session


@pytest.mark.parametrize("slots", [
    [{**SLOTS[0], "start": "27:30"}, SLOTS[1]], [SLOTS[0], {**SLOTS[1], "end": "12:00"}],
    [SLOTS[0], {**SLOTS[1], "start": "11:00"}], [SLOTS[0], {**SLOTS[1], "date": "2026-02-30"}], []])
def test_invalid_slots_do_not_partially_update_session(case, slots):
    session, client = case
    before = deepcopy(session)
    assert post(client, slots, name="Modifiée").status_code == 400
    assert session == before


def test_membership_survives_roster_changes_and_stale_saves(case):
    session, client = case
    stale = deepcopy(session)
    assert post(client).status_code == 200
    members = dict(session[vtc_practice.KEY]["members"])
    stale["trainees"].reverse()
    stale["trainees"].append({"id": "new", "created_at": "2026-10-02"})
    vtc_practice.reconcile({"sessions": [stale]}, app._registered_trainees, {"sessions": [session]})
    assert stale[vtc_practice.KEY]["members"] == {**members, "new": 2}
    session["trainees"][0]["registration_cancelled"] = True
    session["trainees"].reverse()
    assert post(client, [SLOTS[0], {**SLOTS[1], "start": "14:00"}]).status_code == 200
    assert session[vtc_practice.KEY]["members"] == members
    assert post(client, None).status_code == 200
    assert vtc_practice.KEY not in session
    assert post(client).status_code == 400
    vtc_practice.reconcile({"sessions": [stale]}, app._registered_trainees, {"sessions": [session]})
    assert vtc_practice.KEY not in stale


def test_two_individual_documents_messages_and_views(case, tmp_path, monkeypatch):
    session, client = case
    second = {**SLOTS[1], "date": "2026-10-22"}
    assert post(client, [SLOTS[0], second]).status_code == 200
    email = Mock(return_value=True)
    sms = Mock(return_value=True)
    monkeypatch.setattr(app, "brevo_send_email", email)
    monkeypatch.setattr(app, "brevo_send_sms", sms)
    attachment = tmp_path / "convocation.pdf"
    attachment.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(app, "_generate_aps_convocation_files", lambda *args: ("generated.docx", str(attachment)))
    roster = html.fromstring(client.get("/admin/sessions/S1/trainees").data)
    for i, date, start, end, other in [(0, "21/10/2026", "08h30", "12h00", "13h30"),
                                       (1, "22/10/2026", "13h30", "17h00", "08h30")]:
        trainee = session["trainees"][i]
        group = i + 1
        context = app._build_aps_convocation_context(session, trainee)
        docx = tmp_path / f"groupe-{group}.docx"
        app._render_docx_with_python_template(app._aps_template_path(session), str(docx), context)
        with ZipFile(docx) as doc:
            document = etree.fromstring(doc.read("word/document.xml"))
            text = "".join(document.xpath('//*[local-name()="t"]/text()'))
        assert f"{date} de {start} à {end}" in text and "3 h 30" in text
        assert other not in text and "Matinée" not in text and f"Groupe {group}" in text
        app._send_vtc_theory_exam_notification(session, trainee)
        for message in (email.call_args.args[2], sms.call_args.args[1],
                        app._build_aps_convocation_email(trainee["first_name"], session_obj=session, trainee=trainee)[1]):
            assert f"de {start} à {end}" in message and date in message and other not in message
        assert "attachments" in email.call_args.kwargs
        public = html.fromstring(client.get(f"/espace/{trainee['public_token']}").data)
        assert start in public.xpath('//*[@data-vtc-date="practice_training"]')[0].text_content()
        row = roster.xpath(f'//tr[@data-trainee-id="{trainee["id"]}"]')[0]
        assert f"Groupe {group}" in row.text_content() and start in row.text_content()
        assert context["date_examen_pratique"] == "12/11/2026"


def test_changing_one_slot_refreshes_only_affected_documents(case):
    session, client = case
    assert post(client).status_code == 200
    def revisions():
        return [training_convocations.current_source_hash(app, session, t) for t in session["trainees"][:2]]
    previous = revisions()
    assert post(client, [SLOTS[0], {**SLOTS[1], "start": "14:00"}]).status_code == 200
    current = revisions()
    assert previous[0] == current[0] and previous[1] != current[1]

def test_legacy_roster_has_stable_ids_and_excludes_cancelled_registrations(case):
    session, client = case
    session.pop("trainees")
    session["type_formation"] = session.pop("training_type")
    session["stagiaires"] = [{"nom": f"Ancien{i}", "prenom": "Camille"} for i in range(10)]
    session["stagiaires"][-1]["inscription_annulee"] = "oui"
    assert post(client).status_code == 200
    active = app._registered_trainees(session)
    assert len(active) == 9
    assert set(session[vtc_practice.KEY]["members"]) == {t["id"] for t in active}
    assert active == app._registered_trainees(session)
