"""Public specimen must never grant purchased access or mutate learner data."""
import io
from pathlib import Path

from pypdf import PdfReader

import app as host
import elearning_demo as demo
from test_manuals_shop import all_data, login, shop, signup


BASE = "/e-learning/demo/aps"


def test_specimen_metrics_and_connections_are_coherent():
    report = demo.demo_report()
    assert report["progress_percent"] == 50
    assert report["completed_activities"] * 2 == report["total_activities"]
    assert report["active_seconds"] == 31 * 3600
    assert sum(m["active_seconds"] for m in report["modules"]) == report["active_seconds"]
    assert sum(c["credited_seconds"] for c in report["connections"]) == report["active_seconds"]
    assert sum(m["completed_activities"] for m in report["modules"]) == report["completed_activities"]
    assert not report["complete"]
    assert demo.demo_report() == report


def test_public_demo_views_and_lesson_are_read_only(shop):
    before = all_data(shop)
    files = {p.relative_to(host.PERSIST_DIR): p.read_bytes() for p in Path(host.PERSIST_DIR).rglob("*") if p.is_file()}
    for path in (BASE, BASE + "?view=suivi", BASE + "?view=suivi&module=01", BASE + "/cours"):
        response = shop["client"].get(path)
        assert response.status_code == 200, response.text
        assert "Démonstration" in response.text
        assert "fictif" in response.text
        assert '"noindex,nofollow,noarchive"' in response.text
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["Permissions-Policy"] == "display-capture=()"
        assert "public_auth_" not in response.text and "access_token" not in response.text
    assert all_data(shop) == before
    assert {p.relative_to(host.PERSIST_DIR): p.read_bytes() for p in Path(host.PERSIST_DIR).rglob("*") if p.is_file()} == files
    with shop["client"].session_transaction() as session:
        assert not any(key.startswith("public_auth_") for key in session)
    lesson = shop["client"].get(BASE + "/cours").text
    assert "contrôle coercitif de police" in lesson  # Actual selected course paragraph.
    assert "data-demo-exercise" in lesson and "Lire le corrigé expliqué" in lesson
    assert "/elearning/assets/" not in lesson


def test_public_query_and_asset_allowlists_do_not_expose_paid_catalogue(shop, monkeypatch, tmp_path):
    for suffix in ("?view=admin", "?view=suivi&module=99", "/cours/academy-aps62-02", "/illustration/other", "/illustration/..%2Fmanifest.json"):
        assert shop["client"].get(BASE + suffix).status_code == 404
    for suffix in ("", "?view=suivi", "/cours", "/attestation.pdf"):
        assert shop["client"].post(BASE + suffix, data={"progress": "100"}).status_code == 405
    calls = []
    image = tmp_path / "test.webp"
    image.write_bytes(b"RIFF-test-fixture")
    def asset(course, version, name):
        calls.append((course, version, name))
        return image
    monkeypatch.setattr(demo, "bundled_asset", asset)
    for name in ("scene", "schema"):
        response = shop["client"].get(BASE + "/illustration/" + name)
        assert response.status_code == 200 and response.mimetype == "image/webp"
    assert {c[0] for c in calls} == {demo.SAMPLE_COURSE}
    assert {c[2] for c in calls} == set(demo.SAMPLE_ASSETS.values())
    for path in ("/elearning/assets/academy-aps62-01/media/aps62/v2/module-01.webp", "/espace/specimen-person/elearning/academy-aps62-01"):
        assert shop["client"].get(path).status_code in {302, 401, 403, 404}
    assert not (Path(host.PERSIST_DIR) / "native_elearning" / "tracking.sqlite3").exists()


def test_specimen_pdf_cannot_be_confused_with_real_attestation(shop):
    before = all_data(shop)
    response = shop["client"].get(BASE + "/attestation.pdf?name=Vraie%20personne&progress=100")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    pages = PdfReader(io.BytesIO(response.data)).pages
    for page in pages:
        text = page.extract_text()
        assert "SPECIMEN" in text and "DONNÉES FICTIVES" in text
    text = "\n".join(p.extract_text() for p in pages)
    assert "Camille Martin" in text and "Vraie personne" not in text
    assert "partiel" in text and "31 h 00 min" in text
    assert all_data(shop) == before
    assert not (Path(host.PERSIST_DIR) / "native_elearning" / "tracking.sqlite3").exists()


def test_restricted_organism_can_visit_demo_without_context_change(shop):
    signup(shop["client"])
    login(shop["client"])
    before = all_data(shop)
    with shop["client"].session_transaction() as session:
        partner_id, user_id = session["partner_id"], session["user_id"]
    for suffix in ("", "?view=suivi", "/cours", "/attestation.pdf"):
        assert shop["client"].get(BASE + suffix).status_code == 200
    assert all_data(shop) == before
    with shop["client"].session_transaction() as session:
        assert session["partner_id"] == partner_id and session["user_id"] == user_id
        assert not any(key.startswith("public_auth_") for key in session)
