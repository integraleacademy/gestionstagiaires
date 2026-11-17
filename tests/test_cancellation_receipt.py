from copy import deepcopy
from unittest.mock import Mock

import app


def test_preview_and_optional_delivery_are_distinct_from_the_financial_summary(monkeypatch):
    t = {"id":"t", "first_name":"Camille", "email":"camille@example.invalid", "registration_cancelled":True,
         "registration_cancelled_at":"2026-11-16T17:00:00Z"}
    data = {"sessions":[{"id":"s", "training_type":"APS", "date_start":"2026-11-02", "date_end":"2026-11-20", "trainees":[t]}]}
    monkeypatch.setattr(app, "load_data", lambda **kw: deepcopy(data))
    monkeypatch.setattr(app, "_atomic_update_data", lambda fn:fn(data))
    send = Mock(return_value={"ok":True})
    monkeypatch.setattr(app, "brevo_send_email", send)
    client = app.app.test_client()
    with client.session_transaction() as auth:
        auth.update(admin_logged_in=True, admin_role="admin")
    url = "/api/sessions/s/stagiaires/t/accuse-annulation/"
    preview = client.post(url+"apercu").json
    assert preview["ok"] and not preview["already_sent"] and not send.called
    for word in ("Camille", "CPF", "CNAPS", "7 jours ouvrés", "14 jours ouvrés", "RIB", "Clément VAILLANT", "clement-memoji.png",
                 "Agent de Prévention et de Sécurité (APS)", "prévue du 02/11/2026 au 20/11/2026",
                 "Les suites de votre annulation", "aucun frais", "<strong>Si nous devons procéder"):
        assert word in preview["html"]
    assert client.post(url+"envoyer", json={}).status_code == 409
    proof = {"preview_token":preview["preview_token"]}
    t["email"] = "autre@example.invalid"
    assert client.post(url+"envoyer", json=proof).status_code == 409 and not send.called
    t["email"] = preview["recipient"]
    assert client.post(url+"envoyer", json=proof).json["ok"]
    assert client.post(url+"envoyer", json=proof).json["already_sent"]
    assert send.call_count == 1 and send.call_args.args == (preview["recipient"],preview["subject"],preview["html"])
    assert "Bonjour Camille," in preview["text"]
    assert preview["text"] == send.call_args.kwargs["text_content"]
    assert send.call_args.kwargs["reply_to"]["email"] == "ecole@integraleacademy.com"
    assert t["sent_email_history"][0]["html"] == preview["html"] and "cancellation_email_sent_at" not in t
    assert client.post(url+"apercu").json["already_sent"]
    t["registration_cancelled"] = False
    assert client.post(url+"envoyer", json=proof).status_code == 409
    with client.session_transaction() as auth:
        auth["admin_role"] = "viewer"
    assert client.post(url+"envoyer", json=proof).status_code == 403
