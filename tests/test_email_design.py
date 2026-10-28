"""Rendering and delivery contracts for the unified email presentation."""
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

import app as host
from email_design import render_email, normalize_email_text_signature


class EmailAudit(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.shells = 0
        self.headings = 0
        self.links = []
        self.text = []
        self.stack = []
        self.errors = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.shells += int(attrs.get("data-academy-email") == "2026")
        self.headings += int(tag == "h1")
        if tag == "a":
            self.links.append(attrs.get("href"))
        if tag in {"table", "tr", "td", "th", "thead", "tbody"}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in {"table", "tr", "td", "th", "thead", "tbody"}:
            if not self.stack or self.stack.pop() != tag:
                self.errors.append(tag)

    def handle_data(self, value):
        self.text.append(value)


def catalogue():
    client = host.app.test_client()
    with client.session_transaction() as session:
        session.update(admin_logged_in=True, admin_role="admin")
    response = client.get("/admin/outils/mails")
    assert response.status_code == 200

    class Previews(HTMLParser):
        def __init__(self):
            super().__init__()
            self.items = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "data-mail-preview" in attrs:
                self.items.append((attrs["data-mail-title"], attrs["data-mail-preview"]))

    parser = Previews()
    parser.feed(response.get_data(as_text=True))
    return parser.items


def test_every_catalogue_preview_has_one_complete_shell_and_left_aligned_body():
    previews = catalogue()
    assert len(previews) == 20
    for title, source in previews:
        audit = EmailAudit(source)
        assert audit.shells == audit.headings == 1, title
        assert not audit.errors and not audit.stack, (title, audit.errors, audit.stack)
        assert source.count("SIREN 840 899 884") == 1, title
        assert 'class="academy-pad academy-content" align="left"' in source
        assert "font-style:italic" in source and "On avance avec vous." in source
        assert "max-width:640px" in source and "@media(max-width:600px)" in source
        assert "Clément VAILLANT" not in source and "clement-memoji" not in source, title
        assert "".join(audit.text).count("L’équipe Intégrale Academy") == 1, title


@pytest.mark.parametrize("training", ["A3P", "APS", "DIRIGEANT", "SSIAP 1", "VTC"])
def test_document_emails_keep_training_dates_escaped_names_and_download_guidance(training):
    session = {"training_type": training, "date_start": "2026-09-21", "date_end": "2026-11-20"}
    for builder, args in [
        (host._build_aps_entry_attestation_email, ("Camille <Martin>", "2026-09-21", session)),
        (host._build_aps_end_attestation_email, ("Camille <Martin>", "2026-11-20", session)),
        (host._build_aps_convocation_email, ("Camille <Martin>", "2026-09-21", "2026-11-20", session)),
    ]:
        subject, source = builder(*args)
        assert "Intégrale Academy" in subject
        assert "Camille &lt;Martin&gt;" in source and "<Martin>" not in source
        assert "pièce jointe" in source
        audit = EmailAudit(source)
        assert audit.shells == 1 and not audit.errors and not audit.stack


def test_legacy_content_keeps_actions_and_warnings_with_one_team_signature():
    source = render_email('''<h2>📝 Test de français</h2><p>Bonjour Camille,</p>
      <p style="color:#b91c1c">Date limite : 12/11/2026</p>
      <p><a href="https://example.test/access?t=a&amp;key=b" style="display:inline-block;background:#1f8f4a;color:white;padding:12px">Accéder au test</a></p>
      <p>Merci par avance,<br><strong>Clément VAILLANT</strong><br>Directeur Intégrale Academy</p>''')
    audit = EmailAudit(source)
    assert audit.headings == audit.shells == 1
    assert "https://example.test/access?t=a&key=b" in audit.links
    assert "Date limite : 12/11/2026" in source and "color:#b91c1c" in source
    assert "background:#1f8f4a" not in source
    assert "background:#285ac8" in source
    assert "Clément VAILLANT" not in source
    assert "".join(audit.text).count("L’équipe Intégrale Academy") == 1
    assert "Merci par avance," in source
    team_source = render_email("<p>Bonne journée,<br>L'équipe Intégrale Academy</p>")
    assert "".join(EmailAudit(team_source).text).count("L’équipe Intégrale Academy") == 1
    assert "L'équipe Intégrale Academy" not in team_source


@pytest.mark.parametrize("signature", ["team", "clement", "clement_general", "unknown"])
def test_signature_is_team_unless_cassandre_is_explicitly_selected(signature):
    source = render_email("<p>Votre formation vous attend.</p>", signature=signature)
    assert "L’équipe Intégrale Academy" in source
    assert "Clément" not in source and "clement@" not in source and "clement-memoji" not in source
    cassandre = render_email("<p>Votre formation vous attend.</p>", signature="cassandre")
    assert "Cassandre MENARD" in cassandre and "cassandre@integraleacademy.com" in cassandre


def test_saved_mail_signatures_are_replaced_without_changing_recipient_names():
    old = "Bonjour Clément VAILLANT,\nVotre dossier est prêt.\n\nClément VAILLANT - Intégrale Academy"
    updated = normalize_email_text_signature(old)
    assert updated == "Bonjour Clément VAILLANT,\nVotre dossier est prêt.\n\nL’équipe Intégrale Academy"
    source = render_email("<p>Bonjour Camille,</p><p>Clément VAILLANT - Intégrale Academy</p>")
    assert "Clément VAILLANT" not in source
    assert "L’équipe Intégrale Academy" in source


@pytest.mark.parametrize("contact,expected", [("Clément VAILLANT", "L’équipe Intégrale Academy"), ("Cassandre MENARD", "Cassandre MENARD")])
def test_jury_html_and_text_use_an_allowed_signature(contact, expected):
    import ssiap_exam
    from ssiap_exam_mail import render_mail
    config = dict(ssiap_exam.DEFAULTS, date="2026-11-20", time="09:00", contact_name=contact)
    message = render_mail(config, {"first_name": "Camille", "last_name": "MARTIN", "email": "jury@example.test", "role": "president"}, "invitation", 12, "")
    assert expected in message["html"] and expected in message["text"]
    assert "Clément VAILLANT" not in message["html"] and "Clément VAILLANT" not in message["text"]


def test_registration_and_access_builders_escape_names_and_keep_personal_links():
    url = "https://example.test/espace/personal?one=1&two=2"
    for _, source in [host.build_registration_email('<Camille>', 'APS & SSIAP', '21/09/2026', '20/11/2026', url),
                      host.build_student_access_email('<Camille>', 'APS & SSIAP', url)]:
        assert "&lt;Camille&gt;" in source and "APS &amp; SSIAP" in source
        assert url in EmailAudit(source).links


def test_delivery_preserves_designed_html_attachments_text_and_history(monkeypatch):
    calls = []
    monkeypatch.setattr(host, "BREVO_API_KEY", "fixture-key")
    monkeypatch.setattr(host, "BREVO_SENDER_EMAIL", "school@example.test")
    monkeypatch.setattr(host, "_safe_brevo_log", lambda *a, **kw: None)
    monkeypatch.setattr(host.requests, "post", lambda url, **kw: (
        calls.append(kw["json"]) or SimpleNamespace(status_code=201, text="", json=lambda: {"messageId": "fixture-id"})
    ))
    subject, source = host._build_aps_end_attestation_email("Camille", "2026-11-20", {"training_type": "A3P"})
    trainee = {}
    attachment = {"name": "attestation.pdf", "content": "Zml4dHVyZQ=="}
    result = host.brevo_send_email("camille@example.test", subject, source, trainee=trainee,
        attachments=[attachment], text_content="Votre attestation", metadata={"idempotency_key": "fixture-once"})
    assert result["ok"]
    assert calls[0]["htmlContent"] == source
    assert calls[0]["attachment"] == [attachment]
    assert calls[0]["textContent"] == "Votre attestation"
    assert calls[0]["headers"] == {"idempotencyKey": "fixture-once"}
    assert trainee["sent_email_history"][0]["html"] == source
