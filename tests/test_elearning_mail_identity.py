"""Capture real Brevo transport payloads; never deliver an external email."""
import copy
from types import SimpleNamespace

import pytest

import app as host
from test_manuals_shop import shop


# The shop fixture replaces host.brevo_send_email for integration workflows.
# Keep the actual transport so these tests exercise the JSON sent to Brevo.
send_email = host.brevo_send_email


@pytest.fixture
def transport(shop, monkeypatch):
    calls = []
    monkeypatch.setattr(host, "BREVO_API_KEY", "fixture-api-key")
    monkeypatch.setattr(host, "BREVO_SENDER_EMAIL", "platform@example.test")
    monkeypatch.setattr(host, "BREVO_SENDER_NAME", "Plateforme de formation")
    monkeypatch.setattr(host, "_safe_brevo_log", lambda *args, **kwargs: None)
    def post(url, **kwargs):
        calls.append({"url": url, **copy.deepcopy(kwargs)})
        return SimpleNamespace(status_code=201, text="", json=lambda: {"messageId": "fixture-message"})
    monkeypatch.setattr(host.requests, "post", post)
    return calls


def send(**identity):
    return send_email("learner@example.test", "Votre parcours", "<p>Bonjour</p>", metadata={"purpose": "fixture"}, **identity)


def test_existing_callers_keep_default_sender_and_boolean_return(transport):
    assert send_email("learner@example.test", "Votre parcours", "<p>Bonjour</p>") is True
    assert len(transport) == 1
    request = transport[0]
    assert request["url"] == "https://api.brevo.com/v3/smtp/email" and request["timeout"] == 12
    assert request["json"] == {
        "sender": {"name": "Plateforme de formation", "email": "platform@example.test"},
        "to": [{"email": "learner@example.test"}],
        "subject": "Votre parcours", "htmlContent": "<p>Bonjour</p>",
    }


def test_existing_positional_options_and_delivery_metadata_are_unchanged(transport):
    trainee = {}
    attachments = [{"name": "cours.pdf", "content": "ZmFrZS1maXh0dXJl"}]
    result = send_email("learner@example.test", "Votre parcours", "<p>Bonjour</p>",
                        ["office@example.test"], trainee, attachments, "Bonjour", {"idempotency_key": "fixture-once"})
    assert result["ok"] and result["message_id"] == "fixture-message"
    payload = transport[0]["json"]
    assert payload["sender"] == {"name": "Plateforme de formation", "email": "platform@example.test"}
    assert payload["cc"] == [{"email": "office@example.test"}]
    assert payload["attachment"] == attachments and payload["textContent"] == "Bonjour"
    assert payload["headers"] == {"idempotencyKey": "fixture-once"}
    assert "replyTo" not in payload
    assert trainee["sent_email_history"][0]["to_email"] == "learner@example.test"


def test_school_name_verified_sender_and_school_reply_to_are_distinct(transport):
    result = send(sender_name="École des Métiers & Sécurité", sender_email="access@campus.example.test",
                  reply_to={"name": "Équipe pédagogique", "email": "contact@centre.example.test"})
    assert result["ok"] and len(transport) == 1
    payload = transport[0]["json"]
    assert payload["sender"] == {"name": "École des Métiers & Sécurité", "email": "access@campus.example.test"}
    assert payload["replyTo"] == {"name": "Équipe pédagogique", "email": "contact@centre.example.test"}
    assert payload["to"] == [{"email": "learner@example.test"}]


@pytest.mark.parametrize("value", [None, ""])
def test_missing_sender_override_uses_configured_identity_without_reply_to(transport, value):
    assert send(sender_name=value, sender_email=value, reply_to=None)["ok"]
    payload = transport[0]["json"]
    assert payload["sender"] == {"name": "Plateforme de formation", "email": "platform@example.test"}
    assert "replyTo" not in payload


def test_display_names_are_safe_and_reply_to_name_defaults_to_school(transport):
    assert send(sender_name="  Centre\r\nFormation\x00Campus\x7fNord  ",
                reply_to={"email": "contact@centre.example.test"})["ok"]
    payload = transport[0]["json"]
    name = payload["sender"]["name"]
    assert name.split() == ["Centre", "Formation", "Campus", "Nord"]
    assert all(ord(character) >= 32 and ord(character) != 127 for character in name)
    assert payload["replyTo"] == {"name": name, "email": "contact@centre.example.test"}
    assert payload["sender"]["email"] == "platform@example.test"


def test_display_name_overrides_are_limited_to_200_characters(transport):
    assert send(sender_name="A" * 240, reply_to={"name": "B" * 240, "email": "contact@centre.example.test"})["ok"]
    assert transport[0]["json"]["sender"]["name"] == "A" * 200
    assert transport[0]["json"]["replyTo"]["name"] == "B" * 200


@pytest.mark.parametrize("field", ["sender_email", "reply_to"])
@pytest.mark.parametrize("email", [
    "not-an-email", "contact@localhost", "a b@centre.example.test",
    "Centre <contact@centre.example.test>", "contact@centre.example.test\r\nBcc: other@example.test",
    "contact@centre.example.test\n", " contact@centre.example.test", " " * 2, 123,
])
def test_invalid_or_injected_identity_email_is_rejected_before_transport(transport, field, email):
    identity = {field: {"email": email, "name": "Centre"} if field == "reply_to" else email}
    result = send(**identity)
    assert result["ok"] is False and result["not_sent"] is True
    assert result["status_code"] is None and result["error"]
    assert transport == []


@pytest.mark.parametrize("reply", [{}, "", "contact@centre.example.test", {"name": "Centre"}, {"email": ""}])
def test_reply_to_requires_an_explicit_valid_contact_mapping(transport, reply):
    result = send(reply_to=reply)
    assert result["ok"] is False and transport == []


def test_invalid_override_preserves_legacy_false_return(transport):
    assert send_email("learner@example.test", "Votre parcours", "<p>Bonjour</p>",
                      sender_email="sender@example.test\r\nOther: injected") is False
    assert transport == []
