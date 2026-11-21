"""Contrats du suivi des RDV CRM dans la page Intégrale EDOF."""
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import edof_crm_appointments_client as bridge


def fake_response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def test_appointment_lookup_uses_exact_crm_origin_and_signed_batch(monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_API_TOKEN", "signed-connection")
    monkeypatch.delenv("GESTION_STAGIAIRES_API_TOKEN", raising=False)
    captured = []
    def post(url, **kwargs):
        captured.append((url, kwargs))
        return fake_response({"ok": True, "appointments": {
            "123456": {"status":"scheduled", "start_at":"2027-01-04T10:00:00+01:00",
                       "host":"Cassandre", "crm_url":
                       "https://assistance-alw9.onrender.com/crm/contacts?fiche=crm-1&retour=pistes"},
            "234567": {"status":"none", "crm_url":
                       "https://assistance-alw9.onrender.com/crm/contacts?fiche=crm-2&retour=pistes"},
            "345678": {"status":"unmatched"}
        }})
    monkeypatch.setattr(bridge.requests, "post", post)
    result = bridge.lookup(["123456","234567","345678"])
    assert result["123456"]["status"] == "scheduled"
    assert result["123456"]["host"] == "Cassandre"
    assert result["234567"]["status"] == "none"
    assert result["345678"] == {"status":"unmatched"}
    assert len(captured) == 1
    url, args = captured[0]
    assert url == "https://assistance-alw9.onrender.com/api/integrations/edof-appointments"
    assert args["allow_redirects"] is False
    body = args["data"]
    assert json.loads(body) == {"folder_ids":["123456","234567","345678"]}
    assert args["headers"][bridge.HEADER] == hmac.digest(
        b"signed-connection",bridge.CONTEXT + body,"sha256").hex()


def test_lookup_falls_back_only_if_first_token_is_rejected(monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_API_TOKEN", "obsolete-secret")
    monkeypatch.setenv("GESTION_STAGIAIRES_API_TOKEN", "current-secret")
    called = []
    def post(url, **kwargs):
        called.append(kwargs["headers"][bridge.HEADER])
        return (fake_response({},401) if len(called) == 1
                else fake_response({"ok":True,"appointments":{"123456":{"status":"unmatched"}}}))
    monkeypatch.setattr(bridge.requests, "post", post)
    assert bridge.lookup(["123456"]) == {"123456":{"status":"unmatched"}}
    assert len(called) == 2


def test_bridge_never_invents_a_rdv_when_crm_does_not_answer(monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_API_TOKEN", "test-secret")
    monkeypatch.delenv("GESTION_STAGIAIRES_API_TOKEN", raising=False)
    monkeypatch.setattr(bridge.requests, "post",lambda *args,**kwargs:fake_response({},503))
    with pytest.raises(bridge.CRMAppointmentsUnavailable):
        bridge.lookup(["123456"])
    monkeypatch.setattr(bridge.requests,"post",lambda *args,**kwargs:fake_response(
        {"ok":True,"appointments":{"123456":{"status":"scheduled","start_at":"not-a-date"}}}))
    with pytest.raises(bridge.CRMAppointmentsUnavailable):
        bridge.lookup(["123456"])


def test_untrusted_crm_links_are_not_rendered_as_links(monkeypatch):
    monkeypatch.setenv("CRM_INTEGRATION_API_TOKEN","test-secret")
    monkeypatch.setattr(bridge.requests,"post",lambda *args,**kwargs:fake_response({
        "ok":True,"appointments":{"123456":{
            "status":"none","crm_url":"https://example.com/steal"
        }}
    }))
    assert bridge.lookup(["123456"])=={"123456":{"status":"none"}}


def test_bridge_is_closed_without_secrets(monkeypatch):
    monkeypatch.delenv("CRM_INTEGRATION_API_TOKEN", raising=False)
    monkeypatch.delenv("GESTION_STAGIAIRES_API_TOKEN", raising=False)
    with pytest.raises(bridge.CRMAppointmentsUnavailable):
        bridge.lookup(["123456"])
    with pytest.raises(ValueError):
        bridge.lookup(["123"])


def test_table_and_detail_show_phone_appointment_before_contact_actions():
    root=Path(__file__).resolve().parents[1]
    template=(root/"templates/integrale_edof.html").read_text(encoding="utf-8")
    assert "<th>RDV téléphonique</th>" in template
    assert 'data-edof-crm-rdv="{{ r.folder_id }}"' in template
    assert 'data-edof-crm-rdv="{{ f.folder_id }}"' in template
    assert "edof-crm-rdv.js" in template
    js=(root/"static/js/edof-crm-rdv.js").read_text(encoding="utf-8")
    assert "data-edof-crm-rdv" in js
    assert "Europe/Paris" in js
    assert "Rapprochement à vérifier" in js


def test_cpf_email_no_longer_mentions_pending_acceptance():
    from flask import Flask
    from edof_cpf_appointment_mail import message_for
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root / "templates"))
    with app.app_context():
        mail = message_for(
            {"folder_id": "123456", "first_name": "Louise", "last_name": "Exemple", "title": "APS"},
            "test@example.invalid",
        )
    for body in (mail["html"], mail["text"]):
        assert "son acceptation n'est pas encore confirmée" not in body
        assert "son acceptation n’est pas encore confirmée" not in body
        assert "rendez-vous téléphonique" in body
