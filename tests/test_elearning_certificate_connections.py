"""Integral PDF connection evidence, active-time totals and readable pagination."""
import io
import re
from types import SimpleNamespace

from pypdf import PdfReader

from elearning_reporting import ProgressReader, certificate_pdf
from elearning_native.store import NativeElearningStore
from test_manuals_shop import shop


def sample(connections):
    report = {"complete": False, "available": True, "active_time_label": "00 h 00 min 31 s",
              "required_time_label": "62 h 00 min 00 s", "completed_modules": 0, "total_modules": 1,
              "completed_activities": 2, "total_activities": 8,
              "started_at_label": "01/09/2026 à 08:00", "updated_at_label": "01/09/2026 à 19:00",
              "generated_at_label": "10/10/2026 à 09:30", "connections": connections,
              "modules": [{"title": "Le cadre de la sécurité privée", "available": True,
                           "progress_percent": 25, "active_time_label": "00 h 00 min 31 s", "status_label": "En cours"}]}
    partner = {"name": "Centre partenaire du Littoral", "email": "contact@centre.example"}
    order = {"id": "commande-exemple", "course_code": "aps", "group_name": "APS septembre 2026"}
    person = {"id": "participant-exemple", "first_name": "Camille", "last_name": "Martin", "email": "camille@example.test"}
    return report, partner, order, person


def connection(index=1, *, ended=True, seconds=31):
    return {"module": f"Trace-{index:03d}", "started_at_label": "01/09/2026 à 08:00",
            "last_seen_label": "01/09/2026 à 18:59", "ended_at_label": "01/09/2026 à 19:00" if ended else "—",
            "status_label": "Clôturée" if ended else "Dernière activité enregistrée",
            "credited_seconds": seconds, "active_time_label": "DO-NOT-TRUST-PREFORMATTED-DURATION"}


def pdf_text(document):
    return re.sub(r"\s+", " ", " ".join(page.extract_text() for page in document.pages))


def test_long_pdf_includes_every_connection_and_repeats_identification_and_headers():
    values = sample([connection(index) for index in range(1, 138)])
    document = PdfReader(io.BytesIO(certificate_pdf(*values)))
    assert len(document.pages) >= 5
    text = pdf_text(document)
    for index in range(1, 138):
        assert text.count(f"Trace-{index:03d}") == 1
    assert "137 connexions enregistrées" in text
    assert "01 h 10 min 47 s" in text  # 137 * 31 credited seconds, not elapsed hours.
    assert "DO-NOT-TRUST-PREFORMATTED-DURATION" not in text
    assert "Europe/Paris" in text
    for page in document.pages[1:]:
        page_text = re.sub(r"\s+", " ", page.extract_text())
        assert "Camille Martin" in page_text and "Centre partenaire du Littoral" in page_text
        for header in ("MODULE", "DÉBUT", "DERNIÈRE ACTIVITÉ", "FIN ENREGISTRÉE", "ÉTAT", "TEMPS ACTIF"):
            assert header in page_text


def test_open_connection_retains_last_activity_without_inventing_an_end():
    document = PdfReader(io.BytesIO(certificate_pdf(*sample([connection(ended=False)]))))
    text = pdf_text(document)
    assert "18:59" in text and "Non enregistrée" in text and "Fin non enregistrée" in text
    assert "Clôturée" not in text
    assert "Une fin non enregistrée ne signifie pas que le stagiaire est toujours connecté" in text
    assert "TOTAL DU TEMPS ACTIF DANS CE RELEVÉ 00 h 00 min 31 s" in text


def test_connection_totals_preserve_recorded_fractional_seconds():
    document = PdfReader(io.BytesIO(certificate_pdf(*sample([connection(1, seconds=0.6), connection(2, seconds=0.6)]))))
    text = pdf_text(document)
    assert text.count("00 h 00 min 00,60 s") == 2
    assert "TOTAL DU TEMPS ACTIF DANS CE RELEVÉ 00 h 00 min 01,20 s" in text
    assert "durée écoulée" in text


