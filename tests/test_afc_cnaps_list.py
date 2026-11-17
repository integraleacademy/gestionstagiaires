from unittest.mock import Mock

import pytest

import app as gestion_app


@pytest.mark.parametrize("archived", [False, True])
def test_afc_list_renders_saved_cnaps_statuses_without_contacting_cnaps(monkeypatch, archived):
    candidates = [
        {"id": "new", "nom": "TEST", "prenom": "Alice"},
        {"id": "known", "nom": "TEST", "prenom": "Paul", "cnaps_status": "TRANSMIS"},
        {"id": "priority", "nom": "TEST", "prenom": "Lou", "cnaps_priority": True},
    ]
    for candidate in candidates:
        candidate["archived"] = archived
    data = {"afc": {"candidates": candidates}}
    lookup = Mock()
    monkeypatch.setattr(gestion_app, "fetch_cnaps_lookup_by_name", lookup)
    monkeypatch.setattr(gestion_app, "load_data", lambda: data)
    monkeypatch.setattr(gestion_app, "save_data", lambda *_: None)
    client = gestion_app.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")

    response = client.get("/admin/afc", query_string={"archives": "1"} if archived else {})

    assert response.status_code == 200
    lookup.assert_not_called()
    html = response.get_data(as_text=True)
    for status in ("INCONNU", "TRANSMIS", "ACCEPTE"):
        assert f"data-cnaps-history='[]'>{status}</span>" in html
    assert html.count('data-refresh-cnaps type="button"') == len(candidates)
    assert not candidates[0].get("cnaps_status")
    assert candidates[2]["cnaps_status"] == "ACCEPTE"
