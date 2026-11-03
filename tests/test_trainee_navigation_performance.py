import copy
from unittest.mock import Mock

import pytest

import crm_app
import app as host


@pytest.mark.parametrize("training_type", ["APS", "A3P"])
def test_opening_roster_and_sheet_requires_no_business_write_or_remote_lookup(monkeypatch, training_type):
    trainee = {"id":"T", "public_token":"t", "first_name":"Léa", "last_name":"Test",
               "updated_at":"2026-05-12T01:02:03", "cpf_amount":200,
               "sent_email_history":[{"sent_at":"2026-10-30", "subject":"Message", "html":"secret-mail-body"}]}
    training = {"id":"S", "name":training_type, "training_type":training_type, "date_start":"2026-11-03",
                "aps_elearning_enabled":training_type == "APS", "trainees":[trainee]}
    data = {"sessions":[training], "wedof_links":[{"session_id":"S","trainee_id":"T","active":True,
            "external_id":"12345","last_seen_at":host._now_iso(),"cpf_snapshot":{"state":"accepted"}}]}
    monkeypatch.setattr(host, "load_data", lambda *args, **kwargs: copy.deepcopy(data))
    for name in ["save_data", "_refresh_yousign_convention_status_if_pending", "_refresh_cpf_link_from_wedof",
                 "fetch_hebergement_status", "fetch_cnapsv3_tracking_requests"]:
        monkeypatch.setattr(host, name, Mock(side_effect=AssertionError(name)))
    client = crm_app.app.test_client()
    with client.session_transaction() as user:
        user.update(admin_logged_in=True, admin_role="admin")
    for path in ["/admin/sessions/S/trainees", "/admin/sessions/S/stagiaires/T"]:
        response = client.get(path)
        assert response.status_code == 200
        assert "store;dur=" in response.headers["Server-Timing"]
    assert "secret-mail-body" not in response.text
    assert 'js/trainee-sheet.js' in response.text and "static/css/trainee-sheet.css" in response.text
    history = client.get("/api/admin/sessions/S/stagiaires/T/email-history")
    assert history.status_code == 200 and "secret-mail-body" in history.text


def test_badge_cache_is_scoped_and_counts_documents_not_people(monkeypatch):
    client = crm_app.app.test_client()
    path = "/api/admin/navigation-counts"
    assert client.get(path).status_code in (401, 302)
    monkeypatch.setattr(host, "_navigation_counts_cache", host.OrderedDict())
    load = Mock(return_value={})
    monkeypatch.setattr(host, "load_data", load)
    monkeypatch.setattr(host, "_docs_to_control_items", lambda _: [{"pending_count":2},{"pending_count":3}])
    monkeypatch.setattr(host, "_signed_conventions_unseen_items", lambda _: [1])
    monkeypatch.setattr(host, "_visible_cnaps_changes", lambda _, *, cached_only: 4 if cached_only else pytest.fail("remote counter"))
    monkeypatch.setattr(host, "_sales_today_count", lambda _: 3)
    monkeypatch.setattr(host, "partner_has_module", lambda _: True)
    with client.session_transaction() as user:
        user.update(admin_logged_in=True, admin_role="admin")
    assert client.get(path).json == dict(ok=True, documents=5, conventions=1, cnaps=4, sales=3)
    client.get(path); load.assert_called_once()
    with client.session_transaction() as user:
        user.update(admin_role="viewer",partner_id="other")
    assert client.get(path).status_code == 200
    assert load.call_count == 2
