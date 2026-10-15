"""Exercise saved exam copies through the real reader, SQLite and Flask routes."""
import copy
from functools import wraps
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from flask import Blueprint, Flask, abort, redirect, render_template, session
from jinja2 import ChoiceLoader, DictLoader
from pypdf import PdfReader
import pytest

import elearning_reporting as reporting
from elearning_exam_pdf import exam_attempt_pdf, read_stored_attempt
from elearning_native.exams import ExamStore, grade_exam
from elearning_native.store import NativeElearningStore


def exam(exam_id="module-01", version="v1", count=3):
    return {"id": exam_id, "version": version, "title": "Examen archivé", "pass_percent": 80,
            "questions": [{"id": f"q-{i}", "prompt": f"Question archivée numéro {i} : que faire ?",
                           "options": [{"id": "a", "text": "Réponse historique correcte"},
                                       {"id": "b", "text": "Réponse historique incorrecte"}],
                           "answer": "a", "explanation": "Explication enregistrée à la soumission.",
                           "module": "Module 01", "sources": []} for i in range(1, count + 1)]}


def pdf_text(data):
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


@pytest.fixture
def evidence_app(tmp_path, monkeypatch):
    partner = {"id": "partner-one", "name": "Centre de formation exemple", "siret": "12345678900001"}
    person = {"id": "learner-one", "first_name": "Camille", "last_name": "EXEMPLE",
              "email": "camille@example.test", "activated_at": "2026-10-01T10:00:00Z"}
    modules = [{"course_id": f"academy-aps62-{i:02d}", "course_version": "v1", "title": f"Module {i}",
                "required_minutes": 60} for i in range(1, 16)]
    order = {"id": "order-one", "order_type": "elearning", "partner_id": partner["id"],
             "course_code": "aps", "status": "ready", "free_snapshot": True, "total_cents": 0,
             "modules": modules, "learners": [person, {**person, "id": "learner-two"}]}
    courses = {item["course_id"]: {"id": item["course_id"], "version": "v1", "title": item["title"],
               "source": {"type": "academy-aps62"}, "mock_exam_id": f"module-{i:02d}",
               "sections": [{"id": "section", "title": "Séquence", "activities": [
                   {"id": "read", "title": "Lecture", "type": "content", "blocks": []}]}]}
               for i, item in enumerate(modules, 1)}
    def load_course(_catalog, course_id, version=None):
        if course_id not in courses or version != "v1":
            raise reporting.CourseImportError("Snapshot unavailable")
        return copy.deepcopy(courses[course_id])
    monkeypatch.setattr(reporting.CourseCatalog, "load_course", load_course)
    host = SimpleNamespace(PERSIST_DIR=str(tmp_path), _current_partner_id=lambda: session.get("partner_id"))
    db_path = tmp_path / "native_elearning" / "tracking.sqlite3"
    NativeElearningStore(db_path)
    store = ExamStore(db_path)
    def save(exam_id="module-01", attempt_id="a" * 32, *, version="v1", person_id=person["id"],
             order_id=order["id"], count=3, wrong=False):
        definition = exam(exam_id, version, count)
        answers = {q["id"]: "b" if wrong else "a" for q in definition["questions"]}
        result = grade_exam(definition, answers)
        store.save("el-" + order_id, person_id, definition, attempt_id, result)
        with sqlite3.connect(db_path) as db:
            db.execute("UPDATE aps_exam_attempts SET submitted_at='2026-10-13T14:16:25+00:00' WHERE attempt_id=?",
                       (attempt_id,))
        return result
    save()
    data = {"manual_orders": [order]}
    app = Flask(__name__, template_folder=str(Path(reporting.__file__).parent / "templates"))
    app.config.update(TESTING=True, SECRET_KEY="test-only")
    app.jinja_loader = ChoiceLoader([DictLoader({
        "manuals/layout.html": "{% block extra_styles %}{% endblock %}{% block content %}{% endblock %}",
        "manuals/_elearning_ui.html": "{% macro icon(name) %}<span aria-hidden='true'></span>{% endmacro %}",
    }), app.jinja_loader])
    bp = Blueprint("manuals_shop", __name__)
    def customer(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("partner_id"):
                return redirect("/login")
            return view(*args, **kwargs)
        return wrapped
    def partner_data():
        if not session.get("partner_id"):
            abort(403)
        return data, {**partner, "id": session["partner_id"]}
    reporting.register_routes(host, bp, page=lambda name, **values: render_template("manuals/" + name, **values),
                              customer=customer, partner_data=partner_data)
    bp.add_url_rule("/orders/<oid>", endpoint="elearning_order", view_func=lambda oid: "")
    bp.add_url_rule("/groups/<gid>", endpoint="elearning_group", view_func=lambda gid: "")
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as auth:
        auth["partner_id"] = partner["id"]
    base = f"/admin/organisme/e-learning/commandes/{order['id']}/stagiaires/{person['id']}/suivi"
    return SimpleNamespace(app=app, client=client, host=host, partner=partner, person=person, order=order,
                           courses=courses, path=db_path, save=save, base=base)


def copy_url(fixture, exam_id="module-01", version="v1", attempt_id="a" * 32):
    return fixture.base + f"/examens/{exam_id}/{version}/{attempt_id}.pdf"


def dump(path):
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


def test_report_removes_programme_and_shows_copy_links_and_unsubmitted_final(evidence_app):
    fixture = evidence_app
    before = dump(fixture.path)
    response = fixture.client.get(fixture.base)
    assert response.status_code == 200
    html = response.text
    assert "Télécharger le programme PDF" not in html and "/programme.pdf" not in html
    assert "Attestation de suivi" in html and "Relevé des connexions" in html
    assert copy_url(fixture) in html
    assert "Examen blanc final APS" in html and "Non passé" in html
    assert "Disponible après soumission" in html
    assert dump(fixture.path) == before


def test_copy_download_contains_saved_questions_selected_answers_grade_and_identity(evidence_app, monkeypatch):
    fixture = evidence_app
    # Export must remain independent of changes to today's question bank.
    monkeypatch.setattr("elearning_native.exams.load_exam", lambda *_: pytest.fail("Must use saved corrections"))
    before = dump(fixture.path)
    response = fixture.client.get(copy_url(fixture))
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    text = pdf_text(response.data)
    for value in ("Camille EXEMPLE", "Centre de formation exemple", "3 / 3", "100 %", "80 %",
                  "13/10/2026 à 16:16:25", "Question archivée numéro 3", "Réponse du stagiaire",
                  "Réponse historique correcte", "Réponse historique incorrecte", "Réponse attendue",
                  "Explication enregistrée", "a" * 32, "Édition : v1"):
        assert value in text
    assert "non enregistrée" in text  # No per-attempt duration is invented.
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Content-Disposition"].startswith("attachment;")
    assert dump(fixture.path) == before


def test_retakes_keep_separate_copies_and_do_not_overwrite_old_answers(evidence_app):
    fixture = evidence_app
    fixture.save(attempt_id="b" * 32, wrong=True)
    page = fixture.client.get(fixture.base).text
    assert copy_url(fixture) in page and copy_url(fixture, attempt_id="b" * 32) in page
    first = pdf_text(fixture.client.get(copy_url(fixture)).data)
    second = pdf_text(fixture.client.get(copy_url(fixture, attempt_id="b" * 32)).data)
    assert "3 / 3" in first and "Objectif atteint" in first
    assert "0 / 3" in second and "À retravailler" in second and "Réponse incorrecte" in second


def test_final_100_questions_is_listed_and_fully_downloadable(evidence_app):
    fixture = evidence_app
    fixture.save(exam_id="final", attempt_id="f" * 32, count=100)
    page = fixture.client.get(fixture.base)
    assert page.status_code == 200 and "Examen blanc final APS" in page.text
    assert "Non passé" not in page.text
    assert copy_url(fixture, "final", attempt_id="f" * 32) in page.text
    response = fixture.client.get(copy_url(fixture, "final", attempt_id="f" * 32))
    assert response.status_code == 200
    text = pdf_text(response.data)
    assert "100 / 100" in text and "Question archivée numéro 100" in text
    assert text.count("Réponse du stagiaire") == 100
    # A missing teaching snapshot must not hide the already-saved final copy.
    fixture.courses.clear()
    assert fixture.client.get(copy_url(fixture, "final", attempt_id="f" * 32)).status_code == 200


@pytest.mark.parametrize("scenario", ["other_partner", "other_learner", "other_order", "wrong_version",
                                      "unassigned_exam", "inactive", "unpaid", "missing_attempt"])
def test_exam_copy_respects_order_learner_edition_and_entitlement(evidence_app, scenario):
    fixture = evidence_app
    url = copy_url(fixture)
    if scenario == "other_partner":
        with fixture.client.session_transaction() as auth:
            auth["partner_id"] = "partner-other"
    elif scenario == "other_learner":
        url = url.replace("learner-one", "learner-two")
    elif scenario == "other_order":
        fixture.save(order_id="order-other", attempt_id="b" * 32)
        url = copy_url(fixture, attempt_id="b" * 32)
    elif scenario == "wrong_version":
        fixture.save(version="v2")
        url = copy_url(fixture, version="v2")
    elif scenario == "unassigned_exam":
        fixture.save(exam_id="module-16")
        url = copy_url(fixture, exam_id="module-16")
    elif scenario == "inactive":
        fixture.person.pop("activated_at")
    elif scenario == "unpaid":
        fixture.order.update(free_snapshot=False, total_cents=5900)
    elif scenario == "missing_attempt":
        url = copy_url(fixture, attempt_id="c" * 32)
    assert fixture.client.get(url).status_code == 404


def test_copy_requires_login_and_is_in_customer_endpoint_allowlist(evidence_app):
    fixture = evidence_app
    assert "manuals_shop.elearning_progress_exam_copy" in reporting.CUSTOMER_ENDPOINTS
    assert fixture.app.test_client().get(copy_url(fixture)).status_code == 302


@pytest.mark.parametrize("proven_transition", [False, True])
def test_final_copy_only_includes_proven_vtc_predecessor(evidence_app, monkeypatch, proven_transition):
    from elearning_native.vtc_105_migration import BASE_VERSION, VERSION, META_KEY, COURSE_IDS

    fixture = evidence_app
    source = [{"course_id": course_id, "course_version": BASE_VERSION} for course_id in sorted(COURSE_IDS)]
    current = [{**module, "course_version": VERSION} for module in source]
    fixture.order.update(course_code="vtc", modules=current)
    def transitioned(session_view, *_):
        if proven_transition:
            session_view[META_KEY] = {"status": "migrated", "source_modules": source, "modules": current}
        return session_view
    monkeypatch.setattr(reporting, "read_transition_session", transitioned)
    fixture.save(exam_id="vtc-final", version=BASE_VERSION)
    fixture.save(exam_id="vtc-final", version=VERSION, attempt_id="f" * 32)
    old_copy = copy_url(fixture, "vtc-final", BASE_VERSION)
    assert fixture.client.get(old_copy).status_code == (200 if proven_transition else 404)
    assert fixture.client.get(copy_url(fixture, "vtc-final", VERSION, "f" * 32)).status_code == 200
    page = fixture.client.get(fixture.base)
    assert page.status_code == 200 and (old_copy in page.text) == proven_transition
    assert "Non passé" not in page.text


def test_partial_archive_is_explicit_and_does_not_reconstruct_missing_answers(evidence_app):
    fixture = evidence_app
    with sqlite3.connect(fixture.path) as db:
        db.execute("UPDATE aps_exam_attempts SET result_json=?", (json.dumps({
            "score": 2, "total": 3, "percent": 66.7, "passed": False}),))
    response = fixture.client.get(copy_url(fixture))
    assert response.status_code == 200
    text = pdf_text(response.data)
    assert "Détails de la tentative incomplets" in text and "0 question(s) conservée(s) sur 3" in text
    assert "Question archivée" not in text and "2 / 3" in text


def test_missing_history_does_not_create_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    assert read_stored_attempt(path, "s", "p", "final", "v1", "a" * 32) is None
    assert not path.exists()


def test_pdf_escapes_archived_markup_and_handles_long_questions(evidence_app):
    fixture = evidence_app
    result = grade_exam(exam(count=1), {"q-1": "a"})
    result["corrections"][0]["prompt"] = "<b>Texte original</b> & " + "Question longue. " * 250
    result["corrections"][0]["options"][0]["text"] = "<img src='https://example.invalid/private'>"
    attempt = {"exam_id": "module-01", "version": "v1", "attempt_id": "a" * 32,
               "submitted_at": "2026-10-13T14:16:25Z", "result": result}
    content = exam_attempt_pdf(attempt, fixture.partner, fixture.order, fixture.person,
                               logo_path="https://example.invalid/logo.png")
    text = pdf_text(content)
    assert "<b>Texte original</b>" in text and "example.invalid/private" in text
    assert "Réponse du stagiaire" in text
