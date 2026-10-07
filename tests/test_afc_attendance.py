import copy
from unittest.mock import Mock

import pytest

import app as gestion_app


@pytest.fixture
def attendance(monkeypatch):
    candidates = [
        {"id": "second", "nom": "ZOLA", "prenom": "Émile", "identifiant_ft": "FT-002", "date_icop": "2026-09-23", "presence_afc_status": "CONVOQUE"},
        {"id": "first", "nom": "ALBERT", "prenom": "Léa", "identifiant_ft": "FT-001", "date_icop": "2026-09-23", "presence_afc_status": "ABSENT", "decision": "NON RETENU", "motif_refus": "CONFIDENTIEL"},
        {"id": "other", "nom": "AUTRE-DATE", "prenom": "Marc", "date_icop": "2026-09-24"},
        {"id": "archived", "nom": "ARCHIVE", "prenom": "Anne", "date_icop": "2026-09-23", "archived": True},
        {"id": "undated", "nom": "SANS-DATE", "prenom": "Paul"},
        {"id": "invalid", "nom": "DATE-INVALIDE", "prenom": "Paul", "date_icop": "2026-02-30"},
    ]
    for candidate in candidates:
        candidate["cnaps_status"] = "INCONNU"
    data = {"afc": {"candidates": candidates}}
    monkeypatch.setattr(gestion_app, "load_data", lambda: data)
    save = Mock()
    monkeypatch.setattr(gestion_app, "save_data", save)
    monkeypatch.setattr(gestion_app, "fetch_cnaps_lookup_by_name", lambda *_: {})
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_role"] = "admin"
    return client, data, save


def test_print_filters_by_date_and_sorts_without_changing_records(attendance):
    client, data, save = attendance
    original = copy.deepcopy(data)
    response = client.get("/admin/afc/feuille-presence?date_icop=2026-09-23")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "23/09/2026" in html
    assert html.index("ALBERT") < html.index("ZOLA")
    assert "FT-001" in html and "FT-002" in html
    for excluded in ("AUTRE-DATE", "ARCHIVE", "SANS-DATE", "DATE-INVALIDE", "CONFIDENTIEL", "NON RETENU"):
        assert excluded not in html
    assert "Signature du candidat" in html
    assert "Signature de l’intervenant" in html
    assert data == original
    save.assert_not_called()


def test_archived_sheet_uses_only_archived_candidates(attendance):
    client, _, _ = attendance
    response = client.get("/admin/afc/feuille-presence?date_icop=2026-09-23&archives=1")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ARCHIVE" in html
    assert "ALBERT" not in html and "ZOLA" not in html
    assert "/admin/afc?archives=1" in html


@pytest.mark.parametrize("date", ["", "incorrect", "2026-02-30", "20260923", "2026-09-23T10:00:00"])
def test_invalid_or_missing_date_does_not_print_all_candidates(attendance, date):
    client, _, save = attendance
    response = client.get("/admin/afc/feuille-presence", query_string={"date_icop": date})
    assert response.status_code == 400
    assert "ALBERT" not in response.get_data(as_text=True)
    save.assert_not_called()


def test_date_without_candidates_returns_not_found(attendance):
    client, _, _ = attendance
    assert client.get("/admin/afc/feuille-presence?date_icop=2026-12-31").status_code == 404


def test_print_requires_admin_login(attendance):
    client, _, _ = attendance
    with client.session_transaction() as session:
        session.clear()
    response = client.get("/admin/afc/feuille-presence?date_icop=2026-09-23")
    assert response.status_code == 302
    assert "/admin/login" in response.location
    assert "ALBERT" not in response.get_data(as_text=True)


def test_date_selector_lists_only_valid_dates_in_current_archive_view(attendance):
    client, _, _ = attendance
    html = client.get("/admin/afc").get_data(as_text=True)
    assert 'action="/admin/afc/feuille-presence"' in html
    assert '<option value="2026-09-23">23/09/2026 · 2 candidats</option>' in html
    assert '<option value="2026-09-24">24/09/2026 · 1 candidat</option>' in html
    assert '<option value="2026-02-30">' not in html
    archived_html = client.get("/admin/afc?archives=1").get_data(as_text=True)
    assert '<option value="2026-09-23">23/09/2026 · 1 candidat</option>' in archived_html
    assert '<option value="2026-09-24">' not in archived_html
    assert 'name="archives" value="1"' in archived_html


def test_no_dates_disables_print_action(attendance):
    client, data, _ = attendance
    data["afc"]["candidates"] = []
    html = client.get("/admin/afc").get_data(as_text=True)
    assert "Aucune date ICOP renseignée" in html
    assert 'id="afcAttendancePrint" type="submit" disabled' in html


def test_multi_page_sheet_repeats_date_and_numbers_candidates(attendance):
    client, data, _ = attendance
    data["afc"]["candidates"] = [
        {"nom": f"CANDIDAT-{i:02}", "prenom": "Léa", "date_icop": "2026-09-23"}
        for i in range(13)
    ]
    html = client.get("/admin/afc/feuille-presence?date_icop=2026-09-23").get_data(as_text=True)
    assert html.count('<main class="sheet">') == 2
    assert html.count("Date ICOP : 23/09/2026") == 2
    assert "Page 1 / 2" in html and "Page 2 / 2" in html
    assert '<td class="number">13</td>' in html
    assert html.count("CANDIDAT-") == 13


def test_candidate_names_are_escaped(attendance):
    client, data, _ = attendance
    data["afc"]["candidates"][0]["nom"] = '<script>alert("test")</script>'
    html = client.get("/admin/afc/feuille-presence?date_icop=2026-09-23").get_data(as_text=True)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
