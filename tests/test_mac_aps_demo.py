"""Public MAC APS excerpt and PDF use fictional data, with no enrolment writes."""
import io
import re
from pathlib import Path

from pypdf import PdfReader

import app as host
import mac_aps_demo as demo
from elearning_native import mac_aps
from test_manuals_shop import all_data, login, shop, signup

BASE = "/e-learning/demo/mac-aps"


def stored_files():
    return {p.relative_to(host.PERSIST_DIR): p.read_bytes() for p in Path(host.PERSIST_DIR).rglob("*") if p.is_file()}


def test_mac_demo_is_half_of_activities_with_coherent_sequential_module_times():
    report = demo.demo_report()
    assert report["progress_percent"] == 50
    assert report["completed_activities"] * 2 == report["total_activities"]
    assert report["active_seconds"] == (7 * 60 + 18) * 60
    assert report["required_time_label"] == "14 h 00 min"
    assert [module["number"] for module in report["modules"]] == ["02", "03", "05"]
    assert [module["required_time_label"] for module in report["modules"]] == ["03 h 00 min", "04 h 00 min", "07 h 00 min"]
    assert sum(module["active_seconds"] for module in report["modules"]) == report["active_seconds"]
    assert sum(connection["credited_seconds"] for connection in report["connections"]) == report["active_seconds"]
    for connection in report["connections"]:
        assert connection["course_id"] in {module["id"] for module in report["modules"]}
        assert connection["course_version"] == mac_aps.VERSION and connection["status_label"] == "Clôturée"
        assert connection["started_at_label"] == connection["date"] + " à " + connection["started"]
        assert connection["last_seen_label"] == connection["ended_at_label"] == connection["date"] + " à " + connection["ended"]
    for index, module in enumerate(report["modules"]):
        assert module["completed_activities"] == (module["total_activities"] if index < 2 else 2)
        assert module["version"] == mac_aps.VERSION
        assert module["module_complete"] is (index < 2)
        assert sum(obj["active_seconds"] for obj in module["timed_objectives"]) == module["active_seconds"]
    assert report["completed_modules"] == 2 and len(report["exams"]) == 2 and not report["complete"]
    assert [module["assessment_summary"]["attempt_count"] for module in report["modules"]] == [13, 17, 1]
    assert [module["score_percent"] for module in report["modules"]] == [100, 100, 2.78]
    assert all(exam["passed"] for exam in report["exams"])
    assert report["final_exam"] is None
    assert [objective["status_label"] for objective in report["modules"][2]["timed_objectives"]] == ["En cours"] + ["À suivre"] * 7
    assert demo.demo_report() == report


