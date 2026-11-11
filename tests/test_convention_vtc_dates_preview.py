import copy
from pathlib import Path
from unittest.mock import Mock

from docx import Document
from lxml import html
import pytest

import app


@pytest.fixture
def case(monkeypatch):
    trainee = {"id": "T-DATES", "first_name": "Camille", "last_name": "EXEMPLE",
               "email": "camille@example.test", "public_token": "preview-test",
               "vtc_real_training_dates": "26/11/2026 au 26/12/2026"}
    training = {"id": "S-DATES", "training_type": "CHAUFFEUR VTC", "name": "VTC DECEMBRE",
                "date_start": "2026-09-12", "date_end": "2026-11-20", "trainees": [trainee]}
    data = {"sessions": [training]}
    load = Mock(return_value=data)
    monkeypatch.setattr(app, "load_data", load)
    monkeypatch.setattr(app.admin_trainee_wedof_refresh, "schedule_refresh", Mock())
    client = app.app.test_client()
    with client.session_transaction() as auth:
        auth["admin_logged_in"] = True
        auth["admin_role"] = "admin"
    return training, trainee, client, load


@pytest.mark.parametrize("dates", ["26/11/2026 au 26/12/2026", "Du 26-11-2026 au 26-12-2026",
                                  "2026-11-26 → 2026-12-26"])
def test_vtc_convention_uses_real_dates_without_changing_the_session(case, dates, tmp_path):
    training, trainee, _, _ = case
    trainee["vtc_real_training_dates"] = dates
    before = copy.deepcopy(training)
    values = app._aps_convention_replacements(training, trainee)
    assert values["periode_formation"] == "du 26/11/2026 au 26/12/2026"
    assert values["date_debut_formation"] == values["date_debut"] == "26/11/2026"
    assert values["date_fin_formation"] == values["date_fin"] == "26/12/2026"
    assert values["date_un_mois_avant_debut_formation"] == "26/10/2026"
    assert training == before
    target = tmp_path / "convention.docx"
    target.write_bytes(Path("templates_word/conventionvtc.docx").read_bytes())
    app._replace_docx_xml_placeholders(str(target), values)
    text = "\n".join(p.text for p in app._iter_docx_paragraphs(Document(target)))
    assert text.count("26/11/2026 au 26/12/2026") >= 2
    assert "12/09/2026" not in text and "20/11/2026" not in text


@pytest.mark.parametrize("dates", ["", "à définir", "26/11/2026", "31/11/2026 au 26/12/2026",
                                  "26/12/2026 au 26/11/2026"])
def test_missing_or_invalid_vtc_dates_never_fall_back_to_session_dates(case, dates):
    training, trainee, _, _ = case
    trainee["vtc_real_training_dates"] = dates
    with pytest.raises(ValueError, match="Dates réelles de formation VTC"):
        app._aps_convention_replacements(training, trainee)


@pytest.mark.parametrize("course", ["APS", "A3P", "SSIAP 1", "DIRIGEANT INITIAL", "DIRIGEANT VAE"])
def test_other_courses_ignore_any_carried_over_vtc_dates(case, course):
    training, trainee, _, _ = case
    training.update(training_type=course, name=course)
    values = app._aps_convention_replacements(training, trainee)
    assert values["periode_formation"] == "du 12/09/2026 au 20/11/2026"


def test_preview_is_inline_fresh_and_leaves_the_sent_document_untouched(case, tmp_path, monkeypatch):
    training, trainee, client, load = case
    old = tmp_path / "sent.pdf"
    old.write_bytes(b"sent-original")
    trainee["convention_signature"] = {"status": "ongoing", "signature_request_id": "already-sent",
                                        "unsigned_pdf_path": str(old)}
    before = copy.deepcopy(trainee)
    save, send = Mock(), Mock()
    monkeypatch.setattr(app, "save_data", save)
    monkeypatch.setattr(app, "create_yousign_convention_signature", send)

    def generate(session, person, *ids, output_dir):
        values = app._aps_convention_replacements(session, person)
        pdf = Path(output_dir) / "preview.pdf"
        pdf.write_bytes(b"%PDF-1.4\n" + values["periode_formation"].encode())
        return str(pdf.with_suffix(".docx")), str(pdf)

    monkeypatch.setattr(app, "_generate_aps_convention_files", generate)
    monkeypatch.setattr(app, "_prepare_yousign_pdf_and_fields", lambda path: (path, []))
    response = client.get("/admin/sessions/S-DATES/stagiaires/T-DATES/convention/preview")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    assert response.headers["Content-Disposition"].startswith("inline;")
    assert "no-store" in response.headers["Cache-Control"]
    assert b"26/11/2026 au 26/12/2026" in response.data
    assert trainee == before and old.read_bytes() == b"sent-original"
    load.assert_called_once_with(run_background_tasks=False)
    save.assert_not_called()
    send.assert_not_called()


@pytest.mark.parametrize("course", ["VTC", "APS", "A3P", "SSIAP 1", "DIRIGEANT INITIAL", "DIRIGEANT VAE"])
@pytest.mark.parametrize("signed", [False, True])
def test_preview_button_opens_a_new_tab_for_every_training_type(case, course, signed):
    training, trainee, client, _ = case
    training.update(training_type=course, name=course)
    if signed:
        trainee["convention_legacy_signed_at"] = "2026-11-01T10:00:00Z"
    response = client.get("/admin/sessions/S-DATES/stagiaires/T-DATES")
    assert response.status_code == 200
    page = html.fromstring(response.data)
    button, = page.xpath('//a[contains(@class,"automation-preview-convention")]')
    assert "Prévisualiser" in button.text_content()
    assert button.get("target") == "_blank" and button.get("rel") == "noopener"
    assert button.get("href").endswith("/signed-pdf" if signed else "/preview")
    assert "download" not in button.get("href")
