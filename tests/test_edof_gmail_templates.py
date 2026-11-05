"""Real EFP login wording with synthetic identities and codes only."""

import base64
import time

import pytest

from edof_gmail import SENDER, extract_code


EMAIL = "camille.exemple@gmail.com"
SUBJECT = (
    "{code} est votre code de sécurité EFP Connect pour accéder au service "
    "numérique EDOF pour votre entreprise."
)
BODY = (
    "Bonjour Camille EXEMPLE,\n"
    "Nous avons détecté une tentative de connexion à votre compte utilisateur "
    "au service numérique EDOF pour votre entreprise.\n"
    "Afin de préserver la sécurité de votre compte, nous vous invitons à saisir "
    "le code de sécurité ci-dessous sur EFP Connect\u00a0:\n\n{code}\n\n"
    "Ce code est valable 30 minutes.\n"
    "Après avoir complété la vérification, les connexions suivantes provenant "
    "de cet appareil seront donc reconnues par notre système de sécurité."
)


def part(text, mime="text/plain"):
    return {"mimeType": mime, "body": {
        "data": base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")}}


def message(subject, *parts):
    return {"internalDate": str(int(time.time() * 1000)), "payload": {
        "mimeType": "multipart/alternative", "headers": [
            {"name": "From", "value": SENDER},
            {"name": "To", "value": EMAIL},
            {"name": "Subject", "value": subject},
            {"name": "Authentication-Results", "value":
             "mx.google.com; dmarc=pass header.from=emploi.gouv.fr"},
        ], "parts": list(parts)}}


@pytest.mark.parametrize("source", ["subject", "body", "both"])
@pytest.mark.parametrize("mime", ["text/plain", "text/html"])
def test_current_efp_login_template(source, mime):
    subject = SUBJECT.format(code="123456") if source != "body" else "EFP Connect"
    body = BODY.format(code="123456") if source != "subject" else "Connexion EDOF."
    if mime == "text/html":
        body = "<table>" + "".join("<tr><td>" + line + "</td></tr>" for line in body.splitlines()) + "</table>"
    item = message(subject, part(body, mime))
    assert extract_code(item, EMAIL, time.time() - 1) == "123456"


def test_same_code_in_subject_plain_and_html_is_not_ambiguous():
    body = BODY.format(code="123456")
    item = message(SUBJECT.format(code="123456"), part(body),
                   part("<p>" + body.replace("\n", "<br>") + "</p>", "text/html"))
    assert extract_code(item, EMAIL, time.time() - 1) == "123456"


@pytest.mark.parametrize("other", [
    SUBJECT.format(code="654321"),
    BODY.format(code="654321"),
    "EFP Connect. Votre code de sécurité : 654321",
])
def test_conflicting_codes_across_templates_or_mime_parts_are_rejected(other):
    item = message(SUBJECT.format(code="123456"), part(BODY.format(code="123456")), part(other))
    assert extract_code(item, EMAIL, time.time() - 1) is None


@pytest.mark.parametrize("change", ["old", "sender", "recipient", "authentication", "reset"])
def test_new_template_still_requires_a_fresh_authenticated_login_message(change):
    item = message(SUBJECT.format(code="123456"), part(BODY.format(code="123456")))
    started = time.time() - 1
    if change == "old":
        item["internalDate"] = str(int((started - 1) * 1000))
    elif change == "sender":
        item["payload"]["headers"][0]["value"] = "attacker@example.invalid"
    elif change == "recipient":
        item["payload"]["headers"][1]["value"] = "another@example.invalid"
    elif change == "authentication":
        item["payload"]["headers"][3]["value"] = "mx.google.com; dmarc=fail header.from=emploi.gouv.fr"
    else:
        item["payload"]["parts"].append(part("Réinitialisation de votre mot de passe."))
    assert extract_code(item, EMAIL, started) is None


@pytest.mark.parametrize("code", ["12345", "123456789", "123456x"])
def test_invalid_code_lengths_and_suffixes_are_rejected(code):
    item = message(SUBJECT.format(code=code), part(BODY.format(code=code)))
    assert extract_code(item, EMAIL, time.time() - 1) is None


def test_unlabelled_numbers_are_not_treated_as_codes():
    item = message("Connexion EFP Connect", part("Dossier EDOF 123456. Ce code est valable 30 minutes."))
    assert extract_code(item, EMAIL, time.time() - 1) is None


def test_code_label_and_value_cannot_be_joined_across_mime_parts():
    item = message("Connexion EFP Connect", part("Votre code de sécurité :"), part("123456"))
    assert extract_code(item, EMAIL, time.time() - 1) is None