def test_no_connection_still_has_an_identified_zero_time_annex():
    document = PdfReader(io.BytesIO(certificate_pdf(*sample([]))))
    assert len(document.pages) == 2
    text = pdf_text(document)
    assert "Relevé détaillé des connexions" in text and "0 connexions enregistrées" in text
    assert "Aucune connexion au parcours n’est enregistrée à la date d’édition" in text
    assert "Total du temps actif dans ce relevé : 00 h 00 min 00 s" in text
    assert "Camille Martin" in document.pages[-1].extract_text()


def test_specimen_watermark_remains_on_all_connection_annex_pages():
    document = PdfReader(io.BytesIO(certificate_pdf(*sample([connection(index) for index in range(1, 85)]), specimen=True)))
    assert len(document.pages) >= 4
    for page in document.pages:
        text = page.extract_text()
        assert "SPECIMEN" in text and "DONNÉES FICTIVES" in text
    assert "Trace-084" in pdf_text(document)


def test_unavailable_purchased_edition_keeps_its_connections_without_other_versions_or_people(tmp_path):
    _, partner, order, person = sample([])
    order["modules"] = [{"course_id": "archived-module", "course_version": "purchased-v1",
                         "title": "Module archivé commandé", "required_minutes": 1}]
    store = NativeElearningStore(tmp_path / "native_elearning" / "tracking.sqlite3")
    own = {"session_id": "el-" + order["id"], "trainee_id": person["id"],
           "course_id": "archived-module", "course_version": "purchased-v1"}
    contexts = [own, {**own, "course_version": "unbought-v2"}, {**own, "trainee_id": "other-person"},
                {**own, "session_id": "el-other-order"}, {**own, "course_id": "other-module"}]
    for context in contexts:
        tracking = store.start_tracking(context, tab_id="test", activity_id="activity", now_epoch=1000)
        for epoch in (1000, 1015, 1030):
            store.heartbeat(context, tracking["tracking_session_id"], activity_id="activity", visible=True,
                            focused=True, recent_activity=True, media_playing=False, now_epoch=epoch)
    report = ProgressReader(SimpleNamespace(PERSIST_DIR=tmp_path)).report(order, person)
    assert not report["available"] and report["progress_percent"] is None
    assert report["active_seconds"] == 30 and report["completed_modules"] == 0
    assert report["started_at_label"] != "Pas encore commencé"
    assert report["updated_at_label"] != "Aucune activité enregistrée"
    assert len(report["connections"]) == 1
    assert report["connections"][0]["module"] == "Module archivé commandé"
    assert report["connections"][0]["credited_seconds"] == 30
    text = pdf_text(PdfReader(io.BytesIO(certificate_pdf(report, partner, order, person))))
    assert "1 connexion enregistrée" in text and "Module archivé commandé" in text
    assert "TOTAL DU TEMPS ACTIF DANS CE RELEVÉ 00 h 00 min 30 s" in text
    assert "Aucune connexion" not in text


def test_authenticated_certificate_route_includes_real_connection_evidence(shop):
    from test_elearning_reporting import activated, database_dump, report_url, seed_course, tracked

    order, root = seed_course(activated(shop))
    tracked(root, order)
    before = database_dump(root)
    response = shop["client"].get(report_url(order) + "/attestation.pdf")
    assert response.status_code == 200 and response.mimetype == "application/pdf"
    text = pdf_text(PdfReader(io.BytesIO(response.data)))
    assert "Relevé détaillé des connexions" in text and "1 connexion enregistrée" in text
    assert "1. Module de la commande" in text
    assert "TOTAL DU TEMPS ACTIF DANS CE RELEVÉ 00 h 00 min 30 s" in text
    assert "Fin non enregistrée" in text
    assert database_dump(root) == before