def test_mac_demo_views_have_no_persistence_authentication_or_provider_calls(shop, monkeypatch):
    monkeypatch.setattr(host, "_qonto_request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Public demo must not contact Qonto")))
    monkeypatch.setattr(host, "brevo_send_email", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Public demo must not send email")))
    before, files = all_data(shop), stored_files()
    for path in (BASE, BASE + "?view=suivi", BASE + "?view=suivi&module=03", BASE + "?view=suivi&module=05", BASE + "/cours"):
        response = shop["client"].get(path)
        assert response.status_code == 200, response.text
        assert "Démonstration" in response.text and "fictif" in response.text and "MAC APS" in response.text
        assert '"noindex,nofollow,noarchive"' in response.text
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["Permissions-Policy"] == "display-capture=()"
        assert "public_auth_" not in response.text and "access_token" not in response.text
        assert "/elearning/assets/" not in response.text
    assert all_data(shop) == before and stored_files() == files
    with shop["client"].session_transaction() as session:
        assert not any(key.startswith("public_auth_") for key in session)
    assert not (Path(host.PERSIST_DIR) / "native_elearning" / "tracking.sqlite3").exists()


def test_mac_demo_only_projects_the_selected_lesson_and_three_questions(shop):
    sample = demo.sample_lesson()
    assert len(sample["questions"]) == 3 and len(sample["sections"]) == 3
    html = shop["client"].get(BASE + "/cours").text
    assert html.count('data-question-id="') == 3
    assert "data-mac-demo-quiz" in html and "data-mac-demo-check" in html
    assert "<video " in html and BASE + "/media/video" in html and "Lire la transcription" in html
    assert "1 min 26" in html and "n’est pas enregistré" in html
    assert "answer_groups" not in html and "macaps-final" not in html
    assert not re.search(r'<div class="mac-demo-answer"[^>]*>[^<\s]', html)
    course = mac_aps.load_bundled_course(demo.SAMPLE_COURSE, mac_aps.VERSION)
    later_quiz = next(a for a in course["sections"][1]["activities"] if a.get("macaps", {}).get("kind") == "quiz")
    assert all(question["prompt"] not in html for question in later_quiz["macaps"]["questions"])


def test_public_demo_and_its_assets_do_not_start_the_order_worker(shop, monkeypatch):
    # Spy on the already-installed worker callback; no thread or provider can run.
    hook = next(callback for callback in host.app.before_request_funcs[None] if callback.__name__ == "start_order_worker")
    worker = dict(zip(hook.__code__.co_freevars, hook.__closure__))["kick_worker"]
    calls = []
    monkeypatch.setattr(worker, "cell_contents", lambda **kwargs: calls.append(kwargs))
    assets = set()
    for suffix in ("", "?view=suivi", "/cours", "/releve.pdf", "/media/video", "/media/affiche", "/media/sous-titres"):
        response = shop["client"].get(BASE + suffix)
        assert response.status_code == 200
        if response.mimetype == "text/html":
            assets.update(re.findall(r'(?:src|href)="(/static/[^\"]+)"', response.text))
    assert assets
    for path in assets:
        assert shop["client"].get(path).status_code == 200, path
    assert calls == []
    # Ordinary ordering requests still wake their existing worker.
    signup(shop["client"])
    login(shop["client"])
    calls.clear()
    assert shop["client"].get("/admin/organisme/e-learning").status_code == 200
    assert calls == [{"notify": False}]


def test_mac_demo_uses_explicit_media_and_route_allowlists(shop):
    for suffix in ("?view=admin", "?view=suivi&module=01", "?view=suivi&module=04", "/cours/academy-macaps-03", "/media/full", "/media/..%2Fmedia_manifest.json"):
        assert shop["client"].get(BASE + suffix).status_code == 404
    for suffix in ("", "/cours", "/media/video", "/releve.pdf"):
        assert shop["client"].post(BASE + suffix, data={"progress": "100", "course_code": "mac-aps"}).status_code == 405
    video = shop["client"].get(BASE + "/media/video", headers={"Range": "bytes=0-1023"})
    assert video.status_code == 206 and video.mimetype == "video/mp4"
    assert len(video.data) == 1024 and "ftyp" in video.data[:32].decode("latin1")
    assert shop["client"].get(BASE + "/media/affiche").mimetype == "image/jpeg"
    captions = shop["client"].get(BASE + "/media/sous-titres")
    assert captions.status_code == 200 and captions.mimetype == "text/vtt"
    assert captions.text.startswith("WEBVTT") and "00:01:31.295" not in captions.text


def test_mac_pdf_is_a_fixed_partial_specimen_and_never_a_real_stage_attestation(shop):
    before, files = all_data(shop), stored_files()
    response = shop["client"].get(BASE + "/releve.pdf?name=Vraie%20personne&progress=100&partner_id=other")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    pages = PdfReader(io.BytesIO(response.data)).pages
    for page in pages:
        text = page.extract_text()
        assert "SPECIMEN" in text and "DONNÉES FICTIVES" in text
    text = "\n".join(page.extract_text() for page in pages)
    assert "Camille Martin" in text and "MAC APS" in text and "Vraie personne" not in text
    assert "partiel" in text and "07 h 18 min" in text and "14 h 00 min" in text
    assert "Il ne constitue ni une attestation de stage MAC APS" in " ".join(text.split())
    assert "Non renseignée" not in text and "Fin non enregistrée" not in text
    assert "01/10/2026 à 09:00" in text and "05/10/2026 à 09:18" in text
    assert all_data(shop) == before and stored_files() == files


def test_mac_demo_is_available_to_restricted_centres_without_switching_identity(shop):
    signup(shop["client"])
    login(shop["client"])
    before = all_data(shop)
    with shop["client"].session_transaction() as session:
        ids = (session["partner_id"], session["user_id"])
    for suffix in ("", "?view=suivi", "/cours", "/media/video", "/releve.pdf"):
        assert shop["client"].get(BASE + suffix).status_code == 200
    assert all_data(shop) == before
    with shop["client"].session_transaction() as session:
        assert (session["partner_id"], session["user_id"]) == ids
        assert not any(key.startswith("public_auth_") for key in session)


def test_mac_offer_is_available_in_public_shop_and_centre_ordering(shop):
    public = shop["client"].get("/")
    assert public.status_code == 200 and BASE in public.text
    assert "MAC APS" in public.text and "14 h de parcours" in public.text and "60,00 €" in public.text
    assert "reconnaissance réglementaire en 2026 n’est pas vérifiée" in public.text
    signup(shop["client"])
    login(shop["client"])
    for path in ("/admin/organisme", "/admin/organisme/e-learning", "/admin/organisme/e-learning/nouveau?course=mac-aps"):
        response = shop["client"].get(path)
        assert response.status_code == 200 and "MAC APS" in response.text and "60,00 €" in response.text
    form = shop["client"].get("/admin/organisme/e-learning/nouveau?course=mac-aps").text
    assert 'name="course_code" value="mac-aps" checked' in form
    assert "Tarif unique par stagiaire" in form


def test_public_course_page_keeps_mac_price_demo_and_purchase_intent(shop):
    client = shop["client"]
    listing = client.get("/e-learning")
    assert listing.status_code == 200 and "/e-learning/mac-aps" in listing.text
    response = client.get("/e-learning/mac-aps")
    assert response.status_code == 200 and "60,00 € TTC / stagiaire" in response.text
    assert "MAC APS · 14 h" in response.text and "Tarif unique pour tous les organismes" in response.text
    assert "reconnaissance réglementaire en 2026 n’est pas vérifiée" in response.text
    assert BASE in response.text and BASE + "?view=suivi" in response.text
    showcase_video = re.search(r'<video\b[^>]*class="cs-demo-video"[^>]*>.*?</video>',
                               response.text, flags=re.DOTALL)
    assert showcase_video, 'The MAC APS showcase must expose its actual video excerpt'
    assert BASE + '/media/video' in showcase_video.group(0)
    assert '<track' not in showcase_video.group(0), 'The native track must not cover the baked captions'
    assert f'href="{BASE}/cours"' in response.text and 'transcription' in response.text
    assert 'href="/admin/organisme/e-learning/nouveau?course=mac-aps"' in response.text
    assert all(f"{hours} h 00 min" in response.text for hours in (3, 4, 7))
    assert "noindex" in response.headers["X-Robots-Tag"]
    assert "/e-learning/mac-aps" in client.get("/sitemap.xml").text
    redirect = client.get("/admin/organisme/e-learning/nouveau?course=mac-aps")
    assert redirect.status_code == 302
    from urllib.parse import parse_qs, urlsplit
    assert parse_qs(urlsplit(redirect.location).query)["next"] == ["/admin/organisme/e-learning/nouveau?course=mac-aps"]
